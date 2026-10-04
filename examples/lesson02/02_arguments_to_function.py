"""第二课 B：将手写的 JSON 参数转换成字典，再调用 Python 函数。"""

import json
import sys
from pathlib import Path


project_dir = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_dir / "src"))

from weekend_agent.tools import TripTools


# 只模拟工具请求中的 function 部分；不是完整 API 响应，也不是模型生成的。
# arguments 的值是 JSON 字符串，注意 true 是 JSON 的写法。
tool_request = {
    "name": "search_places",
    "arguments": """{
        "city": "杭州",
        "tags": ["拍照"],
        "indoor": true,
        "max_price": 50
    }""",
}


def main():
    print("本课全部数据为虚构教学数据，请求由我们手写，没有调用大模型。")
    name = tool_request["name"]
    arguments_text = tool_request["arguments"]
    print("\n第 1 步，取出工具名字：", name)
    print("参数解析前的类型：", type(arguments_text).__name__)

    arguments = json.loads(arguments_text)
    print("\n第 2 步，JSON 文本转换成 Python 字典：", arguments)
    print("参数解析后的类型：", type(arguments).__name__)
    print("indoor 的值和类型：", arguments["indoor"], type(arguments["indoor"]).__name__)

    tools = TripTools()
    # 本文件只演示一个已知工具；通用的按名字调用在第三个文件学习。
    result = tools.search_places(**arguments)
    print("\n第 3 步，**arguments 将字典展开成函数的关键字参数。")

    # 上面那行等价于下面的写法，用两次结果对比验证。
    expanded_result = tools.search_places(
        city=arguments["city"],
        tags=arguments["tags"],
        indoor=arguments["indoor"],
        max_price=arguments["max_price"],
    )
    print("两种写法的返回值相同：", result == expanded_result)
    print("\n第 4 步，函数返回结果：找到", result["count"], "个地点。")
    for place in result["places"]:
        print(f"- {place['name']}：每人 {place['price_per_person']} 元")

    print("\n本文件已知参数正确，直接调用函数；第三个文件加入执行前检查。")


if __name__ == "__main__":
    main()
