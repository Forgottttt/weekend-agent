"""最终展示由应用重算。模型不能自行填写费用、营业时间或地点名称。"""

from .jsonio import parse_json_object
from .request import TripRequest
from .tools import ToolRegistry, validate_arguments


def verify_final(content: str, request: TripRequest, registry: ToolRegistry,
                 place_ids: set[str], guides: dict[str, dict]) -> dict:
    candidate = parse_json_object(content, "最终方案")
    schema = {"type": "object", "properties": {
        "status": {"type": "string"},
        "stops": {"type": "array", "maxItems": 8, "items": {"type": "object", "properties": {
            "place_id": {"type": "string"}, "start": {"type": "string"}},
            "required": ["place_id", "start"], "additionalProperties": False}},
        "guide_ids": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
    }, "required": ["status", "stops", "guide_ids"], "additionalProperties": False}
    validate_arguments(candidate, schema, "final")
    if candidate["status"] not in ("planned", "no_plan"):
        raise ValueError("final.status 必须是 planned 或 no_plan")
    if any(guide_id not in guides for guide_id in candidate["guide_ids"]):
        raise ValueError("最终引用必须来自本轮实际检索结果")
    citations = [guides[guide_id] for guide_id in dict.fromkeys(candidate["guide_ids"])]
    if candidate["status"] == "no_plan":
        if candidate["stops"]:
            raise ValueError("no_plan 不能同时返回行程")
        return {"status": "no_plan", "checked": None, "citations": citations}
    has_food = False
    for stop in candidate["stops"]:
        place_id = stop["place_id"]
        if place_id not in place_ids:
            raise ValueError("最终地点必须来自本轮搜索结果")
        place = registry.tools.places[place_id]
        if (request.rain or request.indoor is True) and not place["indoor"]:
            raise ValueError("最终地点违反室内要求")
        if request.indoor is False and place["indoor"]:
            raise ValueError("最终地点违反户外要求")
        food = place["category"] == "food"
        has_food = has_food or food
        if not food and request.tags and not set(request.tags).intersection(place["tags"]):
            raise ValueError("最终活动不符合用户兴趣")
    if request.include_meal and not has_food:
        raise ValueError("用户要求用餐，但最终行程没有用餐地点")
    checked = registry.execute("check_itinerary", request.check_arguments(candidate["stops"]))
    if not checked["ok"]:
        raise ValueError(checked["error"])
    if not checked["data"]["valid"]:
        raise ValueError("；".join(checked["data"]["issues"]))
    return {"status": "planned", "checked": checked["data"], "citations": citations}


def render_plan(plan: dict) -> str:
    rows = ["周末去哪玩 · 全部为虚构教学数据"]
    if plan["status"] == "no_plan":
        rows.append("本轮未找到通过校验的候选方案；这不证明不存在可行方案。可以放宽预算、时间或用餐要求后再试。")
    else:
        checked = plan["checked"]
        rows.extend(f"{stop['start']}–{stop['end']} {stop['name']}" for stop in checked["schedule"])
        rows.append(f"每人 {checked['cost_per_person']:g} 元，全组 {checked['total_group_cost']:g} 元。")
        rows.append(checked["cost_scope"])
    if plan["citations"]:
        rows.append("检索参考：" + "、".join(f"[{d['id']}] {d['title']}" for d in plan["citations"]))
    return "\n".join(rows)
