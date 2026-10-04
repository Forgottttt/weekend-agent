"""第一课 A：先认识数据，再读取项目中的 JSON 文件。"""

import json
from pathlib import Path


def main():
    # 1. 字典 dict：用字段名（键）找到对应的值。
    place = {
        "id": "p09",
        "name": "示例城市展览馆",
        "tags": ["拍照", "文化"],
        "indoor": True,
        "price_per_person": 20,
    }

    print("【1】一个地点是一个字典")
    print("地点名称：", place["name"])
    print("地点标签：", place["tags"])
    print("是否室内：", place["indoor"])
    print("每人价格：", place["price_per_person"])

    # 2. 列表 list：按顺序保存多条数据。这里先用两个很小的字典。
    places = [
        place,
        {"id": "p10", "name": "示例摄影展", "price_per_person": 40},
    ]

    print("\n【2】多个地点放进一个列表")
    print("地点数量：", len(places))
    print("第一个地点：", places[0]["name"])
    print("第二个地点：", places[1]["name"])

    # 3. 数据文件路径相对于本脚本计算，所以换一个终端目录也能运行。
    project_dir = Path(__file__).resolve().parents[2]
    data_file = project_dir / "src" / "weekend_agent" / "data" / "hangzhou_demo.json"

    # read_text 得到文本 str；json.loads 将 JSON 文本转换为 Python 数据。
    text = data_file.read_text(encoding="utf-8")
    data = json.loads(text)

    print("\n【3】读取真正的教学地点库")
    print("读取文件：", data_file)
    print("读取后文本的类型：", type(text).__name__)
    print("解析后数据的类型：", type(data).__name__)
    print("城市：", data["city"])
    print("地点数量：", len(data["places"]))
    print("文件中的第一个地点：", data["places"][0]["name"])
    print("说明：", data["description"])


# 直接运行此文件时才调用 main；仅导入此文件时不会自动打印。
if __name__ == "__main__":
    main()
