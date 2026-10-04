"""第二课 C：使用项目的工具注册表，观察正确参数与错误参数。"""

import json
import sys
from pathlib import Path


project_dir = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_dir / "src"))

from weekend_agent.tools import ToolRegistry, TripTools


def run_case(registry, title, name, arguments):
    print(f"\n【{title}】")
    print("请求的工具：", name)
    print("传入的参数：", json.dumps(arguments, ensure_ascii=False))

    # registry 先检查工具名字和参数，再执行对应的业务函数。
    result = registry.execute(name, arguments)
    print("ok：", result["ok"])
    if result["ok"]:
        print("找到", result["data"]["count"], "个地点：")
        for place in result["data"]["places"]:
            print("-", place["name"])
    else:
        # 失败结果没有 data 字段，读取 error。
        print("错误：", result["error"])
    return result


def main():
    print("本课全部数据为虚构教学数据，请求由我们手写，没有调用大模型。")
    tools = TripTools()
    registry = ToolRegistry(tools)
    arguments = {
        "city": "杭州", "tags": ["拍照"], "indoor": True, "max_price": 50,
    }

    run_case(registry, "1 正确参数", "search_places", arguments)

    # copy 创建新的外层字典。本课只改外层字段，不修改里面的 tags 列表。
    missing = arguments.copy()
    del missing["indoor"]
    run_case(registry, "2 缺少必填字段 indoor", "search_places", missing)

    wrong_type = arguments.copy()
    wrong_type["max_price"] = "50"  # 带引号，变成字符串。
    run_case(registry, "3 价格类型错误", "search_places", wrong_type)

    negative = arguments.copy()
    negative["max_price"] = -1
    run_case(registry, "4 价格小于允许的最小值", "search_places", negative)

    extra = arguments.copy()
    extra["budget_total"] = 100
    run_case(registry, "5 多出未定义的字段", "search_places", extra)

    wrong_city = arguments.copy()
    wrong_city["city"] = "上海"
    run_case(registry, "6 类型正确但当前地点库不支持", "search_places", wrong_city)

    run_case(registry, "7 工具名字不存在", "search_hotels", arguments)

    print("\n原始参数仍然是：", arguments)
    print("我们观察了错误返回；本课尚未让模型自动修正请求。")


if __name__ == "__main__":
    main()
