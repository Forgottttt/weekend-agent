"""长期记忆的离线测试：事实读写、冲突更新、摘要切分。

摘要本身需要模型，因此这里用假 provider 验证**切分与写盘逻辑**，
不验证摘要质量（那属于模型能力，本项目没有相应评测集）。
"""

import json
import tempfile
import unittest
from pathlib import Path

from weekend_agent.longterm import FACT_KEYS, MemoryStore, summable_prefix, summarize_history
from weekend_agent.memory import SessionStore


def turn(index: int) -> list[dict]:
    """构造一个完整回合：user(STRUCTURED_REQUEST) + assistant + tool。"""
    return [
        {"role": "user", "content": f"STRUCTURED_REQUEST:\n{{\"n\": {index}}}\nUSER_NOTE:\n第{index}轮"},
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": f"c{index}", "type": "function",
                         "function": {"name": "get_weather", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": f"c{index}", "content": "{\"ok\": true}"},
    ]


class MemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = SessionStore(Path(self.folder.name) / "state.sqlite3")
        self.session = self.store.create("demo")
        self.memory = MemoryStore(self.store)

    def test_remember_and_recall_only_keeps_latest(self):
        self.memory.remember(self.session, {"budget_per_person": 200, "group_size": 2})
        changes = self.memory.remember(self.session, {"budget_per_person": 80})
        self.assertEqual(changes, [{"key": "budget_per_person", "value": 80, "previous": 200}])
        self.assertEqual(self.memory.recall(self.session),
                         {"budget_per_person": 80, "group_size": 2})

    def test_history_keeps_superseded_versions(self):
        self.memory.remember(self.session, {"group_size": 2})
        self.memory.remember(self.session, {"group_size": 3})
        self.memory.remember(self.session, {"group_size": 5})
        history = self.memory.history(self.session, "group_size")
        self.assertEqual([item["value"] for item in history], [2, 3, 5])
        self.assertEqual([item["superseded"] for item in history], [True, True, False])

    def test_unchanged_value_is_not_duplicated(self):
        self.memory.remember(self.session, {"budget_per_person": 200})
        self.assertEqual(self.memory.remember(self.session, {"budget_per_person": 200}), [])
        self.assertEqual(len(self.memory.history(self.session, "budget_per_person")), 1)

    def test_unknown_keys_and_none_values_are_ignored(self):
        changes = self.memory.remember(self.session,
                                       {"budget_per_person": 100, "secret": "x", "tags": None})
        self.assertEqual([c["key"] for c in changes], ["budget_per_person"])
        self.assertNotIn("secret", self.memory.recall(self.session))
        self.assertTrue(set(self.memory.recall(self.session)) <= set(FACT_KEYS))

    def test_facts_are_isolated_between_sessions(self):
        other = self.store.create("demo")
        self.memory.remember(self.session, {"group_size": 2})
        self.memory.remember(other, {"group_size": 9})
        self.assertEqual(self.memory.recall(self.session)["group_size"], 2)
        self.assertEqual(self.memory.recall(other)["group_size"], 9)

    def test_non_dict_facts_rejected(self):
        with self.assertRaises(ValueError):
            self.memory.remember(self.session, ["不是字典"])

    def test_summary_round_trip_and_overwrite(self):
        self.assertIsNone(self.memory.load_summary(self.session))
        self.memory.save_summary(self.session, "第一版摘要", 3)
        self.memory.save_summary(self.session, "第二版摘要", 6)
        saved = self.memory.load_summary(self.session)
        self.assertEqual(saved["summary"], "第二版摘要")
        self.assertEqual(saved["covered_until"], 6)


class SummarizeTests(unittest.TestCase):
    def test_summable_prefix_keeps_recent_turns(self):
        messages = [item for index in range(5) for item in turn(index)]
        old, cutoff = summable_prefix(messages, keep_turns=2)
        self.assertEqual(len(old), 9)              # 前 3 个回合共 9 条
        self.assertEqual(cutoff, 9)                # 第 4 个回合从这里开始
        self.assertTrue(messages[cutoff]["content"].startswith("STRUCTURED_REQUEST"))

    def test_summable_prefix_empty_when_within_window(self):
        messages = [item for index in range(2) for item in turn(index)]
        self.assertEqual(summable_prefix(messages, keep_turns=3), ([], 0))

    def test_summarize_history_returns_summary_and_cutoff(self):
        class Provider:
            def __init__(self): self.seen = None
            def complete(self, messages, tools):
                self.seen = messages
                return {"role": "assistant", "content": "用户预算 200 元，两人，想去拍照。"}

        messages = [item for index in range(5) for item in turn(index)]
        summary, cutoff = summarize_history(messages, Provider(), keep_turns=2)
        self.assertIn("预算", summary)
        self.assertEqual(cutoff, 9)

    def test_summarize_returns_none_when_nothing_to_compress(self):
        messages = [item for index in range(2) for item in turn(index)]
        class Provider:
            def complete(self, messages, tools): raise AssertionError("不该调用模型")
        self.assertIsNone(summarize_history(messages, Provider(), keep_turns=3))

    def test_summarize_rejects_tool_calls_or_empty_content(self):
        class BadProvider:
            def complete(self, messages, tools):
                return {"role": "assistant", "content": "", "tool_calls": [{"id": "x"}]}
        messages = [item for index in range(5) for item in turn(index)]
        with self.assertRaises(RuntimeError):
            summarize_history(messages, BadProvider(), keep_turns=2)


if __name__ == "__main__":
    unittest.main()
