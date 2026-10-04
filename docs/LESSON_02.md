# 第二课 从 Python 函数到可调用工具

日期：2026-10-03，来源为本聊天。用户已表示理解第一课并要求进入下一步；本课材料已准备，不代表用户已经学完第二课。

这一课继续使用 `search_places`，完成一个目标：将工具请求里的 JSON 参数转换成 Python 字典，检查参数，再执行对应函数并返回结构化结果。

请求由我们手写，全部地点仍为虚构教学数据，没有调用大模型。真正的模型请求和消息循环在后续课程接入。

## 1 先运行三个小文件

```bash
cd /path/to/weekend-agent  # 替换为你自己的项目目录
python3 examples/lesson02/01_tool_schema.py
python3 examples/lesson02/02_arguments_to_function.py
python3 examples/lesson02/03_registry_errors.py
```

| 文件 | 本次新增的理解 | 预期结果 |
|---|---|---|
| `01_tool_schema.py` | 工具名字、用途和参数规则 | 打印搜索工具的 JSON 说明 |
| `02_arguments_to_function.py` | JSON 参数解析与 `**arguments` | 找到 3 个地点，两种调用方式结果相同 |
| `03_registry_errors.py` | 按名字查工具、检查参数、返回错误 | 1 次成功和 6 次具体错误 |

先运行并观察。第一遍不需要读懂 `validate_arguments` 的完整递归实现；本课重点是参数规则、调用路径和返回值。

## 2 第一课的函数还缺什么

第一课直接写：

```python
result = tools.search_places(
    city="杭州", tags=["拍照"], indoor=True, max_price=50,
)
```

是我们在代码里指定了函数和参数。后续让模型选择工具时，我们要先告诉模型：有哪些工具，每个工具解决什么问题，需要哪些参数。

模型接口收到的是工具说明。模型可以返回工具名字和参数，然后由我们的程序检查并执行 Python 函数。模型没有在自己的回答里直接运行本地 Python。

这节课先手写一个请求，把请求到函数的路径跑通。

## 3 Schema 是什么

这里的 Schema 指数据的结构与规则。工具参数用 JSON Schema 的形式描述，例如：

```json
{
  "type": "function",
  "function": {
    "name": "search_places",
    "description": "搜索教学地点；价格为每人金额。indoor=null 表示不限室内外。",
    "parameters": {
      "type": "object",
      "properties": {
        "city": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "indoor": {"type": ["boolean", "null"]},
        "max_price": {"type": "number", "minimum": 0}
      },
      "required": ["city", "tags", "indoor", "max_price"],
      "additionalProperties": false
    }
  }
}
```

逐层看：

- 外层 `type="function"`：这是一个函数工具的说明。
- `function.name`：程序用这个名字找到对应工具。
- `function.description`：说明工具用途，帮助模型选择。
- `function.parameters`：规定调用时参数的结构。
- 参数的 `type="object"`：整组参数是一个对象，在 Python 中用字典表示。
- `properties`：每个字段允许的类型和规则。
- `required`：这些字段必须出现。
- `additionalProperties=false`：不接受说明里没有定义的字段。

工具说明不是函数的实现。它没有遍历地点，也没有执行 `found.append`。实际筛选仍由第一课的 `TripTools.search_places` 执行。

## 4 每个参数的类型

| 字段 | 规则 | 正确示例 | 不正确示例 |
|---|---|---|---|
| `city` | 字符串 | `"杭州"` | `123` |
| `tags` | 列表，里面每项是字符串 | `["拍照"]`、`[]` | `"拍照"`、`[123]` |
| `indoor` | 布尔值或 null | `true`、`false`、`null` | `"室内"`、`1` |
| `max_price` | 不小于 0 的数字 | `50`、`30.5`、`0` | `"50"`、`-1` |

`50` 是数字；`"50"` 是字符串，即使看起来都是五十，参数检查也会区分。

