"""第七课：权威预算30元，模型不能通过修改最终答案绕过。"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from weekend_agent.finalize import render_plan, verify_final
from weekend_agent.request import TripRequest
from weekend_agent.tools import ToolRegistry, TripTools

request = TripRequest.from_dict({"budget_per_person": 30})
registry = ToolRegistry(TripTools())
searched_ids = {"f01", "f04"}
for place_id in ["f01", "f04"]:
    content = json.dumps({"status": "planned", "stops": [{"place_id": place_id, "start": "12:00"}], "guide_ids": []})
    try:
        plan = verify_final(content, request, registry, searched_ids, {})
        print(render_plan(plan))
    except ValueError as error:
        print("拒绝", place_id, "原因：", error)
