import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from weekend_agent.agent import TripAgent
from weekend_agent.config import ModelConfig
from weekend_agent.evaluation import evaluate
from weekend_agent.finalize import verify_final
from weekend_agent.jsonio import parse_json_object
from weekend_agent.memory import SessionStore, select_context
from weekend_agent.providers import APIProvider, tool_call
from weekend_agent.request import TripRequest
from weekend_agent.retrieval import GuideIndex
from weekend_agent.server import create_server
from weekend_agent.service import BusyError, PlanningService
from weekend_agent.tools import ToolRegistry, TripTools


class RequestTests(unittest.TestCase):
    def test_time_format_rejects_signed_hour(self):
        with self.assertRaisesRegex(ValueError, "HH:MM"):
            TripRequest.from_dict({"start_time": "+1:30"})

    def test_request_rejects_invalid_constraints(self):
        for values in ({"budget_per_person": float("nan")}, {"group_size": True},
                       {"start_time": "18:00", "end_time": "10:00"}, {"unknown": 1},
                       {"travel_date": "not-a-date"}, {"city": "上海"}, {"rain": True, "indoor": False}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                TripRequest.from_dict(values)


class RetrievalTests(unittest.TestCase):
    def test_rain_document_is_retrieved_first(self):
        self.assertEqual(GuideIndex().search("雨天室内", 1)[0]["id"], "g_rain")

    def test_no_overlap_does_not_invent_context(self):
        self.assertEqual(GuideIndex().search("unmatchedxyz", 3), [])

    def test_top_k_and_query_limits(self):
        for query, top_k in (("", 2), ("雨天", 0), ("雨天", True)):
            with self.assertRaises(ValueError):
                GuideIndex().search(query, top_k)


class FinalTests(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry(TripTools())

    def candidate(self, place_id="f04", start="12:00", **extra):
        return json.dumps({"status": "planned", "stops": [{"place_id": place_id, "start": start}],
                           "guide_ids": [], **extra})

    def test_actual_user_budget_is_authoritative(self):
        with self.assertRaisesRegex(ValueError, "预算超出"):
            verify_final(self.candidate("f01"), TripRequest.from_dict({"budget_per_person": 30}),
                         self.registry, {"f01"}, {})

    def test_final_price_field_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "未知字段"):
            verify_final(self.candidate(cost_per_person=0), TripRequest(), self.registry, {"f04"}, {})

    def test_final_place_must_have_been_searched(self):
        with self.assertRaisesRegex(ValueError, "本轮搜索"):
            verify_final(self.candidate(), TripRequest(), self.registry, set(), {})

    def test_final_source_must_have_been_retrieved(self):
        with self.assertRaisesRegex(ValueError, "本轮实际检索"):
            verify_final(self.candidate(guide_ids=["g_rain"]), TripRequest(), self.registry, {"f04"}, {})

    def test_meal_and_interest_are_checked(self):
        with self.assertRaisesRegex(ValueError, "用餐"):
            verify_final(self.candidate("p01", "10:00"), TripRequest(), self.registry, {"p01"}, {})
        with self.assertRaisesRegex(ValueError, "兴趣"):
            verify_final(self.candidate("p01", "10:00"), TripRequest.from_dict({"tags": ["艺术"], "include_meal": False}),
                         self.registry, {"p01"}, {})

    def test_indoor_constraint_is_checked_even_if_tool_search_was_loose(self):
        request = TripRequest.from_dict({"indoor": True, "include_meal": False})
        with self.assertRaisesRegex(ValueError, "室内"):
            verify_final(self.candidate("p01", "10:00"), request, self.registry, {"p01"}, {})

    def test_fenced_json_is_accepted(self):
        # 真实模型常把最终 JSON 包在 Markdown 代码围栏里。
        # 解析层剥离围栏，就不必再浪费一轮完整上下文去纠正格式。
        fenced = "```json\n" + self.candidate() + "\n```"
        plan = verify_final(fenced, TripRequest(), self.registry, {"f04"}, {})
        self.assertEqual(plan["status"], "planned")

    def test_plain_fence_and_surrounding_text_are_accepted(self):
        wrapped = "好的，这是最终方案：\n```\n" + self.candidate() + "\n```\n请查收。"
        self.assertEqual(verify_final(wrapped, TripRequest(), self.registry, {"f04"}, {})["status"], "planned")

    def test_unparsable_answer_gets_readable_error(self):
        with self.assertRaisesRegex(ValueError, "不是合法 JSON"):
            verify_final("我建议去示例面馆。", TripRequest(), self.registry, {"f04"}, {})

    def test_json_after_leading_explanation_is_accepted(self):
        # 真实模型实测输出：先一段英文确认文字，再给裸 JSON，且没有 Markdown 围栏。
        content = ("Confirmed: even the minimum costs 27/person > 20 budget. "
                   "No valid itinerary exists under the form's constraints.\n\n"
                   '{"status": "no_plan", "stops": [], "guide_ids": []}')
        plan = verify_final(content, TripRequest(), self.registry, set(), {})
        self.assertEqual(plan["status"], "no_plan")

    def test_braces_inside_strings_do_not_truncate_the_object(self):
        # 扫描配平花括号时必须跳过字符串字面量，否则会在 "预算{100}" 处提前截断，
        # 表现为 JSON 解析失败。
        content = '说明：{"note": "预算{100}以内"}'
        self.assertEqual(parse_json_object(content)["note"], "预算{100}以内")

    def test_parse_error_tells_the_model_not_to_use_fences(self):
        try:
            verify_final("抱歉，我无法给出 JSON。", TripRequest(), self.registry, {"f04"}, {})
        except ValueError as error:
            self.assertIn("Markdown 代码围栏", str(error))
        else:
            self.fail("应当抛出 ValueError")


class ProtocolTests(unittest.TestCase):
    def test_nonfinite_tool_json_is_error_data_and_trace_can_be_serialized(self):
        class BrokenThenAnswer:
            def complete(self, messages, schemas):
                if messages[-1]["role"] == "user":
                    call = tool_call("nan", "search_places", {})
                    call["function"]["arguments"] = '{"city":"杭州","tags":[],"indoor":null,"max_price":NaN}'
                    return {"role": "assistant", "content": None, "tool_calls": [call]}
                return {"role": "assistant", "content": "收到错误"}
        run = TripAgent(BrokenThenAnswer(), ToolRegistry(TripTools())).run("测试")
        self.assertFalse(run.events[0]["result"]["ok"])
        json.dumps(run.events, allow_nan=False)

    def test_final_rejection_can_be_repaired_and_display_is_recomputed(self):
        class Scripted:
            def __init__(self): self.stage = 0
            def complete(self, messages, schemas):
                self.stage += 1
                if self.stage == 1:
                    return {"role": "assistant", "content": None, "tool_calls": [
                        tool_call("search", "search_places", {"city": "杭州", "tags": [], "indoor": None, "max_price": 100}),
                        tool_call("loose-check", "check_itinerary", {"stops": [{"place_id": "f01", "start": "12:00"}],
                                  "budget_per_person": 999, "group_size": 2, "start_time": "10:00", "end_time": "18:00"})]}
                place = "f01" if self.stage == 2 else "f04"
                return {"role": "assistant", "content": json.dumps({"status": "planned", "stops": [
                    {"place_id": place, "start": "12:00"}], "guide_ids": []})}
        run = TripAgent(Scripted(), ToolRegistry(TripTools())).run("测试", TripRequest.from_dict({"budget_per_person": 30}))
        self.assertEqual(run.final_checks, 2)
        self.assertEqual(run.last_check["cost_per_person"], 25)
        self.assertTrue(any(e["kind"] == "final_rejected" for e in run.events))
        self.assertIn("每人 25 元", run.answer)

    def test_submit_plan_is_the_primary_channel(self):
        class Scripted:
            def complete(self, messages, schemas):
                if any(m["role"] == "tool" for m in messages):
                    return {"role": "assistant", "content": None, "tool_calls": [
                        tool_call("submit", "submit_plan", {"status": "planned", "stops": [
                            {"place_id": "f04", "start": "12:00"}], "guide_ids": []})]}
                return {"role": "assistant", "content": None, "tool_calls": [
                    tool_call("search", "search_places", {"city": "杭州", "tags": [],
                                                          "indoor": None, "max_price": 100})]}
        run = TripAgent(Scripted(), ToolRegistry(TripTools())).run("测试", TripRequest())
        self.assertEqual(run.submitted_via, "submit_plan")
        self.assertNotIn("final_via_text_fallback", [e["kind"] for e in run.events])
        self.assertIn("每人 25 元", run.answer)

    def test_text_answer_is_recorded_as_fallback(self):
        class Scripted:
            def complete(self, messages, schemas):
                if any(m["role"] == "tool" for m in messages):
                    return {"role": "assistant", "content": json.dumps(
                        {"status": "planned", "stops": [{"place_id": "f04", "start": "12:00"}],
                         "guide_ids": []})}
                return {"role": "assistant", "content": None, "tool_calls": [
                    tool_call("search", "search_places", {"city": "杭州", "tags": [],
                                                          "indoor": None, "max_price": 100})]}
        run = TripAgent(Scripted(), ToolRegistry(TripTools())).run("测试", TripRequest())
        self.assertEqual(run.submitted_via, "text")
        self.assertIn("final_via_text_fallback", [e["kind"] for e in run.events])

    def test_rejected_submit_plan_returns_error_as_tool_result(self):
        class Scripted:
            def __init__(self): self.stage = 0
            def complete(self, messages, schemas):
                self.stage += 1
                if self.stage == 1:
                    return {"role": "assistant", "content": None, "tool_calls": [
                        tool_call("search", "search_places", {"city": "杭州", "tags": [],
                                                              "indoor": None, "max_price": 100})]}
                place = "f01" if self.stage == 2 else "f04"
                return {"role": "assistant", "content": None, "tool_calls": [
                    tool_call("submit", "submit_plan", {"status": "planned", "stops": [
                        {"place_id": place, "start": "12:00"}], "guide_ids": []})]}
        run = TripAgent(Scripted(), ToolRegistry(TripTools())).run(
            "测试", TripRequest.from_dict({"budget_per_person": 30}))
        self.assertEqual(run.submitted_via, "submit_plan")
        self.assertEqual(run.final_checks, 2)
        rejected = [e for e in run.events if e["kind"] == "final_rejected"]
        self.assertEqual(rejected[0]["via"], "submit_plan")
        self.assertIn("预算超出", rejected[0]["error"])
        self.assertIn("每人 25 元", run.answer)

    def test_successful_submit_answers_every_pending_tool_call(self):
        # 回归：提交成功时若同批次还有别的调用，必须逐个补上配对结果。
        # 漏掉任何一个，下一轮都会带着未配对的 tool_calls，接口会直接拒绝。
        class Scripted:
            def complete(self, messages, schemas):
                return {"role": "assistant", "content": None, "tool_calls": [
                    tool_call("search", "search_places", {"city": "杭州", "tags": [],
                                                          "indoor": None, "max_price": 100}),
                    tool_call("submit", "submit_plan", {"status": "planned", "stops": [
                        {"place_id": "f04", "start": "12:00"}], "guide_ids": []}),
                    tool_call("weather", "get_weather", {"city": "杭州", "travel_date": "2026-11-21"})]}
        agent = TripAgent(Scripted(), ToolRegistry(TripTools()))
        run = agent.run("测试", TripRequest())
        calls = [c["id"] for m in agent.messages for c in m.get("tool_calls", [])]
        results = [m["tool_call_id"] for m in agent.messages if m["role"] == "tool"]
        self.assertEqual(calls, results)
        self.assertEqual(run.submitted_via, "submit_plan")
        self.assertIn("weather", calls)

    def test_malformed_call_id_is_controlled_error(self):
        class Broken:
            def complete(self, messages, schemas):
                call = tool_call("bad", "get_weather", {})
                del call["id"]
                return {"role": "assistant", "tool_calls": [call]}
        with self.assertRaisesRegex(RuntimeError, "协议异常"):
            TripAgent(Broken(), ToolRegistry(TripTools())).run("测试")

    def test_transient_api_error_retries_once_and_records_usage(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return json.dumps({"choices": [{"message": {"content": "ok"}}],
                                               "usage": {"prompt_tokens": 10, "completion_tokens": 5}}).encode()
        provider = APIProvider(ModelConfig("placeholder", "https://example.invalid", "test"))
        failure = HTTPError("https://example.invalid", 429, "rate limit", None, None)
        with patch("weekend_agent.providers.urlopen", side_effect=[failure, Response()]) as mocked, patch("weekend_agent.providers.sleep"):
            self.assertEqual(provider.complete([], [])["content"], "ok")
            self.assertEqual(mocked.call_count, 2)
        self.assertEqual(provider.last_usage["prompt_tokens"], 10)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "state.sqlite3"
        self.service = PlanningService(self.path)

    def tearDown(self): self.folder.cleanup()

    def test_multiturn_restores_constraints_after_restart(self):
        first = self.service.plan({"group_size": 3})
        second = PlanningService(self.path).plan({"rain": True, "budget_per_person": 80}, session_id=first["session_id"])
        self.assertEqual(second["request"]["group_size"], 3)
        self.assertEqual(second["plan"]["status"], "planned")
        self.assertTrue(all(self.service.store.load(first["session_id"])["request"][key] == second["request"][key]
                            for key in ("group_size", "rain", "budget_per_person")))

    def test_partial_time_update_uses_saved_end_time(self):
        first = self.service.plan({"end_time": "22:00", "include_meal": False})
        second = self.service.plan({"start_time": "19:00"}, session_id=first["session_id"])
        self.assertEqual(second["request"]["end_time"], "22:00")

    def test_sessions_do_not_share_constraints(self):
        first, second = self.service.plan({"group_size": 3}), self.service.plan({"group_size": 5})
        self.assertNotEqual(first["session_id"], second["session_id"])
        self.assertEqual(self.service.store.load(first["session_id"])["request"]["group_size"], 3)

    def test_context_keeps_complete_tool_pairs_and_full_history(self):
        session_id = None
        for _ in range(5):
            result = self.service.plan({}, session_id=session_id)
            session_id = result["session_id"]
        history = self.service.store.load(session_id)["messages"]
        context = select_context(history, max_turns=2)
        self.assertLess(len(context), len(history))
        calls = [call["id"] for m in context for call in m.get("tool_calls", [])]
        results = [m["tool_call_id"] for m in context if m["role"] == "tool"]
        self.assertEqual(calls, results)

    def test_plan_result_keeps_events_and_event_log_survives_asdict(self):
        # 回归：事件日志是 list 子类，asdict 会用 type(obj)(生成器) 重建它。
        # 早期版本因此把 events 变成空列表，静默丢掉全部调用记录。
        from dataclasses import asdict, dataclass
        from weekend_agent.agent import _EventLog

        @dataclass
        class Holder:
            events: list

        log = _EventLog()
        log.append({"kind": "tool", "name": "get_weather"})
        self.assertEqual(list(asdict(Holder(log))["events"]),
                         [{"kind": "tool", "name": "get_weather"}])
        result = self.service.plan({})
        self.assertTrue(result["events"], "结果里的事件不应为空")
        self.assertTrue(any(event["kind"] == "tool" for event in result["events"]))

    def test_optimistic_write_prevents_overwrite(self):
        store = SessionStore(self.path)
        session_id = store.create("demo")
        store.save(session_id, [], {}, {}, 0)
        with self.assertRaisesRegex(RuntimeError, "其他请求"):
            store.save(session_id, [], {}, {}, 0)

    def test_same_session_concurrent_run_is_rejected(self):
        first = self.service.plan({})
        lock = self.service.session_locks[first["session_id"]]
        lock.acquire()
        try:
            with self.assertRaises(BusyError):
                self.service.plan({}, session_id=first["session_id"])
        finally: lock.release()

    def test_offline_evaluation_has_no_model_calls(self):
        report = evaluate(output_dir=Path(self.folder.name))
        self.assertEqual(report["case_count"], 12)
        self.assertEqual(report["passed"], 12)
        self.assertEqual(report["model_calls"], 0)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.server = create_server(0, PlanningService(Path(self.folder.name) / "state.sqlite3"))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.folder.cleanup()

    def post(self, body, origin=None, path="/api/plan"):
        headers = {"Content-Type": "application/json"}
        if origin: headers["Origin"] = origin
        return urlopen(Request(self.base + path, data=json.dumps(body).encode(), headers=headers))

    def test_plan_and_restore_over_http(self):
        with self.post({"request": {"rain": True}}) as response:
            result = json.load(response)
        with urlopen(self.base + "/api/session?id=" + result["session_id"]) as response:
            saved = json.load(response)
        self.assertEqual(saved["result"]["plan"]["status"], "planned")
        self.assertTrue(saved["request"]["rain"])

    def test_health_reports_readiness_without_exposing_key(self):
        config = ModelConfig("fake-secret-for-test", "https://api.deepseek.com", "deepseek-flash")
        with patch("weekend_agent.diagnostics.ModelConfig.from_env", return_value=config):
            with urlopen(self.base + "/api/health") as response:
                raw = response.read().decode()
        self.assertNotIn("fake-secret-for-test", raw)
        health = json.loads(raw)
        self.assertTrue(health["model"]["ready"])
        self.assertFalse(health["model"]["network_used"])

    def test_invalid_request_and_cross_origin_are_rejected(self):
        with self.assertRaises(HTTPError) as error:
            self.post({"request": {"group_size": True}})
        self.assertEqual(error.exception.code, 400)
        error.exception.close()
        with self.assertRaises(HTTPError) as error:
            self.post({"request": {}}, origin="https://example.invalid")
        self.assertEqual(error.exception.code, 403)
        error.exception.close()

    def test_stream_endpoint_emits_progress_then_result(self):
        with self.post({"request": {"rain": True}}, path="/api/plan/stream") as response:
            self.assertEqual(response.headers["Content-Type"], "text/event-stream; charset=utf-8")
            raw = response.read().decode("utf-8")
        payloads = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: ")]
        kinds = [payload["kind"] for payload in payloads]
        self.assertEqual(kinds[-1], "done")
        self.assertIn("result", kinds)
        # 进度必须先于结果推送，否则流式就没有意义。
        self.assertLess(kinds.index("phase"), kinds.index("result"))
        self.assertTrue(any(kind == "tool" for kind in kinds))
        result = payloads[kinds.index("result")]["result"]
        self.assertEqual(result["plan"]["status"], "planned")
        self.assertTrue(result["request"]["rain"])

    def test_stream_endpoint_rejects_bad_field_before_streaming(self):
        with self.assertRaises(HTTPError) as error:
            self.post({"request": {}, "boss": True}, path="/api/plan/stream")
        self.assertEqual(error.exception.code, 400)
        error.exception.close()

    def test_extract_rejects_demo_mode_and_unknown_fields(self):
        # 抽取必须有真实模型；离线模式只能按表单运行。
        with self.assertRaises(HTTPError) as error:
            self.post({"text": "两个人去玩", "mode": "demo"}, path="/api/extract")
        self.assertEqual(error.exception.code, 400)
        error.exception.close()
        with self.assertRaises(HTTPError) as error:
            self.post({"text": "两个人去玩", "mode": "live", "budget": 100}, path="/api/extract")
        self.assertEqual(error.exception.code, 400)
        error.exception.close()

    def test_extract_reports_missing_key_as_client_error(self):
        with patch("weekend_agent.config.ModelConfig.from_env",
                   side_effect=ValueError("尚未设置 LLM_API_KEY")):
            with self.assertRaises(HTTPError) as error:
                self.post({"text": "两个人去玩", "mode": "live"}, path="/api/extract")
            self.assertEqual(error.exception.code, 400)
            self.assertIn("LLM_API_KEY", error.exception.read().decode())
            error.exception.close()

    def test_extract_returns_slots_and_clarification(self):
        content = json.dumps({"city": None, "travel_date": None, "budget_per_person": 150,
                              "group_size": None, "tags": None, "indoor": None, "rain": None,
                              "start_time": None, "end_time": None, "include_meal": None})

        class FakeProvider:
            def __init__(self, config): pass

            def complete(self, messages, tools):
                return {"role": "assistant", "content": content}

        config = ModelConfig("fake-key", "https://api.deepseek.com", "deepseek-flash")
        with patch("weekend_agent.providers.APIProvider", FakeProvider), \
                patch("weekend_agent.config.ModelConfig.from_env", return_value=config):
            with self.post({"text": "人均一百五", "mode": "live"}, path="/api/extract") as response:
                result = json.load(response)
        self.assertEqual(result["provided"], {"budget_per_person": 150})
        self.assertEqual(sorted(result["missing"]), ["group_size", "travel_date"])
        self.assertIn("出行日期", result["question"])


if __name__ == "__main__":
    unittest.main()
