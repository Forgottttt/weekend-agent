import json
import unittest
from unittest.mock import patch

from weekend_agent.agent import TripAgent
from weekend_agent.config import ModelConfig
from weekend_agent.providers import APIProvider, DemoProvider, tool_call
from weekend_agent.tools import ToolRegistry, TripTools


class AgentTests(unittest.TestCase):
    def test_demo_has_tool_results_and_no_real_model(self):
        agent = TripAgent(DemoProvider(), ToolRegistry(TripTools()))
        run = agent.run("固定示例")
        self.assertEqual(run.tool_calls, 4)
        self.assertEqual(run.provider_calls, 5)
        self.assertTrue(run.last_check["valid"])
        self.assertEqual(run.last_check["cost_per_person"], 37)
        calls = [call for msg in agent.messages for call in msg.get("tool_calls", [])]
        results = [msg for msg in agent.messages if msg["role"] == "tool"]
        self.assertEqual([c["id"] for c in calls], [r["tool_call_id"] for r in results])

    def test_rain_changes_activity_and_recalculates_cost(self):
        agent = TripAgent(DemoProvider(rain=True), ToolRegistry(TripTools(rain=True)))
        run = agent.run("固定雨天示例")
        self.assertEqual(run.last_check["schedule"][0]["place_id"], "p09")
        self.assertTrue(run.last_check["valid"])
        self.assertEqual(run.last_check["cost_per_person"], 57)

    def test_bad_tool_json_is_returned_for_correction(self):
        class BrokenThenAnswer:
            def complete(self, messages, tools):
                if messages[-1]["role"] == "user":
                    call = tool_call("bad_1", "get_weather", {})
                    call["function"]["arguments"] = "not-json"
                    return {"role": "assistant", "content": None, "tool_calls": [call]}
                return {"role": "assistant", "content": "我收到参数错误了。"}
        run = TripAgent(BrokenThenAnswer(), ToolRegistry(TripTools())).run("测试错误")
        self.assertFalse(run.events[0]["result"]["ok"])

    def test_loop_stops_at_limit(self):
        agent = TripAgent(DemoProvider(), ToolRegistry(TripTools()), max_rounds=2)
        with self.assertRaisesRegex(RuntimeError, "轮数上限"):
            agent.run("固定示例")

    def test_tool_budget_stops_before_extra_call(self):
        agent = TripAgent(DemoProvider(), ToolRegistry(TripTools()), max_tool_calls=1)
        with self.assertRaisesRegex(RuntimeError, "工具调用上限"):
            agent.run("固定示例")
        self.assertEqual(agent.messages[-1]["role"], "tool")

    def test_api_adapter_request_shape_without_network(self):
        captured = {}
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self):
                return json.dumps({"choices": [{"message": {
                    "role": "assistant", "content": "你好",
                }}]}).encode()
        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data)
            return FakeResponse()
        config = ModelConfig("test-placeholder", "https://example.invalid/v1", "test-model")
        with patch("weekend_agent.providers.urlopen", fake_urlopen):
            answer = APIProvider(config).complete([{"role": "user", "content": "你好"}], [])
        self.assertEqual(captured["url"], "https://example.invalid/v1/chat/completions")
        self.assertEqual(captured["body"]["model"], "test-model")
        self.assertEqual(answer["content"], "你好")


if __name__ == "__main__":
    unittest.main()
