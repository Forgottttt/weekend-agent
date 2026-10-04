"""脚本化来源演示拒绝与修正；没有真实大模型决策。"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from weekend_agent.agent import TripAgent
from weekend_agent.providers import tool_call
from weekend_agent.request import TripRequest
from weekend_agent.tools import ToolRegistry, TripTools

class ScriptedRepair:
    def __init__(self): self.stage = 0
    def complete(self, messages, schemas):
        self.stage += 1
        print("来源第", self.stage, "次被调用；消息数", len(messages), "；最后角色", messages[-1]["role"])
        if self.stage == 1:
            return {"role": "assistant", "tool_calls": [tool_call("search", "search_places",
                    {"city": "杭州", "tags": ["美食"], "indoor": True, "max_price": 100})]}
        chosen = "f01" if self.stage == 2 else "f04"
        return {"role": "assistant", "content": json.dumps({"status": "planned",
                "stops": [{"place_id": chosen, "start": "12:00"}], "guide_ids": []})}

request = TripRequest.from_dict({"budget_per_person": 30})
for limit in (4, 2):
    print("\n允许的来源调用轮数：", limit)
    agent = TripAgent(ScriptedRepair(), ToolRegistry(TripTools()), max_rounds=limit)
    try:
        run = agent.run("按30元预算安排", request)
        for event in run.events:
            if event["kind"] == "final_rejected": print("拒绝原因：", event["error"])
        print(run.answer)
        print("来源调用/工具请求/最终校验：", run.provider_calls, run.tool_calls, run.final_checks)
    except RuntimeError as error:
        print("停止原因：", error)
print("为什么允许2轮时，虽然生成了候选，仍没有最终答案？")
