"""第三课：改变一项约束，观察费用和时间冲突。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from weekend_agent.tools import TripTools, to_minutes

tools = TripTools()
print("10:00 →", to_minutes("10:00"), "分钟；11:30 →", to_minutes("11:30"))
print("公园到面馆：", tools.get_route("p01", "f01"))
for label, arrival, budget in [("正常", "12:00", 200), ("交通不足", "11:30", 200), ("预算不足", "12:00", 20)]:
    stops = [{"place_id": "p01", "start": "10:00"}, {"place_id": "f01", "start": arrival}]
    checked = tools.check_itinerary(stops, budget, 3, "10:00", "18:00")
    print(label, "每人", checked["cost_per_person"], "全组", checked["total_group_cost"], "问题", checked["issues"])