`tags` 的规则分两层：先要求外层是列表，再要求每个元素是字符串。这对应第一课的“多个兴趣标签”。

`max_price` 仍然是每人单个地点的价格上限，不是整天或全组预算。

## 5 required 和 null 是两件事

本项目要求 `indoor` 必须提供，但允许它的值为 `null`：

```json
{"city": "杭州", "tags": ["拍照"], "indoor": null, "max_price": 50}
```

这表示明确提供“室内外不限”的条件。

下面省略了 `indoor`，会被判定为缺少必填字段：

```json
{"city": "杭州", "tags": ["拍照"], "max_price": 50}
```

所以，“字段必须出现”与“字段的值不能为 null”不能混为一谈。是否允许 null，要看 `type`。

## 6 JSON 与 Python 的写法

| 含义 | JSON 文本 | Python 值 |
|---|---|---|
| 是 | `true` | `True` |
| 否 | `false` | `False` |
| 空值 | `null` | `None` |

JSON 文本中的键和字符串使用双引号。第一课学习的 `json.loads` 会把 JSON 文本转换成 Python 数据：

```python
arguments = json.loads(arguments_text)
```

第一个脚本还使用了反方向的转换：

```python
json.dumps(schema, ensure_ascii=False, indent=2)
```

`dumps` 将 Python 字典转换成 JSON 字符串。`ensure_ascii=False` 让中文直接显示；`indent=2` 增加缩进便于阅读，它们不改变参数规则。

`loads` 中的 s 表示从字符串读取。这里没有保存新文件，也没有发送网络请求。

## 7 手写一份工具请求

第二个脚本中：

```python
tool_request = {
    "name": "search_places",
    "arguments": """{
        "city": "杭州",
        "tags": ["拍照"],
        "indoor": true,
        "max_price": 50
    }""",
}
```

这是工具请求中 `function` 部分的教学示意。完整接口响应还有消息角色、调用 ID 等字段，后续再学。

这里有两层不同的数据：

- 外面的 `tool_request` 是 Python 字典。
- `tool_request["arguments"]` 是三引号包住的多行字符串，里面的内容采用 JSON 格式。

三引号用于保存多行文本。由于里面是文本，JSON 的 `true` 不会被 Python 当成变量运行。

执行后的变量变化：

| 语句 | 变量 | 值或类型 |
|---|---|---|
| `name = tool_request["name"]` | `name` | 字符串 `"search_places"` |
| `arguments_text = tool_request["arguments"]` | `arguments_text` | JSON 格式的字符串 `str` |
| `arguments = json.loads(arguments_text)` | `arguments` | Python 字典 `dict` |
| 读取 `arguments["indoor"]` | 字段的值 | Python 布尔值 `True` |

本课使用的 JSON 文本语法正确。JSON 语法错误会先在解析阶段报错，尚未进入工具注册表，不要与后面的参数规则错误混为一谈。

## 8 **arguments 怎样调用函数

```python
result = tools.search_places(**arguments)
```

在函数调用位置，`**` 将字典展开为关键字参数。假如字典是：

```python
arguments = {
    "city": "杭州", "tags": ["拍照"], "indoor": True, "max_price": 50,
}
```

上面的调用相当于：

```python
result = tools.search_places(
    city="杭州", tags=["拍照"], indoor=True, max_price=50,
)
```

字典的键对应函数的参数名，字典的值对应传入的值。这里的 `**` 不是乘法，也不是让模型执行代码，而是 Python 的参数展开语法。

`arguments` 字典不会被展开操作删除。执行之后，`result` 保存普通函数返回的字典，仍然可以读取 `result["count"]` 和 `result["places"]`。

第二个脚本用两种写法各调用一次搜索，再用 `==` 比较返回值。预期相同，都得到 3 个地点。两次调用是为了演示等价关系，实际应用只需要调用一次。

## 9 为什么还要参数检查

