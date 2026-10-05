"""引用评审的离线测试：验证指标口径与输入校验，不验证评审模型本身的能力。"""

import json
import tempfile
import unittest
from pathlib import Path

from weekend_agent.citation_eval import evaluate_citations, judge_support

CITED = {"id": "g_food", "title": "美食与午餐", "text": "午餐安排与费用口径。"}
OTHER = {"id": "d0001", "title": "示例资料", "text": "另一篇教学资料。"}


def plan_result(citations=(CITED,), documents=(CITED, OTHER)):
    schedule = [{"place_id": "f04", "name": "示例面馆", "start": "12:00", "end": "12:45",
                 "price_per_person": 25}]
    return {
        "plan": {"status": "planned", "citations": list(citations),
                 "checked": {"schedule": schedule, "cost_per_person": 25,
                             "total_group_cost": 50, "cost_scope": "仅含地点与相邻交通。"}},
        "events": [{"kind": "tool", "name": "search_guides",
                    "result": {"ok": True, "data": {"documents": list(documents)}}}],
    }


class FakeService:
    def __init__(self, results):
        self.results = list(results)
        self.index = 0

    def plan(self, values, **kwargs):
        result = self.results[self.index]
        self.index += 1
        return result


class JudgeProvider:
    def __init__(self, content):
        self.content = content
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        return {"role": "assistant", "content": self.content}


def verdict(supporting):
    return json.dumps({"supporting": supporting, "reason": "测试用判断"})


class CitationEvalTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.cases = Path(self.folder.name) / "cases.json"
        self.cases.write_text(json.dumps([
            {"id": "c1", "request": {}, "expected_status": "planned"},
            {"id": "c2", "request": {}, "expected_status": "planned"},
            {"id": "c3", "request": {}, "expected_status": "no_plan"},
        ]), encoding="utf-8")
        # c3 没有方案，应当被跳过而不计入比例。
        no_plan = {"plan": {"status": "no_plan", "citations": []}, "events": []}
        self.service = FakeService([plan_result(), plan_result(), no_plan])

    def run_eval(self, content):
        provider = JudgeProvider(content)
        report = evaluate_citations(output_dir=Path(self.folder.name), cases_path=self.cases,
                                    provider=provider, service=self.service)
        return report, provider

    def test_hit_and_unrelated_are_computed_separately(self):
        report, provider = self.run_eval(verdict(["g_food"]))
        self.assertEqual(report["case_count"], 3)
        self.assertEqual(report["judged_count"], 2)
        self.assertEqual(report["skipped_count"], 1)
        self.assertEqual(report["cited_total"], 2)
        self.assertEqual(report["hit_total"], 2)
        self.assertEqual(report["citation_precision"], 1.0)
        self.assertEqual(report["unrelated_citation_rate"], 0.0)
        self.assertEqual(report["citation_recall"], 1.0)
        self.assertEqual(provider.calls, 2)

    def test_unrelated_citation_is_counted(self):
        report, _ = self.run_eval(verdict([]))
        self.assertEqual(report["hit_total"], 0)
        self.assertEqual(report["citation_precision"], 0.0)
        self.assertEqual(report["unrelated_citation_rate"], 1.0)
        self.assertIsNone(report["citation_recall"])

    def test_missed_support_lowers_recall_only(self):
        # 评审认为两篇都支持，但方案只引了一篇：命中率满分，召回率只有一半。
        result = plan_result()
        result["events"][0]["result"]["data"]["documents"] = [CITED, OTHER]
        service = FakeService([result, result, result])
        report = evaluate_citations(output_dir=Path(self.folder.name), cases_path=self.cases,
                                    provider=JudgeProvider(verdict(["g_food", "d0001"])),
                                    service=service)
        self.assertEqual(report["citation_precision"], 1.0)
        self.assertEqual(report["citation_recall"], 0.5)

    def test_judge_cannot_invent_document_ids(self):
        provider = JudgeProvider(verdict(["d9999"]))
        with self.assertRaisesRegex(ValueError, "不在检索集"):
            judge_support(plan_result()["plan"], {"g_food": CITED}, provider, {})

    def test_malformed_judge_output_is_rejected(self):
        provider = JudgeProvider("我觉得都挺相关的。")
        with self.assertRaisesRegex(ValueError, "不是合法 JSON"):
            judge_support(plan_result()["plan"], {"g_food": CITED}, provider, {})

    def test_judge_output_accepts_markdown_fence(self):
        provider = JudgeProvider("```json\n" + verdict(["g_food"]) + "\n```")
        self.assertEqual(judge_support(plan_result()["plan"], {"g_food": CITED}, provider, {}),
                         {"supporting": ["g_food"], "reason": "测试用判断"})


if __name__ == "__main__":
    unittest.main()
