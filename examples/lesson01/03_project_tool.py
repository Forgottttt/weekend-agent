"""第一课 C：调用真正的项目工具，并比较几组不同参数。"""

import sys
from pathlib import Path


# examples/lesson01 → 项目根目录 → src，告诉 Python 去哪里找包。
project_dir = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_dir / "src"))

from weekend_agent.tools import TripTools


def show_result(title, result):
    print(f"\n【{title}】")
    print(f"找到 {result['count']} 个地点：")
    for place in result["places"]:
        print(f"- {place['id']} {place['name']}：每人 {place['price_per_person']} 元")


def main():
    # 创建一个对象。__init__ 自动执行，读入 JSON 并保存到这个对象里。
    tools = TripTools()

    print("全部数据均为虚构教学数据；本课没有调用大模型。")
    print("tools.data 的类型：", type(tools.data).__name__)
    print("tools.data['places'] 的类型：", type(tools.data["places"]).__name__)
    print("tools.places 的类型：", type(tools.places).__name__)
    print("可以按 ID 取地点：", tools.places["p09"]["name"])

    # 第一组：和逐步演示完全相同的条件。
    result = tools.search_places(city="杭州", tags=["拍照"], indoor=True, max_price=50)
    show_result("拍照＋室内＋50 元以内", result)

    # 第二组：只改变价格。注意：没有修改 JSON 文件里的地点价格。
    result = tools.search_places(city="杭州", tags=["拍照"], indoor=True, max_price=30)
    show_result("拍照＋室内＋30 元以内", result)

    # 第三组：放宽室内外限制。None 的意思是不设置这个限制。
    result = tools.search_places(city="杭州", tags=["拍照"], indoor=None, max_price=50)
    show_result("拍照＋不限室内外＋50 元以内", result)

    # 第四组：两个标签是“任意一个匹配即可”，不是必须同时拥有。
    result = tools.search_places(city="杭州", tags=["拍照", "美食"], indoor=True, max_price=50)
    show_result("拍照或美食＋室内＋50 元以内", result)


if __name__ == "__main__":
    main()
