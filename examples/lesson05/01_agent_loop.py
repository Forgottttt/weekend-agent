"""第五课：观察完整离线循环；它是规则流程，不是模型能力证明。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from weekend_agent.agent import TripAgent
from weekend_agent.planning import DayDemoProvider
from weekend_agent.request import TripRequest
from weekend_agent.tools import ToolRegistry, TripTools

request = TripRequest.from_dict({})
tools = TripTools()
agent = TripAgent(DayDemoProvider(request, tools), ToolRegistry(tools), max_rounds=12, max_tool_calls=20)
run = agent.run("请按表单规划。", request)
for event in run.events:
    if event["kind"] == "tool":
        print("轮数", event["round"], "工具", event["name"], "成功", event["result"]["ok"])
print(run.answer)
print("来源调用", run.provider_calls, "工具请求", run.tool_calls, "真实模型请求 0")
