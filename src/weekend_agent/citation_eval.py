"""引用忠实性评测（LLM-as-judge）。

只验证"引用 ID 来自本轮检索"是不够的——那只说明来源**存在**，不说明来源**支持**这份方案。
这里让评审模型做一次对照判断：

    给定【已通过约束校验的最终方案】和【本轮检索到的全部资料】，
    指出哪些资料真正支持方案的选择。

由此得到三个指标：

- **引用命中率**（precision）：被引用且评审认为支持的 / 被引用的。低说明引了不相关的资料。
- **引用召回率**（recall）：被引用且支持的 / 评审认为支持的全部。低说明漏引了该引的资料。
- **无关引用率**：被引用但评审认为不支持的 / 被引用的。

诚实边界：这是**模型评审模型**，评审本身有偏差，且方案没有自由文本论证，
因此这里测的是"引用与方案主题的相关性支持"，不是严格意义上的语义蕴含。
"""

import json
import time
from datetime import datetime
from pathlib import Path

from .config import ModelConfig, PROJECT_ROOT
from .jsonio import parse_json_object
from .providers import APIProvider
from .service import PlanningService
from .tools import TripTools, validate_arguments

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "supporting": {"type": "array", "maxItems": 20, "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
    "required": ["supporting", "reason"],
    "additionalProperties": False,
}

JUDGE_SYSTEM = """你是出行方案的引用审核员。你会看到一份**已经通过约束校验**的行程方案，
以及规划时检索到的全部教学资料。请判断：这些资料里哪些**真正支持**这份方案的选择。

判断标准（只看支持关系，不评价方案好坏）：
- 方案选了室内地点，而资料讲雨天室内安排 → 支持
- 方案包含用餐地点，而资料讲午餐与美食安排 → 支持
- 方案多次换乘地点，而资料讲交通衔接与时间留白 → 支持
- 方案受预算约束，而资料讲费用口径 → 支持
- 仅仅因为都提到"杭州"、或用词偶然重合 → **不算支持**

只输出一个 JSON 对象，不要 Markdown 代码围栏，不要解释文字：
{"supporting": ["资料ID", ...], "reason": "一句话说明你的判断依据"}
supporting 只能是上面给出的资料 ID；没有一条支持时返回空数组。"""


def _plan_summary(plan: dict, places: dict[str, dict]) -> str:
    checked = plan.get("checked") or {}
    lines = [f"状态：{plan.get('status')}"]
    for stop in checked.get("schedule", []):
        place = places.get(stop["place_id"], {})
        lines.append(
            f"- {stop['start']}–{stop['end']} {stop['name']}"
            f"（类别={place.get('category', '未知')}，标签={'/'.join(place.get('tags', [])) or '无'}，"
            f"每人{stop['price_per_person']}元）")
    if checked:
        lines.append(f"每人合计 {checked.get('cost_per_person')} 元，"
                     f"全组 {checked.get('total_group_cost')} 元")
        scope = checked.get("cost_scope")
        if scope:
            lines.append(f"费用口径：{scope}")
    return "\n".join(lines)


def _documents_block(documents: dict[str, dict]) -> str:
    return "\n".join(f"[{doc_id}] {doc['title']}：{doc['text']}"
                     for doc_id, doc in documents.items())


def judge_support(plan: dict, documents: dict[str, dict], provider,
                  places: dict[str, dict]) -> dict:
    """让评审模型指出哪些资料支持这份方案。"""
    messages = [
        {"role": "system", "content": JUDGE_SYSTEM},
        {"role": "user", "content": "方案：\n" + _plan_summary(plan, places) +
         "\n\n检索到的资料：\n" + _documents_block(documents)},
    ]
    message = provider.complete(messages, [])
    if not isinstance(message, dict) or message.get("tool_calls"):
        raise RuntimeError("评审模型没有返回有效的判断")
    verdict = parse_json_object(message.get("content"), "引用评审结果")
    validate_arguments(verdict, JUDGE_SCHEMA, "verdict")
    unknown = [doc_id for doc_id in verdict["supporting"] if doc_id not in documents]
    if unknown:
        raise ValueError(f"评审给出了不在检索集里的资料 ID：{unknown}")
    return verdict


