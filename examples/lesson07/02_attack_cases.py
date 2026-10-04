"""实际搜索后，逐项尝试绕过最终结果校验。"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from weekend_agent.finalize import verify_final
from weekend_agent.request import TripRequest
from weekend_agent.tools import ToolRegistry, TripTools

registry = ToolRegistry(TripTools())
searched = registry.execute("search_places", {"city": "杭州", "tags": ["美食"], "indoor": True, "max_price": 100})
ids = {place["id"] for place in searched["data"]["places"]}
request = TripRequest.from_dict({"budget_per_person": 30})
base = {"status": "planned", "stops": [{"place_id": "f04", "start": "12:00"}], "guide_ids": []}
cases = [("合法候选", base), ("伪造价格字段", {**base, "cost_per_person": 0}),
         ("未经检索的引用", {**base, "guide_ids": ["g_rain"]}),
         ("搜索过但超预算", {**base, "stops": [{"place_id": "f01", "start": "12:00"}]}),
         ("库中存在但本轮未搜索", {**base, "stops": [{"place_id": "p01", "start": "10:00"}]})]
for label, candidate in cases:
    try:
        plan = verify_final(json.dumps(candidate), request, registry, ids, {})
        print(label, "通过，每人", plan["checked"]["cost_per_person"])
    except ValueError as error:
        print(label, "被拒绝：", error)
print("set中的地点仅证明搜索见过；不证明最终组合符合预算。")
