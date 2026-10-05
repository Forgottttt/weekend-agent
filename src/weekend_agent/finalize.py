"""最终展示由应用重算。模型不能自行填写费用、营业时间或地点名称。"""

from .jsonio import parse_json_object
from .request import TripRequest
from .tools import SUBMIT_PLAN_PARAMETERS, ToolRegistry, validate_arguments


def verify_plan(candidate: dict, request: TripRequest, registry: ToolRegistry,
                place_ids: set[str], guides: dict[str, dict]) -> dict:
    """校验一份**已经解析成字典**的最终方案。

    `submit_plan` 工具调用的参数本身就是字典，因此这是主通道；
    文本兜底路径会先用 jsonio.parse_json_object 解析再调用这里，
    两条通道共用同一套判定，不存在第二份规则。
    """
    validate_arguments(candidate, SUBMIT_PLAN_PARAMETERS, "final")
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


def verify_final(content: str, request: TripRequest, registry: ToolRegistry,
                 place_ids: set[str], guides: dict[str, dict]) -> dict:
    """文本兜底通道：模型没有调用 submit_plan 时，从回复文本里解析出方案再校验。

    保留这条通道是因为删掉它只会让偶发的格式问题变成硬失败；
    是否被使用由 RunResult.submitted_via 记录，可以直接度量。
    """
    return verify_plan(parse_json_object(content, "最终方案"),
                       request, registry, place_ids, guides)


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
