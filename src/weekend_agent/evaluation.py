"""固定回归集、规则基线和独立最终校验。离线数字不代表模型能力。"""

import json
import statistics
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from .config import PROJECT_ROOT
from .finalize import verify_final
from .request import TripRequest
from .service import PlanningService
from .tools import ToolRegistry, TripTools


def evaluate(mode: str = "demo", output_dir: Path | None = None) -> dict:
    cases = json.loads((Path(__file__).parent / "data" / "eval_cases.json").read_text(encoding="utf-8"))
    rows = []
    with TemporaryDirectory() as folder:
        service = PlanningService(Path(folder) / "eval.sqlite3")
        for case in cases:
            request = TripRequest.from_dict(case["request"])
            fixed = {"status": "planned", "stops": [{"place_id": "p01", "start": "10:00"},
                     {"place_id": "f01", "start": "12:00"}, {"place_id": "p10", "start": "14:00"}],
                     "guide_ids": []}
            tools = TripTools(rain=request.rain, include_meal=request.include_meal)
            try:
                verify_final(json.dumps(fixed), request, ToolRegistry(tools), set(tools.places), {})
                baseline_valid = True
            except ValueError:
                baseline_valid = False
            try:
                result = service.plan(case["request"], mode=mode)
                actual = result["plan"]["status"]
                rows.append({"id": case["id"], "expected": case["expected_status"], "actual": actual,
                             "pass": actual == case["expected_status"], "baseline_valid": baseline_valid,
                             "duration_seconds": result["duration_seconds"], "provider_calls": result["provider_calls"],
                             "tool_calls": result["tool_calls"], "model_calls": result["model_calls"],
                             "final_checks": result.get("final_checks", 0),
                             "submitted_via": result.get("submitted_via"),
                             "http_attempts": result["http_attempts"],
                             "input_tokens": result["input_tokens"], "output_tokens": result["output_tokens"],
                             "checked": result["last_check"]})
            except (ValueError, RuntimeError) as error:
                rows.append({"id": case["id"], "expected": case["expected_status"], "actual": "error",
                             "pass": False, "baseline_valid": baseline_valid, "error": str(error),
                             **getattr(error, "metrics", {})})
    durations = sorted(row["duration_seconds"] for row in rows if "duration_seconds" in row)
    planned = [row for row in rows if row["actual"] == "planned"]
    report = {"mode": mode, "dataset": "eval_cases_v1_12", "case_count": len(rows),
              "passed": sum(row["pass"] for row in rows),
              "planned_count": len(planned), "validated_plan_count": sum(bool(row["checked"]["valid"]) for row in planned),
              "baseline_valid_count": sum(row["baseline_valid"] for row in rows),
              # 终审被拒后重试的比例，用来衡量「模型输出不合法」这类格式问题的严重程度。
              "repaired_count": sum(1 for row in rows if row.get("final_checks", 0) > 1),
              "final_checks_total": sum(row.get("final_checks", 0) for row in rows),
              # 走文本兜底而不是 submit_plan 的用例数：这个数字应当趋近于 0。
              "text_fallback_count": sum(1 for row in rows if row.get("submitted_via") == "text"),
              "model_calls": sum(row.get("model_calls", 0) for row in rows),
              "http_attempts": sum(row.get("http_attempts", 0) for row in rows),
              "input_tokens": sum(row.get("input_tokens", 0) for row in rows),
              "output_tokens": sum(row.get("output_tokens", 0) for row in rows),
              "median_seconds": statistics.median(durations) if durations else None,
              "limitations": "开发期小型回归集；基线较弱；demo不代表模型能力；计数包含失败任务，usage仅含已收到的响应，丢失响应可能仍计费；未做盲测或用户研究。",
              "cases": rows}
    target_dir = output_dir or PROJECT_ROOT / "outputs"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / datetime.now().strftime("eval_%Y%m%d_%H%M%S_%f.json")
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    report["report_path"] = str(target)
    return report
