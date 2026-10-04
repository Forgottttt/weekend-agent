"""可复现的离线规划流程。它是规则基线，不是大模型，也不理解自由文本。"""

import json

from .providers import tool_call
from .request import TripRequest
from .tools import TripTools, format_time, to_minutes


def build_demo_stops(request: TripRequest, tools: TripTools, candidates: list[dict]) -> list[dict]:
    """贪心选择最多六站；不保证最优，也不证明无解。"""
    stops, used = [], set()
    now, limit, cost = to_minutes(request.start_time), to_minutes(request.end_time), 0.0
    previous = None
    has_food = False
    for _ in range(6):
        choices = []
        want_food = request.include_meal and not has_food and now >= 11 * 60
        for place in candidates:
            if place["id"] in used:
                continue
            route = tools.get_route(previous, place["id"]) if previous else {"minutes": 0, "fare_per_person": 0}
            arrival = max(now + route["minutes"], to_minutes(place["open"]))
            finish = arrival + place["visit_minutes"]
            next_cost = cost + route["fare_per_person"] + place["price_per_person"]
            if finish > min(limit, to_minutes(place["close"])) or next_cost > request.budget_per_person:
                continue
            food = place["category"] == "food"
            preference = (100 if food == want_food else 0) + 10 * len(set(request.tags) & set(place["tags"]))
            choices.append((-preference, next_cost, finish, place["id"], arrival, place))
        if not choices:
            break
        _, next_cost, finish, place_id, arrival, place = min(choices)
        stops.append({"place_id": place_id, "start": format_time(arrival)})
        used.add(place_id)
        previous, now, cost = place_id, finish, next_cost
        has_food = has_food or place["category"] == "food"
    return [] if request.include_meal and not has_food else stops


class DayDemoProvider:
    def __init__(self, request: TripRequest, tools: TripTools):
        self.request, self.tools = request, tools

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        # 找本轮的用户消息，不把前一轮的工具结果当成本轮结果。
        start = max(i for i, item in enumerate(messages)
                    if item["role"] == "user" and item["content"].startswith("STRUCTURED_REQUEST:\n"))
        results = []
        names = {call["id"]: call["function"]["name"] for item in messages[start:]
                 for call in item.get("tool_calls", [])}
        for item in messages[start:]:
            if item["role"] == "tool":
                results.append((names[item["tool_call_id"]], json.loads(item["content"])))
        r = self.request
        if not results:
            calls = [tool_call("day_weather", "get_weather", {"city": r.city, "travel_date": r.travel_date})]
        elif results[-1][0] == "get_weather":
            # 用餐是单独要求，候选搜索也纳入美食。
            tags = list(dict.fromkeys(r.tags + (["美食"] if r.include_meal else [])))
            calls = [tool_call("day_places", "search_places", {
                "city": r.city, "tags": tags, "indoor": True if r.rain else r.indoor,
                "max_price": r.budget_per_person})]
        elif results[-1][0] == "search_places":
            query = " ".join(r.tags + ["预算", "雨天室内" if r.rain else "交通衔接"])
            calls = [tool_call("day_guides", "search_guides", {"query": query, "top_k": 3})]
        else:
            candidate_result = next(value for name, value in results if name == "search_places")
            candidates = candidate_result.get("data", {}).get("places", [])
            # 规则规划直接使用本地纯函数；这些内部计算不算模型工具请求。
            stops = build_demo_stops(r, self.tools, candidates)
            if results[-1][0] == "search_guides" and len(stops) > 1:
                calls = [tool_call(f"day_route_{i}", "get_route", {
                    "from_id": left["place_id"], "to_id": right["place_id"]})
                    for i, (left, right) in enumerate(zip(stops, stops[1:]))]
            elif results[-1][0] != "check_itinerary":
                calls = [tool_call("day_check", "check_itinerary", r.check_arguments(stops))]
            else:
                checked = results[-1][1]
                guides = next(value for name, value in results if name == "search_guides")
                valid = checked.get("ok") and checked["data"]["valid"]
                final = {"status": "planned" if valid else "no_plan", "stops": stops if valid else [],
                         "guide_ids": [d["id"] for d in guides.get("data", {}).get("documents", [])]}
                return {"role": "assistant", "content": json.dumps(final, ensure_ascii=False)}
        return {"role": "assistant", "content": None, "tool_calls": calls}
