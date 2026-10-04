"""第一课：先调用普通函数，观察输入条件怎样影响返回结果。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from weekend_agent.tools import TripTools

tools = TripTools()
result = tools.search_places(city="杭州", tags=["拍照"], indoor=True, max_price=50)

print("条件：杭州、喜欢拍照、室内、每人价格不超过 50 元")
print(f"找到 {result['count']} 个教学地点：")
for place in result["places"]:
    print(f"- {place['name']}：每人 {place['price_per_person']} 元")
