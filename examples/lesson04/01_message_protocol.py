"""第四课：只做一次请求和一次结果回传，观察 ID 配对。"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from weekend_agent.providers import tool_call
from weekend_agent.tools import ToolRegistry, TripTools

messages = [{"role": "user", "content": "查教学天气。"}]
call = tool_call("weather_001", "get_weather", {"city": "杭州", "travel_date": "2026-11-21"})
messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
arguments = json.loads(call["function"]["arguments"])
result = ToolRegistry(TripTools()).execute(call["function"]["name"], arguments)
messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, ensure_ascii=False)})
print(json.dumps(messages, ensure_ascii=False, indent=2))
print("请求 ID 和结果 ID 相同：", call["id"] == messages[-1]["tool_call_id"])
