"""collect_stats / collect_trace 的聚合与容错测试：用临时 SQLite 构造各种运行快照。"""

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from weekend_agent.memory import SessionStore
from weekend_agent.server import create_server
from weekend_agent.service import PlanningService
from weekend_agent.stats import classify_result, collect_stats, collect_trace


def tool_event(name="search_places", ok=True, round_index=1):
    return {"kind": "tool", "round": round_index, "name": name, "arguments": {},
            "result": {"ok": ok} if ok else {"ok": False, "error": "工具参数不是有效的 JSON"}}


def planned(events=None, **extra):
    """一次成功运行的快照；extra 可覆盖任意字段，用来模拟缺字段的老快照。"""
    return {"plan": {"status": "planned"}, "events": events if events is not None else [tool_event()],
            "duration_seconds": 1.0, "input_tokens": 10, "output_tokens": 5,
            "provider_calls": 2, "model_calls": 2, "tool_calls": 1, "final_checks": 1,
            "submitted_via": "submit_plan", "mode": "live", "request": {"travel_date": "2026-11-21"},
            **extra}


class StatsTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = SessionStore(Path(self._tmp.name) / "stats.sqlite3")
        self.session_id = self.store.create("demo")
        self.version = 0

    def tearDown(self):
        self._tmp.cleanup()

    def add_run(self, result, raw=None, created_at="2026-01-01 00:00:00"):
        """写入一条 plan_runs；raw 用于注入损坏的 JSON 文本。"""
        self.version += 1
        payload = raw if raw is not None else json.dumps(result, ensure_ascii=False)
        with self.store.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO plan_runs(session_id,version,request,result,created_at) VALUES(?,?,?,?,?)""",
                (self.session_id, self.version, "{}", payload, created_at))
        return cursor.lastrowid


class CollectStatsTests(StatsTestBase):
    def test_empty_database_returns_zeroes(self):
        stats = collect_stats(self.store)
        self.assertEqual(stats["run_count"], 0)
        self.assertEqual(stats["success_rate"], 0.0)
        self.assertEqual(stats["median_duration_seconds"], 0.0)
        self.assertEqual(stats["p95_duration_seconds"], 0.0)
        self.assertEqual(stats["total_input_tokens"], 0)
        self.assertEqual(stats["tool_histogram"], {})
        self.assertEqual(stats["failure_histogram"], {})
        self.assertEqual(stats["recent_runs"], [])
        self.assertIsNone(stats["latest_run_at"])

    def test_success_rate_counts_only_planned_runs(self):
        for _ in range(3):
            self.add_run(planned())
        self.add_run({"plan": {"status": "no_plan"}, "events": []})
        self.add_run({"answer": "没有方案", "plan": None})
        stats = collect_stats(self.store)
        self.assertEqual(stats["run_count"], 5)
        self.assertEqual(stats["planned_runs"], 3)
        self.assertEqual(stats["success_rate"], 0.6)

    def test_no_plan_is_listed_separately_from_error(self):
        self.add_run({"plan": {"status": "no_plan"}, "events": []})
        self.add_run({"plan": None, "events": []})
        stats = collect_stats(self.store)
        self.assertEqual(stats["no_plan_runs"], 1)
        self.assertEqual(stats["error_runs"], 1)
        self.assertEqual(stats["failure_histogram"], {"error": 1, "no_plan": 1})
        self.assertEqual(stats["success_rate"], 0.0)

    def test_error_event_marks_run_as_error(self):
        self.add_run(planned(events=[{"kind": "error", "error": "服务内部错误"}]))
        stats = collect_stats(self.store)
        self.assertEqual(stats["error_runs"], 1)
        self.assertEqual(stats["planned_runs"], 0)

    def test_corrupt_and_non_object_snapshots_do_not_crash(self):
        self.add_run(None, raw="{ 这不是 JSON")
        self.add_run(None, raw="[1,2,3]")
        self.add_run(None, raw="")
        stats = collect_stats(self.store)
        self.assertEqual(stats["run_count"], 3)
        self.assertEqual(stats["error_runs"], 3)
        self.assertEqual(stats["sum_tool_calls"], 0)
        self.assertEqual(stats["median_duration_seconds"], 0.0)
        self.assertEqual(len(stats["recent_runs"]), 3)
        self.assertEqual(stats["recent_runs"][0]["outcome"], "error")

    def test_tool_histogram_counts_names_and_unknown_tool(self):
        self.add_run(planned(events=[tool_event("get_route"), tool_event("get_route"),
                                     tool_event("check_itinerary", ok=False), tool_event("")]))
        self.add_run(planned(events=[{"kind": "tool", "result": {"ok": True}}]))
        stats = collect_stats(self.store)
        self.assertEqual(stats["tool_histogram"],
                         {"get_route": 2, "check_itinerary": 1, "未知工具": 2})
        self.assertEqual(stats["sum_tool_calls"], 2)
        self.assertEqual(stats["tool_error_count"], 1)

    def test_final_rejection_is_classified_by_via(self):
        self.add_run(planned(events=[{"kind": "final_rejected", "via": "submit_plan", "error": "预算超出"},
                                     {"kind": "final_rejected", "via": "text", "error": "格式错误"},
                                     {"kind": "final_rejected", "error": "没有 via 的老事件"}]))
        stats = collect_stats(self.store)
        self.assertEqual(stats["failure_histogram"], {
            "final_rejected:submit_plan": 1, "final_rejected:text": 1, "final_rejected:未知通道": 1})
        # 终审被拒后成功，仍然算一次成功运行，只有归因计数新增。
        self.assertEqual(stats["planned_runs"], 1)
        self.assertEqual(stats["success_rate"], 1.0)

    def test_duration_median_and_p95_skip_missing_values(self):
        for duration in (10.0, 20.0, 30.0, 40.0):
            self.add_run(planned(duration_seconds=duration))
        self.add_run(planned(duration_seconds=None))
        stats = collect_stats(self.store)
        self.assertEqual(stats["median_duration_seconds"], 25.0)
        self.assertEqual(stats["p95_duration_seconds"], 40.0)

    def test_totals_sum_tokens_and_calls_with_model_calls_fallback(self):
        self.add_run(planned(input_tokens=100, output_tokens=20, model_calls=3, provider_calls=4, tool_calls=5))
        self.add_run(planned(input_tokens=50, output_tokens=10, provider_calls=7, tool_calls=2, model_calls=None))
        stats = collect_stats(self.store)
        self.assertEqual(stats["total_input_tokens"], 150)
        self.assertEqual(stats["total_output_tokens"], 30)
        self.assertEqual(stats["sum_model_calls"], 10)  # 第二条缺 model_calls，退回 provider_calls
        self.assertEqual(stats["sum_provider_calls"], 11)
        self.assertEqual(stats["sum_tool_calls"], 7)

    def test_repair_and_text_fallback_counts(self):
        self.add_run(planned(final_checks=2))
        self.add_run(planned(final_checks=3, submitted_via="submit_plan"))
        self.add_run(planned(final_checks=1, submitted_via="text"))
        self.add_run(planned(final_checks=1))
        stats = collect_stats(self.store)
        self.assertEqual(stats["repair_runs"], 2)
        self.assertEqual(stats["text_fallback_runs"], 1)

    def test_legacy_snapshot_missing_most_fields(self):
        # 最老快照：只有 plan 和 events，其它字段全缺。
        self.add_run({"plan": {"status": "planned"}, "events": [{"kind": "tool", "name": "get_weather"}]})
        stats = collect_stats(self.store)
        self.assertEqual(stats["planned_runs"], 1)
        self.assertEqual(stats["success_rate"], 1.0)
        self.assertEqual(stats["median_duration_seconds"], 0.0)
        self.assertEqual(stats["total_input_tokens"], 0)
        self.assertEqual(stats["sum_model_calls"], 0)
        self.assertEqual(stats["repair_runs"], 0)
        self.assertEqual(stats["text_fallback_runs"], 0)
        self.assertEqual(stats["tool_histogram"], {"get_weather": 1})
        self.assertIsNone(stats["recent_runs"][0]["submitted_via"])

    def test_odd_value_types_are_treated_as_missing(self):
        self.add_run(planned(duration_seconds=True, tool_calls="3", final_checks=-1,
                             input_tokens=float("nan"), model_calls="x"))
        stats = collect_stats(self.store)
        self.assertEqual(stats["median_duration_seconds"], 0.0)
        self.assertEqual(stats["sum_tool_calls"], 0)
        self.assertEqual(stats["total_input_tokens"], 0)
        self.assertEqual(stats["sum_model_calls"], 2)  # 退回同一条的 provider_calls
        self.assertEqual(stats["repair_runs"], 0)

    def test_events_field_that_is_not_a_list_is_ignored(self):
        self.add_run(planned(events="坏数据"))
        self.add_run(planned(events=[{"kind": "tool", "name": "get_route"}, "不是对象", None]))
        stats = collect_stats(self.store)
        self.assertEqual(stats["run_count"], 2)
        self.assertEqual(stats["tool_histogram"], {"get_route": 1})
        self.assertEqual(stats["failure_histogram"], {})

    def test_limit_is_validated_and_applied(self):
        for index in range(3):
            self.add_run(planned(duration_seconds=float(index)), created_at=f"2026-01-0{index + 1} 00:00:00")
        for bad in (0, -1, 1001, True, "200", 2.0):
            with self.subTest(limit=bad), self.assertRaises(ValueError):
                collect_stats(self.store, bad)
        stats = collect_stats(self.store, 2)
        self.assertEqual(stats["run_count"], 2)
        self.assertEqual(stats["limit"], 2)
        self.assertEqual(stats["latest_run_at"], "2026-01-03 00:00:00")
        self.assertEqual([run["version"] for run in stats["recent_runs"]], [3, 2])

    def test_recent_runs_carry_metrics_and_request(self):
        run_id = self.add_run(planned(events=[tool_event("get_route", ok=False)], final_checks=2))
        recent = collect_stats(self.store)["recent_runs"][0]
        self.assertEqual(recent["run_id"], run_id)
        self.assertEqual(recent["session_id"], self.session_id)
        self.assertEqual(recent["outcome"], "planned")
        self.assertEqual(recent["plan_status"], "planned")
        self.assertEqual(recent["tool_error_count"], 1)
        self.assertEqual(recent["final_rejected_count"], 0)
        self.assertEqual(recent["event_count"], 1)
        self.assertEqual(recent["travel_date"], "2026-11-21")

    def test_classify_result_handles_raw_values(self):
        self.assertEqual(classify_result({"plan": {"status": "planned"}}), "planned")
        self.assertEqual(classify_result({"plan": {"status": "no_plan"}}), "no_plan")
        self.assertEqual(classify_result({"plan": {}}), "no_plan")
        self.assertEqual(classify_result({}), "error")
        self.assertEqual(classify_result(None), "error")
        self.assertEqual(classify_result({"plan": {"status": "planned"}, "error": "崩了"}), "error")


class CollectTraceTests(StatsTestBase):
    def test_trace_returns_events_and_metrics(self):
        events = [{"kind": "phase", "phase": "session"}, tool_event("get_weather"),
                  {"kind": "final_rejected", "via": "submit_plan", "error": "时间冲突"},
                  {"kind": "final_validation", "plan": {"status": "planned"}, "via": "submit_plan"}]
        run_id = self.add_run(planned(events=events, final_checks=2))
        trace = collect_trace(self.store, run_id)
        self.assertEqual(trace["run_id"], run_id)
        self.assertEqual(trace["session_id"], self.session_id)
        self.assertEqual(trace["version"], 1)
        self.assertEqual(trace["events"], events)
        self.assertEqual(trace["metrics"]["outcome"], "planned")
        self.assertEqual(trace["metrics"]["final_checks"], 2)
        self.assertEqual(trace["metrics"]["final_rejected_count"], 1)
        self.assertEqual(trace["request"], {"travel_date": "2026-11-21"})

    def test_trace_tolerates_legacy_and_corrupt_snapshots(self):
        legacy = self.add_run({"plan": {"status": "planned"}})
        self.assertEqual(collect_trace(self.store, legacy)["events"], [])
        self.assertEqual(collect_trace(self.store, legacy)["metrics"]["duration_seconds"], None)
        corrupt = self.add_run(None, raw="{坏")
        trace = collect_trace(self.store, corrupt)
        self.assertEqual(trace["events"], [])
        self.assertEqual(trace["metrics"]["outcome"], "error")
        self.assertEqual(trace["request"], {})

    def test_trace_rejects_missing_or_invalid_id(self):
        with self.assertRaisesRegex(ValueError, "不存在"):
            collect_trace(self.store, 999)
        for bad in (0, -3, True, "5", None):
            with self.subTest(run_id=bad), self.assertRaisesRegex(ValueError, "编号"):
                collect_trace(self.store, bad)


class StatsHttpTests(unittest.TestCase):
    """新路由的端到端检查：真实起服务，只读接口，不改动已有路由。"""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.server = create_server(0, PlanningService(Path(self.folder.name) / "http.sqlite3"))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.folder.cleanup()

    def get(self, path):
        with urlopen(self.base + path) as response:
            return response, response.read().decode("utf-8")

    def plan_once(self):
        body = json.dumps({"request": {"budget_per_person": 120}}).encode()
        request = Request(self.base + "/api/plan", data=body, headers={"Content-Type": "application/json"})
        with urlopen(request) as response:
            return json.load(response)

    def test_stats_and_trace_routes_serve_real_data(self):
        planned = self.plan_once()
        response, raw = self.get("/api/stats")
        stats = json.loads(raw)
        self.assertEqual(response.status, 200)
        self.assertEqual(stats["run_count"], 1)
        self.assertEqual(stats["sum_tool_calls"], planned["tool_calls"])
        run_id = stats["recent_runs"][0]["run_id"]
        _, trace_raw = self.get(f"/api/trace?id={run_id}")
        trace = json.loads(trace_raw)
        self.assertEqual(trace["run_id"], run_id)
        self.assertEqual(trace["events"], planned["events"])
        self.assertEqual(trace["metrics"]["event_count"], len(planned["events"]))

    def test_trace_route_rejects_bad_or_missing_id(self):
        for path in ("/api/trace", "/api/trace?id=abc", "/api/trace?id=0", "/api/trace?id=987654"):
            with self.subTest(path=path):
                try:
                    self.get(path)
                except HTTPError as error:
                    self.assertEqual(error.code, 404)
                    error.close()
                else:
                    self.fail("非法或不存在的运行编号应当返回 404")

    def test_static_trace_page_and_script_are_served(self):
        response, page = self.get("/trace")
        self.assertEqual(response.headers["Content-Type"], "text/html; charset=utf-8")
        self.assertIn("运行观测面板", page)
        response, script = self.get("/trace.js")
        self.assertEqual(response.headers["Content-Type"], "text/javascript; charset=utf-8")
        self.assertIn("/api/stats", script)
        self.assertNotIn("innerHTML", script)


if __name__ == "__main__":
    unittest.main()
