"""槽位抽取的离线测试。

这些测试验证的是**安全边界**，不是模型能力：模型返回什么都要经过校验，
编造的字段、越界的数值、非法的日期都必须被拒绝。模型真实表现由
`extraction_eval` 用真实 API 度量。
"""

import json
import unittest

from weekend_agent.extraction import (REQUIRED_SLOTS, clarification, extract_slots,
                                      extract_until_complete, merge, missing_slots,
                                      provided_slots)

SLOT_NAMES = ("city", "travel_date", "budget_per_person", "group_size", "tags",
              "indoor", "rain", "start_time", "end_time", "include_meal")


class ScriptedProvider:
    """返回固定内容的假模型，协议与真实 provider 一致。"""

    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

    def complete(self, messages, tools):
        message = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            message["tool_calls"] = self.tool_calls
        return message


def slots_json(**overrides) -> str:
    values = {name: None for name in SLOT_NAMES}
    values.update(overrides)
    return json.dumps(values)


class ExtractionTests(unittest.TestCase):
    def extract(self, content, text="两个人去玩", today="2026-10-04"):
        return extract_slots(text, ScriptedProvider(content=content), today=today)

    def test_all_null_means_nothing_was_stated(self):
        provided = provided_slots(self.extract(slots_json()))
        self.assertEqual(provided, {})
        self.assertEqual(missing_slots(provided), list(REQUIRED_SLOTS))
        self.assertIn("出行日期", clarification(missing_slots(provided)))

    def test_stated_slots_are_extracted_and_normalized(self):
        provided = provided_slots(self.extract(slots_json(budget_per_person=150, include_meal=True)))
        self.assertEqual(provided, {"budget_per_person": 150, "include_meal": True})
        self.assertNotIn("group_size", provided)

    def test_empty_tag_list_counts_as_not_stated(self):
        provided = provided_slots(self.extract(slots_json(tags=[])))
        self.assertNotIn("tags", provided)

    def test_fenced_json_from_model_is_accepted(self):
        # 与 finalize 同一套解析层：模型加围栏不该导致抽取失败。
        content = "```json\n" + slots_json(budget_per_person=80) + "\n```"
        self.assertEqual(provided_slots(self.extract(content)), {"budget_per_person": 80})

    def test_unknown_slot_is_rejected(self):
        # 模型不能凭空引入一个系统不认识的槽位。
        content = json.dumps({**{name: None for name in SLOT_NAMES}, "vip_discount": True})
        with self.assertRaisesRegex(ValueError, "未知字段"):
            self.extract(content)

    def test_out_of_range_value_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "超出有效范围"):
            self.extract(slots_json(budget_per_person=999999))

    def test_illegal_date_is_rejected_by_form_validation(self):
        provided = provided_slots(self.extract(slots_json(travel_date="下周六")))
        with self.assertRaises(ValueError):
            merge({"travel_date": "2026-11-21"}, provided)

    def test_city_outside_the_teaching_dataset_is_rejected(self):
        provided = provided_slots(self.extract(slots_json(city="北京")))
        with self.assertRaisesRegex(ValueError, "只支持杭州"):
            merge({"city": "杭州"}, provided)

    def test_merge_keeps_form_values_for_unstated_slots(self):
        base = {"budget_per_person": 200, "group_size": 2, "travel_date": "2026-11-21"}
        merged = merge(base, {"budget_per_person": 80})
        self.assertEqual(merged["budget_per_person"], 80)
        self.assertEqual(merged["group_size"], 2)

    def test_tool_calls_during_extraction_are_rejected(self):
        provider = ScriptedProvider(content=None, tool_calls=[{"id": "x", "type": "function"}])
        with self.assertRaisesRegex(RuntimeError, "不应该产生工具调用"):
            extract_slots("随便安排", provider, today="2026-10-04")

    def test_empty_text_is_rejected_without_calling_the_model(self):
        with self.assertRaises(ValueError):
            extract_slots("   ", ScriptedProvider(content=slots_json()), today="2026-10-04")

    def test_no_clarification_when_all_required_slots_are_present(self):
        provided = provided_slots(self.extract(
            slots_json(travel_date="2026-11-21", budget_per_person=200, group_size=2)))
        self.assertEqual(missing_slots(provided), [])
        self.assertIsNone(clarification([]))


class ClarificationLoopTests(unittest.TestCase):
    """多轮澄清：追问 → 把回答并回描述 → 重新抽取。"""

    def test_loop_asks_until_required_slots_are_present(self):
        replies = [slots_json(travel_date="2026-11-21", budget_per_person=150, include_meal=True),
                   slots_json(travel_date="2026-11-21", budget_per_person=150,
                              include_meal=True, group_size=3)]

        class Sequenced:
            def __init__(self): self.calls = 0
            def complete(self, messages, tools):
                self.calls += 1
                return {"role": "assistant", "content": replies[min(self.calls - 1, len(replies) - 1)]}

        prompts: list[str] = []
        result = extract_until_complete("11月21号，人均150，中午要吃饭", Sequenced(),
                                        ask=lambda question: prompts.append(question) or "三个人",
                                        today="2026-10-04")
        self.assertTrue(result.complete)
        self.assertEqual(result.rounds, 1)
        self.assertEqual(result.provided["group_size"], 3)
        self.assertIn("同行人数", prompts[0])
        # 用户的补充必须并回描述，让下一轮抽取看到完整上下文。
        self.assertIn("补充说明：三个人", result.text)

    def test_two_rounds_when_two_slots_are_missing(self):
        replies = [slots_json(),
                   slots_json(travel_date="2026-11-21", budget_per_person=150),
                   slots_json(travel_date="2026-11-21", budget_per_person=150, group_size=2)]

        class Sequenced:
            def __init__(self): self.calls = 0
            def complete(self, messages, tools):
                self.calls += 1
                return {"role": "assistant", "content": replies[min(self.calls - 1, len(replies) - 1)]}

        answers = iter(["11月21号，预算150", "两个人"])
        result = extract_until_complete("想出去玩", Sequenced(), ask=lambda q: next(answers),
                                        today="2026-10-04")
        self.assertTrue(result.complete)
        self.assertEqual(result.rounds, 2)
        self.assertEqual(result.provided["group_size"], 2)
        self.assertIn("补充说明：两个人", result.text)
        self.assertIn("补充说明：11月21号，预算150", result.text)

    def test_without_ask_callback_it_returns_the_pending_question(self):
        provider = ScriptedProvider(content=slots_json(budget_per_person=100))
        result = extract_until_complete("预算100", provider, ask=None, today="2026-10-04")
        self.assertFalse(result.complete)
        self.assertEqual(result.asked, [])
        self.assertIn("出行日期", result.pending)

    def test_gives_up_after_max_rounds(self):
        provider = ScriptedProvider(content=slots_json())
        result = extract_until_complete("随便安排", provider, ask=lambda q: "还是不知道",
                                        max_rounds=2, today="2026-10-04")
        self.assertFalse(result.complete)
        self.assertEqual(result.rounds, 2)
        self.assertIsNotNone(result.pending)

    def test_empty_answer_stops_the_loop(self):
        provider = ScriptedProvider(content=slots_json(budget_per_person=100))
        result = extract_until_complete("预算100", provider, ask=lambda q: "   ",
                                        today="2026-10-04")
        self.assertFalse(result.complete)
        self.assertEqual(result.rounds, 1)


if __name__ == "__main__":
    unittest.main()