函数参数上的类型注解，例如 `max_price: float`，主要是给开发者和开发工具看的，普通 Python 调用不会自动据此检查类型。

工具说明可以约束和指导请求，但不能替代应用自己的运行时检查。因此，本项目在执行工具前调用 `validate_arguments`。

对搜索工具，它检查：

1. 参数整体是否是字典。
2. 必填字段是否齐全。
3. 是否包含未定义字段。
4. 每个字段的类型是否正确，包括列表元素的类型。
5. 数字是否为有限数字，并符合最小值等规则。

本项目的检查函数只实现我们使用到的 JSON Schema 子集，不是完整的通用 JSON Schema 库。

这节课先理解“什么会通过、什么会被拒绝”。递归检查列表与字典的实现可以之后单独拆解。

## 10 ToolRegistry 保存什么

第三个脚本创建：

```python
tools = TripTools()
registry = ToolRegistry(tools)
```

`tools` 是第一课那个对象，保存地点库，提供业务函数。

`registry` 是另一个对象，保存这个 `tools` 对象和工具说明。它负责根据请求的名字找到工具，并在执行前检查参数。

业务代码的初始化逻辑是：

```python
self.tools = tools
self.schemas = TOOL_SCHEMAS
self.by_name = {item["function"]["name"]: item["function"] for item in self.schemas}
```

最后一行是字典推导式。暂时展开成普通写法理解：

```python
self.by_name = {}
for item in self.schemas:
    function_info = item["function"]
    name = function_info["name"]
    self.by_name[name] = function_info
```

最后得到“工具名字 → 工具说明”的对应关系，例如：

```python
self.by_name["search_places"]
```

可以取到搜索工具的名字、描述和参数规则。这个字典保存的是说明；实际函数仍然在 `self.tools` 对象上。

## 11 execute 的运行顺序

项目的实际代码是：

```python
def execute(self, name, arguments):
    try:
        if name not in self.by_name:
            raise ValueError(f"未知工具：{name}")
        validate_arguments(arguments, self.by_name[name]["parameters"])
        return {"ok": True, "data": getattr(self.tools, name)(**arguments)}
    except (ValueError, TypeError, KeyError) as error:
        return {"ok": False, "error": str(error)}
```

这里省略了类型注解便于阅读，执行逻辑与项目相同。

按顺序理解：

1. `try` 中是尝试执行的代码。
2. 检查工具名字是否已登记，未知名字产生 `ValueError`。
3. 取出这个工具的参数规则，检查 `arguments`。
4. 检查通过后，找到对应的 Python 函数并调用。
5. 函数正常返回，就包装成 `ok=True` 的结果。
6. 如果过程中出现列出的异常类型，进入 `except`，包装成 `ok=False` 的错误结果。

`raise` 的意思是产生异常。发生异常后，不会继续执行 `try` 内后面的语句，而是寻找匹配的 `except`。

`str(error)` 把异常对象转换成可读的错误文本。`except` 只处理列出的三类异常，不代表所有程序错误都会被吞掉。

## 12 getattr 又是什么

```python
getattr(self.tools, name)(**arguments)
```

先拆成两行：

```python
function = getattr(self.tools, name)
data = function(**arguments)
```

当 `name == "search_places"` 时：

```python
function = self.tools.search_places
```

这一步只是取到方法，还没执行。下一行有括号才执行：

```python
data = function(**arguments)
```

`getattr` 用一个字符串名字取得对象的属性。这里取得的是方法；程序在之前已确认工具名字在登记列表中。

这解决了一个实际问题：工具请求里的名字是字符串，我们怎样根据字符串调用对应方法。

## 13 成功和失败为什么长得不一样

成功返回的结构示意：

```python
{
    "ok": True,
    "data": {"data_mode": "fictional_demo", "places": [...], "count": 3},
}
```

`...` 表示此处省略了完整的地点列表，不是要求你把地点替换成省略号。

