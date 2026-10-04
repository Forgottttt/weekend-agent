"""把 JSON 格式错误、参数错误和消息协议错误分开观察。"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from weekend_agent.agent import TripAgent
from weekend_agent.providers import tool_call
from weekend_agent.tools import ToolRegistry, TripTools

registry = ToolRegistry(TripTools())
raw = '{"city":"杭州","travel_date":"2026-11-21"}'
print("loads之前：", type(raw).__name__, "；之后：", type(json.loads(raw)).__name__)
for name, arguments in [("get_weather", raw), ("get_weather", '{"city":'),
                         ("get_weather", '{"city":"杭州"}'), ("unknown", '{}')]:
    try:
        decoded = json.loads(arguments)
        result = registry.execute(name, decoded)
    except json.JSONDecodeError:
        result = {"ok": False, "error": "JSON 还没有解析成功，尚未进入注册表"}
    print(name, "→", result)

class DuplicateIDProvider:
    def complete(self, messages, schemas):
        args = {"city": "杭州", "travel_date": "2026-11-21"}
        return {"role": "assistant", "tool_calls": [tool_call("same", "get_weather", args),
                                                        tool_call("same", "get_weather", args)]}

try:
    TripAgent(DuplicateIDProvider(), registry).run("观察重复ID")
except RuntimeError as error:
    print("两次调用共用ID：", error)
print("注意：工具运行失败可作为 tool 消息回传；ID配对损坏则停止本轮。")
