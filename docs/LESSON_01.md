# 第一课 从地点数据到筛选工具

日期：2026-10-03。配套代码已准备并运行验证，不代表用户已经学完。

这节课实现一件具体的事：从 18 个教学地点里，找出“有拍照标签、属于室内、每人价格不超过 50 元”的地点。全部地点信息都是虚构教学数据。

学完应能解释：数据从哪里来，函数怎样逐个判断地点，结果列表如何改变，返回值保存在哪里，以及这个函数以后怎样成为 Agent 的工具。

## 1 先运行三个小文件

在终端依次执行，先观察结果，再对照代码：

```bash
cd /path/to/weekend-agent  # 替换为你自己的项目目录
python3 examples/lesson01/01_data_basics.py
python3 examples/lesson01/02_filter_trace.py
python3 examples/lesson01/03_project_tool.py
```

| 文件 | 作用 | 观察重点 |
|---|---|---|
| `01_data_basics.py` | 演示字典、列表和 JSON 读取 | 数据类型怎样变化 |
| `02_filter_trace.py` | 逐个打印筛选过程 | `place`、`found` 与 `continue` |
| `03_project_tool.py` | 调用业务代码中的工具 | 文件关系、对象和参数变化 |

第三个文件的四组结果数量应依次为 3、1、9、5。脚本只读地点库并打印结果。

## 2 一条地点数据是什么

第一个脚本中有：

```python
place = {
    "id": "p09",
    "name": "示例城市展览馆",
    "tags": ["拍照", "文化"],
    "indoor": True,
    "price_per_person": 20,
}
```

`place` 是变量名，右边是字典 `dict`。字典使用“键 → 值”的对应关系。例如 `"name"` 是键，`"示例城市展览馆"` 是对应的值。

| 表达式 | 得到的值 | 类型 |
|---|---|---|
| `place["id"]` | `"p09"` | 字符串 `str` |
| `place["name"]` | `"示例城市展览馆"` | 字符串 `str` |
| `place["tags"]` | `["拍照", "文化"]` | 列表 `list` |
| `place["indoor"]` | `True` | 布尔值 `bool` |
| `place["price_per_person"]` | `20` | 整数 `int` |

`place["name"]` 的意思是：在地点字典中找键 `"name"`，取出它的值。字段名必须写对，`"price"` 和 `"price_per_person"` 不是同一个键。

`True` 表示是，`False` 表示否。这里用它表示地点是否室内。`tags` 本身又是一个列表，因为一个地点可以有多个标签。

业务地点库还包含游玩时长、营业时间等字段，本课暂时只关注筛选需要的字段。

## 3 多条地点放在哪里

```python
places = [
    place,
    {"id": "p10", "name": "示例摄影展", "price_per_person": 40},
]
```

外面的方括号表示列表 `list`，里面按顺序保存两个地点字典。

```python
places[0]           # 第一个字典
places[1]           # 第二个字典
places[0]["name"]  # 第一个字典中的名称
len(places)         # 列表长度，当前是 2
```

列表下标从 0 开始。`places[0]["name"]` 分两步：先用下标 0 取出一个字典，再用键 `"name"` 取出字符串。

`places` 常表示“多个地点”，`place` 常表示“其中一个地点”。名称没有语法魔法，但使用单数和复数有助于阅读。

## 4 从 JSON 文件到 Python 数据

项目地点文件是 `src/weekend_agent/data/hangzhou_demo.json`。外层结构可以缩写为：

```json
{
  "city": "杭州",
  "places": [
    {"id": "p09", "name": "示例城市展览馆", "indoor": true}
  ]
}
```

这是结构示意，不需要替换完整地点库。JSON 是保存和传输结构化数据的文本格式。

读取分两步：

```python
text = data_file.read_text(encoding="utf-8")
data = json.loads(text)
```

`read_text` 读取文本，得到字符串 `str`。`json.loads` 解析这段 JSON 文本，得到 Python 字典。字典里的 `"places"` 字段是一个列表，每个列表元素又是地点字典。

```text
JSON 文件 → 文本 text → 字典 data → data["places"] 地点列表
```

