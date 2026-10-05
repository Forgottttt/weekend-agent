"""跨运行聚合统计：把 plan_runs 里已经存下的运行快照整理成可观测指标。

只读 plan_runs，不写库、不依赖 HTTP，因此可以直接用临时数据库做单元测试。
历史快照改过结构是常态：字段缺失时按 0 或跳过处理，绝不让面板因为一条老记录而整页报错。
"""

import json
import math
import sqlite3
import statistics
from typing import Any

# 与 result.plan.status 的取值保持一致；no_plan 表示"正常返回但没有方案"，不是异常。
PLANNED_STATUS = "planned"
NO_PLAN_LABEL = "no_plan"
ERROR_LABEL = "error"
UNKNOWN_TOOL_LABEL = "未知工具"
UNKNOWN_VIA_LABEL = "final_rejected:未知通道"


def _number(value: Any) -> float | None:
    """返回有限数值；bool、字符串、NaN、Infinity 一律当作缺失。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return float(value)


def _count(value: Any) -> int:
    """非负整数计数，缺失或非法时返回 0。"""
    number = _number(value)
    return int(number) if number is not None and number >= 0 else 0


def _percentile(values: list[float], ratio: float) -> float:
    """就近取整法（nearest-rank）：小样本下比插值更贴近"排在第 95 百分位的那一次"。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(ratio * len(ordered)) - 1))
    return round(ordered[index], 3)


def _parse_result(raw: Any) -> dict:
    """快照里的 result 可能是文本、可能损坏；解析失败时返回空 dict 而不是抛异常。"""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return {}
    return raw if isinstance(raw, dict) else {}


def _events(result: dict) -> list:
    """events 原样取出；缺失或不是列表时返回空列表。"""
    events = result.get("events")
    return events if isinstance(events, list) else []


def _event_dicts(result: dict) -> list[dict]:
    return [event for event in _events(result) if isinstance(event, dict)]


def _model_calls(result: dict) -> int:
    """真实模型调用数；老快照没有 model_calls 字段时退回 provider_calls。"""
    calls = _number(result.get("model_calls"))
    return _count(calls if calls is not None else result.get("provider_calls"))


def classify_result(result: Any) -> str:
    """把一次运行归到 planned / no_plan / error 三类。

    error：result 缺失、带 error 字段、出现 error 事件，或根本没有 plan 字段；
    no_plan：正常返回、也有 plan 结构，但结论不是 planned（例如没找到候选）；
    planned：plan.status == "planned"，是成功率的分子。
    """
    if not isinstance(result, dict) or not result or result.get("error"):
        return ERROR_LABEL
    if any(event.get("kind") == "error" for event in _event_dicts(result)):
        return ERROR_LABEL
    plan = result.get("plan")
    if not isinstance(plan, dict):
        return ERROR_LABEL
    return PLANNED_STATUS if plan.get("status") == PLANNED_STATUS else NO_PLAN_LABEL


def _run_metrics(result: Any) -> dict:
    """一次运行的关键指标；列表和事件时间线共用，缺失字段按 0／None 处理。"""
    data = result if isinstance(result, dict) else {}
    plan = data.get("plan")
    plan_status = plan.get("status") if isinstance(plan, dict) else None
    tools = [event for event in _event_dicts(data) if event.get("kind") == "tool"]
    rejected = [event for event in _event_dicts(data) if event.get("kind") == "final_rejected"]
    duration = _number(data.get("duration_seconds"))
    return {
        "outcome": classify_result(data),
        "plan_status": plan_status if isinstance(plan_status, str) else None,
        "duration_seconds": round(duration, 3) if duration is not None and duration >= 0 else None,
        "input_tokens": _count(data.get("input_tokens")),
        "output_tokens": _count(data.get("output_tokens")),
        "model_calls": _model_calls(data),
        "provider_calls": _count(data.get("provider_calls")),
        "tool_calls": _count(data.get("tool_calls")),
        "final_checks": _count(data.get("final_checks")),
        "submitted_via": data.get("submitted_via") if isinstance(data.get("submitted_via"), str) else None,
        "mode": data.get("mode") if isinstance(data.get("mode"), str) else None,
        "model": data.get("model") if isinstance(data.get("model"), str) else None,
        "event_count": len(_events(data)),
        "tool_error_count": sum(1 for event in tools
                                if not isinstance(event.get("result"), dict)
                                or event["result"].get("ok") is not True),
        "final_rejected_count": len(rejected),
    }


def _ranked(histogram: dict[str, int]) -> dict[str, int]:
    """按次数从多到少排序，次数相同按名称，保证同一份数据输出稳定。"""
    return dict(sorted(histogram.items(), key=lambda item: (-item[1], item[0])))


