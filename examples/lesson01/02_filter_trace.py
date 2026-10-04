"""第一课 B：把真实工具的筛选逻辑展开，并打印每一步。

这是教学演示函数。真正的业务实现位于 src/weekend_agent/tools.py。
两者都使用同一份 JSON 数据，方便逐行对照。
"""

import json
from pathlib import Path


# 练习时每次只改一个条件，先预测结果再运行。
CITY = "杭州"
USER_TAGS = ["拍照"]
INDOOR = True  # True=只要室内；False=只要户外；None=不限。
MAX_PRICE = 50  # 单个地点的每人价格上限，不是整天总预算。


def search_places_with_trace(data, city, tags, indoor, max_price):
    """返回筛选结果；同时把 found 的变化打印出来。"""
    if city != data["city"]:
        raise ValueError("当前教学地点库只支持杭州")

    found = []
    print("初始 found = []，还没有地点被选中。")

    # data['places'] 是列表：每次循环取其中的一个地点字典。
    for place in data["places"]:
        print(f"\n正在检查：{place['id']} {place['name']}")

        # 第一个条件：用户未指定标签时，不按标签过滤。
        if tags:
            common_tags = set(tags).intersection(place["tags"])
            print(f"  标签交集：{sorted(common_tags)}")
            if not common_tags:
                print("  跳过：没有任何共同标签；执行 continue，开始检查下一个地点。")
                print(f"  found 数量仍为 {len(found)}。")
                continue
        else:
            print("  用户标签为空：不限制兴趣类型。")

        # 第二个条件：None 表示没有室内外限制；False 仍是有效条件。
        if indoor is not None:
            print(f"  室内外判断：地点 {place['indoor']}，用户要求 {indoor}")
            if place["indoor"] != indoor:
                print("  跳过：室内外不符合；后面的价格检查和 append 本轮不执行。")
                print(f"  found 数量仍为 {len(found)}。")
                continue
        else:
            print("  indoor=None：不限制室内外。")

        # 第三个条件：等于价格上限的地点也可以保留。
        print(f"  价格判断：{place['price_per_person']} > {max_price} 吗？")
        if place["price_per_person"] > max_price:
            print("  跳过：价格超出上限。")
            print(f"  found 数量仍为 {len(found)}。")
            continue

        # 只有通过前面所有条件的地点，才会执行这一行。
        found.append(place)
        print(f"  保留：执行 found.append(place)，现在数量为 {len(found)}。")

    # for 完成以后再 return：返回的是全部匹配地点。
    return {
        "data_mode": "fictional_demo",
        "places": found,
        "count": len(found),
    }


def main():
    project_dir = Path(__file__).resolve().parents[2]
    data_file = project_dir / "src" / "weekend_agent" / "data" / "hangzhou_demo.json"
    data = json.loads(data_file.read_text(encoding="utf-8"))

    print("全部数据均为虚构教学数据。")
    print(f"筛选条件：city={CITY}，tags={USER_TAGS}，indoor={INDOOR}，max_price={MAX_PRICE}")

    result = search_places_with_trace(
        data=data,
        city=CITY,
        tags=USER_TAGS,
        indoor=INDOOR,
        max_price=MAX_PRICE,
    )

    print("\n【最终结果】")
    print(f"result['count'] = {result['count']}")
    for place in result["places"]:
        print(f"- {place['id']} {place['name']}：每人 {place['price_per_person']} 元")


if __name__ == "__main__":
    main()