JSON 的 `true`、`false`、`null` 对应 Python 的 `True`、`False`、`None`。在 Python 文件里应写 `True`，在 JSON 文件里应写 `true`。

`utf-8` 指定文本编码，帮助正确读取中文。`json.loads` 中的 `s` 可理解为 string，这里处理的是已经读取到的字符串。

## 5 函数输入是怎么传进去的

第二个脚本顶部有四个可修改变量：

```python
CITY = "杭州"
USER_TAGS = ["拍照"]
INDOOR = True
MAX_PRICE = 50
```

之后传给函数：

```python
result = search_places_with_trace(
    data=data,
    city=CITY,
    tags=USER_TAGS,
    indoor=INDOOR,
    max_price=MAX_PRICE,
)
```

`city=CITY` 左边是函数参数名，右边是调用处变量，其值为 `"杭州"`，所以函数内部 `city` 得到 `"杭州"`。

同理，`tags` 得到 `["拍照"]`，`indoor` 得到 `True`，`max_price` 得到 `50`。这种写出参数名的方式叫关键字参数，有助于说明每个值的作用。

价格上限限制的是单个地点的每人价格。它不计算整天费用，行程总预算将在第二课累计检查。

## 6 循环中的两个变量

```python
found = []
for place in data["places"]:
    ...
```

`found` 保存符合全部条件的地点，初始为空列表。`for` 每次从地点列表中取一个字典，让 `place` 指向它，再执行缩进里的代码。

第一次 `place` 是公园，下一次是花园，之后依次取其他地点。`place` 每轮变化，而 `found` 在整个循环中累积结果。

Python 用缩进表示代码属于哪里。`found = []` 放在循环外面：如果每一轮都重新清空它，前面已经收集的结果就丢失了。

## 7 第一个条件 标签匹配

教学版把真实工具中的紧凑判断展开：

```python
if tags:
    common_tags = set(tags).intersection(place["tags"])
    if not common_tags:
        continue
```

- `if tags`：列表非空时进入；如果是 `[]`，表示不限制标签。
- `set(tags)`：把用户标签转换为集合；集合适合判断共同元素，会去除重复项。
- `intersection`：求用户标签与地点标签的交集。
- `if not common_tags`：如果交集为空，就没有匹配标签。
- `continue`：结束当前这一轮，立即取下一个地点。

以用户标签 `["拍照"]` 为例：

```python
set(["拍照"]).intersection(["拍照", "文化"])
# 非空集合 {"拍照"}：展览馆标签匹配

set(["拍照"]).intersection(["文化", "阅读"])
# 空集合 set()：书店标签不匹配
```

书店执行 `continue` 后，这一轮不会再检查室内和价格，也不会加入 `found`。循环仍会继续检查后面的地点。

真实工具写成：

```python
if tags and not set(tags).intersection(place["tags"]):
    continue
```

`and` 采用短路求值：只有用户标签非空，才计算右边的交集。如果没有指定标签，这条排除规则不生效。

当前规则是“任意一个标签匹配即可”。`["拍照", "美食"]` 表示接受拍照或美食地点，不要求每个地点同时拥有两个标签。

## 8 第二个条件 室内外筛选

```python
if indoor is not None:
    if place["indoor"] != indoor:
        continue
```

| 参数 indoor | 含义 |
|---|---|
| `True` | 只保留室内地点 |
| `False` | 只保留户外地点 |
| `None` | 不限制室内外 |

用户要求 `True`、公园是 `False` 时，`False != True` 成立，公园被跳过。

用户要求 `True`、展览馆也是 `True` 时，不执行跳过，继续检查价格。

用户传入 `None` 时，外层条件不成立，不检查室内外。

必须区分 `False` 和 `None`。如果误写成 `if indoor`，用户要求“只要户外”的 `False` 就会被错误地当成没有限制。

真实工具用一个条件表达同样的意思：

```python
if indoor is not None and place["indoor"] != indoor:
    continue
```

## 9 第三个条件 价格

```python
if place["price_per_person"] > max_price:
    continue
```

上限 50：20、40、45 都通过。上限 30：20 通过，40 和 45 被跳过。