def _load_rows(store, limit: int) -> list[tuple]:
    """最近 limit 条运行快照，新的在前。只读，老库缺表时按"没有数据"处理。"""
    try:
        with store.connect() as connection:
            return connection.execute(
                """SELECT id,session_id,version,result,created_at FROM plan_runs
                   ORDER BY id DESC LIMIT ?""", (limit,)).fetchall()
    except sqlite3.OperationalError:
        return []


def collect_stats(store, limit: int = 200) -> dict:
    """聚合最近 limit 次运行的观测指标。

    failure_histogram 统计"失败归因出现次数"而不是运行数：一次运行可以同时有终审被拒
    和最终成功（修复后通过），所以这里按事件计数；error / no_plan 按运行计数。
    """
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("统计条数必须在1–1000之间")

    rows = _load_rows(store, limit)
    tool_histogram: dict[str, int] = {}
    failure_histogram: dict[str, int] = {}
    durations: list[float] = []
    recent_runs: list[dict] = []
    planned_runs = repair_runs = text_fallback_runs = 0
    totals = {"input_tokens": 0, "output_tokens": 0, "model_calls": 0,
              "provider_calls": 0, "tool_calls": 0, "tool_errors": 0}

    for run_id, session_id, version, raw_result, created_at in rows:
        result = _parse_result(raw_result)
        outcome = classify_result(result)
        if outcome == PLANNED_STATUS:
            planned_runs += 1
        else:
            failure_histogram[outcome] = failure_histogram.get(outcome, 0) + 1

        for event in _event_dicts(result):
            if event.get("kind") == "tool":
                name = event.get("name")
                label = name if isinstance(name, str) and name else UNKNOWN_TOOL_LABEL
                tool_histogram[label] = tool_histogram.get(label, 0) + 1
            elif event.get("kind") == "final_rejected":
                via = event.get("via")
                label = f"final_rejected:{via}" if isinstance(via, str) and via else UNKNOWN_VIA_LABEL
                failure_histogram[label] = failure_histogram.get(label, 0) + 1

        metrics = _run_metrics(result)
        if metrics["duration_seconds"] is not None:
            durations.append(metrics["duration_seconds"])
        if metrics["final_checks"] > 1:
            repair_runs += 1
        if metrics["submitted_via"] == "text":
            text_fallback_runs += 1
        for key in ("input_tokens", "output_tokens", "model_calls", "provider_calls", "tool_calls"):
            totals[key] += metrics[key]
        totals["tool_errors"] += metrics["tool_error_count"]

        request = result.get("request")
        request = request if isinstance(request, dict) else {}
        recent_runs.append({
            "run_id": run_id, "session_id": session_id, "version": version,
            "created_at": created_at if isinstance(created_at, str) else None,
            "travel_date": request.get("travel_date"), "budget_per_person": request.get("budget_per_person"),
            **metrics,
        })

    run_count = len(rows)
    return {
        "limit": limit,
        "run_count": run_count,
        # 一次都没有运行时按 0.0 返回，前端不必再判断 null。
        "success_rate": round(planned_runs / run_count, 4) if run_count else 0.0,
        "planned_runs": planned_runs,
        "no_plan_runs": failure_histogram.get(NO_PLAN_LABEL, 0),
        "error_runs": failure_histogram.get(ERROR_LABEL, 0),
        "median_duration_seconds": round(statistics.median(durations), 3) if durations else 0.0,
        "p95_duration_seconds": _percentile(durations, 0.95),
        "total_input_tokens": totals["input_tokens"],
        "total_output_tokens": totals["output_tokens"],
        "sum_model_calls": totals["model_calls"],
        "sum_provider_calls": totals["provider_calls"],
        "sum_tool_calls": totals["tool_calls"],
        "tool_error_count": totals["tool_errors"],
        "tool_histogram": _ranked(tool_histogram),
        "failure_histogram": _ranked(failure_histogram),
        "repair_runs": repair_runs,
        "text_fallback_runs": text_fallback_runs,
        "latest_run_at": rows[0][4] if rows and isinstance(rows[0][4], str) else None,
        "recent_runs": recent_runs,
    }


def collect_trace(store, run_id: int) -> dict:
    """一次运行的完整事件时间线：events 原样返回，另附关键指标与请求条件。"""
    if type(run_id) is not int or run_id <= 0:
        raise ValueError("生成记录编号不正确")
    with store.connect() as connection:
        row = connection.execute(
            "SELECT id,session_id,version,result,created_at FROM plan_runs WHERE id=?",
            (run_id,)).fetchone()
    if row is None:
        raise ValueError("生成记录不存在")
    result = _parse_result(row[3])
    request = result.get("request")
    return {
        "run_id": row[0], "session_id": row[1], "version": row[2],
        "created_at": row[4] if isinstance(row[4], str) else None,
        "request": request if isinstance(request, dict) else {},
        "metrics": _run_metrics(result),
        "events": _events(result),
    }