现在 `count` 被包在 `data` 里面，因此读取方式变成：

```python
result["data"]["count"]
```

失败返回：

```python
{"ok": False, "error": "arguments.max_price 类型应为 ['number']"}
```

失败没有 `data` 字段，所以第三个脚本先判断：

```python
if result["ok"]:
    # 读取 result["data"]
else:
    # 读取 result["error"]
```

这样后续模型也能读取具体错误并尝试修正参数。本课只演示错误返回，尚未实现模型自动修正。

## 14 观察七个请求

| 请求 | ok | 失败或成功的位置 |
|---|---|---|
| 正确参数 | True | 搜索函数执行，找到 3 个地点 |
| 删除 indoor | False | 参数检查：缺少必填字段 |
| max_price 改为字符串 "50" | False | 参数检查：价格类型错误 |
| max_price 改为 -1 | False | 参数检查：价格超出允许范围 |
| 多加 budget_total | False | 参数检查：未知字段 |
| city 改为 "上海" | False | 参数检查通过，业务函数发现地点库不支持 |
| 工具名 search_hotels | False | 名字检查：工具未登记 |

重点观察“上海”这个例子：`"上海"` 是字符串，因此满足 Schema 的类型要求；但是当前业务地点库只支持杭州，`search_places` 里的 `_check_city` 会产生异常，再由注册表转换成错误返回。

参数检查与业务规则各负责一部分。通过参数检查不代表业务一定成功，也不代表内容符合现实。

第三个脚本使用 `arguments.copy()` 复制外层字典，再修改测试字段。它是浅拷贝；里面的 `tags` 列表仍然共享，本课没有改这个列表。

`del missing["indoor"]` 删除的是新字典中的一个键。把 `wrong_type["max_price"]` 改成字符串，也不会修改原始字典对应的数字。

## 15 文件怎样连接

```text
examples/lesson02/01_tool_schema.py
    → 读取 tools.py 的 TOOL_SCHEMAS
    → 打印工具说明

examples/lesson02/02_arguments_to_function.py
    → json.loads 解析手写 JSON 参数
    → 直接调用 TripTools.search_places
    → 搜索 hangzhou_demo.json 中的地点

examples/lesson02/03_registry_errors.py
    → 创建 TripTools 和 ToolRegistry
    → registry.execute 检查工具名字和参数
    → 检查通过才执行 TripTools.search_places
    → 返回成功数据或具体错误
```

本次新增的是教学入口，复用项目现有的工具说明与注册表，没有另写一套业务搜索算法。所有调用都在本地运行，不需要密钥。

## 16 一个小练习

打开 `examples/lesson02/02_arguments_to_function.py`，把 JSON 文本中的：

```json
"indoor": true
```

改成：

```json
"indoor": null
```

只改这一行，运行同一个脚本。先预测，再看结果。

应该观察到：

- JSON 解析后，`arguments["indoor"]` 是 Python 的 `None`。
- 两种调用方式的返回结果仍然相同。
- 搜索不限制室内外，地点数量从 3 变成 9。
- `found` 仍然需要满足拍照标签和每人不超过 50 元的规则。

自测问题：

1. 工具说明里的 description 会执行搜索吗？
2. `tool_request["arguments"]` 与 `json.loads` 后的 `arguments` 分别是什么类型？
3. `**arguments` 与直接写四个关键字参数是什么关系？
4. 为什么 `indoor=null` 可以，但完全不提供 indoor 不可以？
5. 为什么 "上海" 能通过类型检查，却仍然返回 `ok=False`？

本课完成后应能用自己的话说明：“工具说明描述调用方式；程序解析请求、检查参数，再按名字执行 Python 方法；正常结果和已处理的错误都用字典返回。”

下一课再做预算与时间校验，让工具能判断一份行程是否可执行，然后学习真实的工具调用消息与循环。