这里使用 `>`，因此正好等于上限也能通过。换成 `>=` 会改变边界。

## 10 通过全部条件才 append

```python
found.append(place)
```

`append` 把一个元素加到列表末尾。这里加入完整的地点字典，方便后面的工具继续使用它的 ID、名称和价格。

不要写成 `found = found.append(place)`。`append` 直接修改列表，本身返回 `None`；把返回值赋给 `found` 会让它不再指向结果列表。

当前条件下，完整数据的变化如下。表中用 ID 简写列表，实际保存的是地点字典：

| 本轮地点 | 首个跳过原因或处理 | 本轮结束后的 found |
|---|---|---|
| p01 公园 | 户外 | `[]` |
| p02 花园 | 户外 | `[]` |
| p03 步道 | 户外 | `[]` |
| p04 市集 | 没有拍照标签 | `[]` |
| p05 观景台 | 户外 | `[]` |
| p06 骑行公园 | 没有拍照标签 | `[]` |
| p07 历史街区 | 户外 | `[]` |
| p08 夜景广场 | 户外 | `[]` |
| p09 展览馆 | 全部符合，append | `[p09]` |
| p10 摄影展 | 全部符合，append | `[p09, p10]` |
| p11 书店 | 没有拍照标签 | `[p09, p10]` |
| p12 桌游馆 | 没有拍照标签 | `[p09, p10]` |
| p13 手作工坊 | 没有拍照标签 | `[p09, p10]` |
| p14 室内乐园 | 没有拍照标签 | `[p09, p10]` |
| f01 面馆 | 没有拍照标签 | `[p09, p10]` |
| f02 家常菜馆 | 没有拍照标签 | `[p09, p10]` |
| f03 咖啡馆 | 全部符合，append | `[p09, p10, f03]` |
| f04 小吃店 | 没有拍照标签 | `[p09, p10, f03]` |

## 11 return 与 result

循环结束后：

```python
return {
    "data_mode": "fictional_demo",
    "places": found,
    "count": len(found),
}
```

函数创建结果字典并返回。`places` 保存匹配地点，`count` 保存数量，`data_mode` 标明使用教学数据。

调用处 `result = search_places_with_trace(...)` 接收这个字典，因此：

```python
result["count"]              # 3
result["places"]             # 三个地点字典组成的列表
result["places"][0]["name"] # 示例城市展览馆
```

`return` 结束整个函数；`continue` 只结束当前循环的一轮。`return` 应在循环后面，如果放进循环里，函数可能只检查一个地点就返回。

`print` 只是显示内容，不能替代返回值。`return` 也不会自动保存文件或数据库。

## 12 连接到真实项目中的类和对象

第三个脚本调用：

```python
from weekend_agent.tools import TripTools
tools = TripTools()
result = tools.search_places(city="杭州", tags=["拍照"], indoor=True, max_price=50)
```

`TripTools` 是类，定义这组工具和它们使用的数据。`tools` 是按这个类创建的对象。

创建对象时，初始化方法自动执行：

```python
def __init__(self, data_file: Path = DATA_FILE, rain: bool = False):
    self.data = json.loads(data_file.read_text(encoding="utf-8"))
    self.places = {place["id"]: place for place in self.data["places"]}
    self.rain = rain
```

`self` 指当前对象。创建 `tools` 时，这几行将数据保存到 `tools.data`、`tools.places` 和 `tools.rain`。

`tools.data["places"]` 是原地点列表；`tools.places` 是为了按 ID 查找而创建的字典：

```python
tools.data["places"][0] # 按顺序取第一个地点
tools.places["p09"]     # 按 ID 取城市展览馆
```

字典推导式可以展开为：

```python
self.places = {}
for place in self.data["places"]:
    self.places[place["id"]] = place
```

例如 `"p09"` 是键，展览馆的完整字典是值。真实搜索中的 `self.places.values()` 依次取出这个映射里的地点字典。

当前地点 ID 唯一，字典保持插入顺序，因此真实版与教学版遍历顺序一致。重复 ID 会覆盖映射中的先前条目，后续真实数据需要保证 ID 唯一。

