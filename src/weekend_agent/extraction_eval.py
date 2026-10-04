"""槽位抽取评测。

三个指标分工不同，缺一不可：

- **槽位准确率**：用户说到的条件，模型有没有抽对。低了说明"听不懂"。
- **幻觉误填率**：用户没说到的条件，模型有没有自己编一个。这是抽取环节最危险的失败——
  它会把用户从未提过的预算或人数写进权威约束，而且下游所有校验都会认为这是"用户的要求"。
- **追问触发正确率**：该追问的时候有没有追问。低了说明应用在替用户做假设。
"""

import json
import time
from datetime import datetime
from pathlib import Path

from .config import ModelConfig, PROJECT_ROOT
from .extraction import (REQUIRED_SLOTS, clarification, extract_slots,
                         missing_slots, provided_slots)
from .providers import APIProvider


def _same(actual, expected) -> bool:
    if isinstance(expected, list):
        return isinstance(actual, list) and {str(x) for x in actual} == {str(x) for x in expected}
    if isinstance(expected, bool) or isinstance(actual, bool):
        return actual is expected
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(actual) - float(expected)) < 1e-9
    return actual == expected


def evaluate_extraction(provider=None, output_dir: Path | None = None,
                        cases_path: Path | None = None) -> dict:
    source = cases_path or Path(__file__).parent / "data" / "extraction_cases.json"
    cases = json.loads(Path(source).read_text(encoding="utf-8"))
    provider = provider or APIProvider(ModelConfig.from_env())
    rows = []
    for case in cases:
        started = time.perf_counter()
        row: dict = {"id": case["id"], "text": case["text"],
                     "stated_total": len(case["stated"]), "unstated_total": len(case["unstated"])}
        try:
            slots = extract_slots(case["text"], provider, today=case["today"])
            provided = provided_slots(slots)
            correct, wrong_slots = 0, []
            for name, expected in case["stated"].items():
                if name in provided and _same(provided[name], expected):
                    correct += 1
                else:
                    wrong_slots.append({"slot": name, "expected": expected,
                                        "actual": provided.get(name)})
            hallucinated = [name for name in case["unstated"] if name in provided]
            question = clarification(missing_slots(provided))
            expect_ask = any(name in case["unstated"] for name in REQUIRED_SLOTS)
            row.update({
                "provided": provided, "correct": correct, "wrong": len(wrong_slots),
                "wrong_slots": wrong_slots, "hallucinated": hallucinated,
                "expect_clarification": expect_ask, "asked_clarification": question is not None,
                "clarification_correct": expect_ask == (question is not None),
                "question": question,
            })
        except (ValueError, RuntimeError) as error:
            row.update({"error": str(error), "correct": 0, "wrong": len(case["stated"]),
                        "wrong_slots": [], "hallucinated": [], "clarification_correct": False,
                        "expect_clarification": any(n in case["unstated"] for n in REQUIRED_SLOTS),
                        "asked_clarification": False, "question": None})
        row["duration_seconds"] = round(time.perf_counter() - started, 3)
        rows.append(row)

    stated_total = sum(row["stated_total"] for row in rows)
    unstated_total = sum(row["unstated_total"] for row in rows)
    correct_total = sum(row["correct"] for row in rows)
    hallucinated_total = sum(len(row["hallucinated"]) for row in rows)
    ask_correct = sum(row["clarification_correct"] for row in rows)
    report = {
        "dataset": "extraction_cases_v1_20",
        "case_count": len(rows),
        "errors": sum(1 for row in rows if "error" in row),
        "model_calls": len(rows),
        "slot_accuracy": round(correct_total / stated_total, 4) if stated_total else None,
        "stated_slots": stated_total, "correct_slots": correct_total,
        "hallucination_rate": round(hallucinated_total / unstated_total, 4) if unstated_total else None,
        "unstated_slots": unstated_total, "hallucinated_slots": hallucinated_total,
        "clarification_accuracy": round(ask_correct / len(rows), 4) if rows else None,
        "clarification_correct_cases": ask_correct,
        "median_seconds": sorted(row["duration_seconds"] for row in rows)[len(rows) // 2] if rows else None,
        "limitations": ("20 例小样本，标签由本仓库作者人工标注，"
                        "标注口径以「用户明确说到」为准，兴趣标签的归类存在判断余地；"
                        "因此这些数字反映的是本项目抽取口径下的相对表现，不是通用抽取能力评测。"),
        "cases": rows,
    }
    target_dir = output_dir or PROJECT_ROOT / "outputs"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / datetime.now().strftime("extraction_%Y%m%d_%H%M%S_%f.json")
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    report["report_path"] = str(target)
    return report