def evaluate_citations(output_dir: Path | None = None, cases_path: Path | None = None,
                       provider=None, service: PlanningService | None = None,
                       database: Path | None = None) -> dict:
    """对每个用例跑一次真实规划，再对引用做一次评审。"""
    from .config import DATA_FILE
    source = cases_path or Path(__file__).parent / "data" / "eval_cases.json"
    cases = json.loads(Path(source).read_text(encoding="utf-8"))
    provider = provider or APIProvider(ModelConfig.from_env())
    places = TripTools(DATA_FILE).places

    import tempfile
    folder = None
    if service is None:
        if database is None:
            folder = tempfile.TemporaryDirectory()
            database = Path(folder.name) / "citation.sqlite3"
        service = PlanningService(database)

    rows = []
    for case in cases:
        started = time.perf_counter()
        row: dict = {"id": case["id"], "expected": case["expected_status"]}
        try:
            result = service.plan(case["request"], mode="live")
            plan = result.get("plan")
            if not plan or plan.get("status") != "planned":
                row.update({"skipped": "本轮没有可评审的方案", "status": "no_plan"})
                rows.append(row)
                continue
            documents: dict[str, dict] = {}
            for event in result["events"]:
                if event.get("kind") == "tool" and event.get("name") == "search_guides":
                    for document in event["result"].get("data", {}).get("documents", []):
                        documents[document["id"]] = document
            cited = [citation["id"] for citation in plan.get("citations", [])]
            if not cited:
                row.update({"skipped": "本轮没有引用任何资料", "status": "planned"})
                rows.append(row)
                continue
            verdict = judge_support(plan, documents, provider, places)
            supporting = list(dict.fromkeys(verdict["supporting"]))
            hit = [doc_id for doc_id in cited if doc_id in supporting]
            row.update({
                "status": "judged",
                "cited": cited,
                "supporting": supporting,
                "hit": hit,
                "unrelated": [doc_id for doc_id in cited if doc_id not in supporting],
                "missed": [doc_id for doc_id in supporting if doc_id not in cited],
                "reason": verdict["reason"],
                "retrieved_count": len(documents),
                "duration_seconds": round(time.perf_counter() - started, 3),
            })
        except (ValueError, RuntimeError) as error:
            row.update({"status": "error", "error": str(error),
                        "duration_seconds": round(time.perf_counter() - started, 3)})
        rows.append(row)

    judged = [row for row in rows if row["status"] == "judged"]
    cited_total = sum(len(row["cited"]) for row in judged)
    hit_total = sum(len(row["hit"]) for row in judged)
    unrelated_total = sum(len(row["unrelated"]) for row in judged)
    supporting_total = sum(len(row["supporting"]) for row in judged)
    report = {
        "dataset": "eval_cases_v1_12",
        "case_count": len(rows),
        "judged_count": len(judged),
        "skipped_count": sum(1 for row in rows if "skipped" in row),
        "error_count": sum(1 for row in rows if row["status"] == "error"),
        "cited_total": cited_total,
        "hit_total": hit_total,
        "citation_precision": round(hit_total / cited_total, 4) if cited_total else None,
        "unrelated_citation_rate": round(unrelated_total / cited_total, 4) if cited_total else None,
        "citation_recall": round(hit_total / supporting_total, 4) if supporting_total else None,
        "judge_model_calls": len(judged),
        "judge_input_tokens": getattr(provider, "total_usage", {}).get("prompt_tokens", 0),
        "judge_output_tokens": getattr(provider, "total_usage", {}).get("completion_tokens", 0),
        "limitations": ("这是模型评审模型，评审自身有偏差；方案没有自由文本论证，"
                        "因此测的是引用与方案主题的**相关性支持**，不是严格语义蕴含；"
                        "样本仅 12 例，引用条数很少，比例类指标不稳定。"),
        "cases": rows,
    }
    target_dir = output_dir or PROJECT_ROOT / "outputs"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / datetime.now().strftime("citations_%Y%m%d_%H%M%S_%f.json")
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
                      encoding="utf-8")
    report["report_path"] = str(target)
    if folder is not None:
        folder.cleanup()
    return report