调用 `tools.search_places(...)` 时，Python 自动将 `tools` 传给方法的 `self`，所以调用处不用填写 `self=tools`。

真实方法先执行 `self._check_city(city)`，确认地点库支持该城市，再开始筛选。

## 13 文件关系和启动代码

```text
03_project_tool.py → 导入 tools.py 中的 TripTools
                              ↓
                        从 config.py 取得 DATA_FILE
                              ↓
                        初始化时读取 JSON
                              ↓
                        search_places 筛选
                              ↓
03_project_tool.py ← 返回字典存到 result → 显示到终端
```

第三个脚本顶部：

```python
project_dir = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_dir / "src"))
```

`__file__` 表示当前文件路径。`resolve()` 转成绝对路径。对这个脚本来说，`parents[0]` 是 `lesson01`，`parents[1]` 是 `examples`，`parents[2]` 是项目目录。`/ "src"` 拼接路径。

`sys.path` 是 Python 寻找可导入模块的路径列表。把 `src` 放进去，后面的导入就能找到项目源码。

末尾的：

```python
if __name__ == "__main__":
    main()
```

表示直接运行文件时执行 `main()`。其他程序只导入这个文件时，不自动运行 `main()`。

## 14 类型提示如何阅读

真实方法定义：

```python
def search_places(self, city: str, tags: list[str], indoor: bool | None,
                  max_price: float) -> dict:
```

`city: str` 表示城市应是字符串；`tags: list[str]` 表示字符串列表；`bool | None` 表示布尔值或 None；`max_price: float` 表示数值条件；`-> dict` 表示返回字典。

类型提示帮助阅读和开发工具检查，但 Python 不会只凭提示自动验证参数。后续模型生成参数时还会经过 `ToolRegistry` 校验。本课用正确参数直接调用函数。

脚本传入 `50` 是整数，与地点价格比较可以正常运行。

## 15 自己修改的小练习

修改 `02_filter_trace.py` 顶部的条件变量。每次只改一项，先预测，再观察运行结果：

| 练习 | 修改 | 观察 |
|---|---|---|
| A | `MAX_PRICE = 30` | 摄影展和咖啡馆如何被跳过 |
| B | 恢复 50，改 `INDOOR = None` | 室内外检查是否跳过 |
| C | 恢复 True，改 `USER_TAGS = []` | 书店是否入选 |
| D | 改 `USER_TAGS = ["拍照", "美食"]`，其余保持 True、50 | 没有拍照标签的面馆是否入选 |

自查：

1. `place`、`places`、`found` 和 `result` 各是什么？
2. `found` 为什么放在循环外面？
3. 执行 `continue` 后，这一轮后面的代码还执行吗？
4. `False` 与 `None` 有什么不同？
5. 为什么函数结束以后，调用处能读到 `result["count"]`？
6. 多个标签是否要求全部匹配？
7. 为什么单个地点不超 50 元，不代表整天不超 50 元？

## 16 核对答案与面试表达

A：1 个，展览馆。B：9 个，公园、花园、步道、观景台、历史街区、夜景广场、展览馆、摄影展、咖啡馆。C：6 个，展览馆、摄影展、书店、面馆、咖啡馆、小吃店。D：5 个，展览馆、摄影展、面馆、咖啡馆、小吃店。

`place` 是单个地点字典；`places` 是地点集合；`found` 是筛选结果列表；`result` 是返回的结果字典。`found` 在循环外初始化以保留已找到的地点。`continue` 跳过本轮剩余代码。False 限制户外，None 不限制。`result` 接收 return 返回的字典，没有自动保存文件。标签是任意匹配，整天费用需要累计地点与交通费用。

理解后可以这样解释这块实现：

> 我把地点数据保存为 JSON，实现了一个确定性的筛选函数。它根据兴趣标签、室内外条件和单个地点的每人价格上限返回候选地点。标签采用任意匹配，None 表示不限制室内外。函数返回地点列表和数量，后续程序或模型可以继续使用。总预算要通过另一个工具累计检查。

本课没有模型调用。以后 Agent 会把需求转换成工具参数，再调用同一个业务函数；这节课的输入、筛选规则与返回值会直接用于后续工具调用。
