"""第二课 A：查看 search_places 的工具说明，不执行地点搜索。"""

import json
import sys
from pathlib import Path


# 与第一课一样：把项目的 src 目录加入 Python 的查找路径。
project_dir = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_dir / "src"))

from weekend_agent.tools import TOOL_SCHEMAS


def main():
    # 下标从 0 开始：第 0 个是天气工具，第 1 个是地点搜索工具。
    schema = TOOL_SCHEMAS[1]
    function_info = schema["function"]
    parameters = function_info["parameters"]

    print("本课全部数据为虚构教学数据，没有调用大模型。")
    print("工具名字：", function_info["name"])
    print("工具用途：", function_info["description"])
    print("必须提供的参数：", parameters["required"])

    print("\n每个参数允许的类型：")
    for name, rule in parameters["properties"].items():
        print(f"- {name}: {rule['type']}")

    print("\n工具说明转换成 JSON 文本后：")
    # dumps：Python 数据 → JSON 字符串。第一课的 loads 是反方向。
    print(json.dumps(schema, ensure_ascii=False, indent=2))

    # 名字叫 required 不代表值不能为 null，要结合 type 一起看。
    print("\nindoor 的允许类型：", parameters["properties"]["indoor"]["type"])
    print("Python 的 None 转成 JSON：", json.dumps({"indoor": None}))
    print("注意：工具说明描述怎样调用函数，本身不会执行函数。")


if __name__ == "__main__":
    main()
