"""从真实工具输出逐站观察费用、时间与边界。全程离线。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from weekend_agent.tools import TripTools, to_minutes

tools = TripTools()
stops = [{"place_id": "p01", "start": "10:00"}, {"place_id": "f01", "start": "12:00"}]
checked = tools.check_itinerary(stops, 37, 3, "10:00", "18:00")
running_cost = 0
previous_end = None
for index, stop in enumerate(checked["schedule"], 1):
    route = stop["route_from_previous"]
    fare = route["fare_per_person"] if route else 0
    print(f"第{index}站 {stop['name']}")
    print("累计费用：", running_cost, "+ 交通", fare, "+ 地点", stop["price_per_person"])
    running_cost += fare + stop["price_per_person"]
    if route:
        print("最早可到达分钟：", previous_end, "+", route["minutes"], "=", previous_end + route["minutes"])
    print("实际到达/结束分钟：", to_minutes(stop["start"]), to_minutes(stop["end"]))
    previous_end = to_minutes(stop["end"])
    print("当前累计每人费用：", running_cost)
assert running_cost == checked["cost_per_person"] == 37
print("全组三人：", checked["total_group_cost"], "；预算恰好37是否通过：", checked["valid"])

for arrival in ("11:44", "11:45", "12:00"):
    changed = [stops[0], {"place_id": "f01", "start": arrival}]
    result = tools.check_itinerary(changed, 37, 3, "10:00", "18:00")
    print("只改第二站到达时间", arrival, "→", result["valid"], result["issues"])
print("先预测：只把预算改36，会出现什么错误？")
print(tools.check_itinerary(stops, 36, 3, "10:00", "18:00")["issues"])
