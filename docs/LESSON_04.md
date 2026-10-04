# 第4课：模型怎样“调用”一个Python函数

前置知识：第2课的Schema和注册表，第3课的工具计算。本课先不联网，把通信格式练熟；接入DeepSeek之后，模型只是替换掉手写的那条调用消息。

## 1. 你要解决的疑惑

模型运行在远端，`TripTools.get_weather`运行在你的电脑。模型既看不到你的Python对象，也不会直接执行函数。它输出一段结构化请求；本地程序读取请求、运行允许的函数、再把结果交回模型。

```text
模型输出工具名和参数
    ↓ JSON解析与参数检查
本地注册表执行Python函数
    ↓ 结果编码成JSON文本
追加一条tool消息
    ↓ 再发给模型
模型继续决定下一步
```

本课学完应能手写一组配对消息，并定位“格式错”“参数错”“ID错”分别发生在哪层。

## 2. 文件和实验入口

- [providers.py](../src/weekend_agent/providers.py)：`tool_call`是构造教学请求的辅助函数。
- [tools.py](../src/weekend_agent/tools.py)：`ToolRegistry.execute`真正执行工具。
- [agent.py](../src/weekend_agent/agent.py)：读取调用消息、检查协议并回传结果。
- [基本消息实验](../examples/lesson04/01_message_protocol.py)：打印一套完整请求与回传。
- [错误分层实验](../examples/lesson04/02_protocol_failures.py)：比较不同错误。

```bash
python3 examples/lesson04/01_message_protocol.py
python3 examples/lesson04/02_protocol_failures.py
```

## 3. messages究竟是什么

`messages`是一个有顺序的Python列表，每个元素是一个消息字典。

| role | 谁在提供内容 | 例子 |
|---|---|---|
| system | 应用定义规则 | 只能使用教学数据、不能编造票价 |
| user | 用户需求或应用反馈 | 根据表单安排，或最终校验失败原因 |
| assistant | 模型返回 | 请求调用工具，或给出最终候选 |
| tool | 本地程序执行结果 | 天气工具返回的JSON文本 |

顺序有意义：不能先放工具结果，再放触发它的请求。`role`也不是随便起的标签，供应商接口会检查这些约定。

## 4. 看懂一条工具调用

```python
call = {
    "id": "weather_001",
    "type": "function",
    "function": {
        "name": "get_weather",
        "arguments": '{"city":"杭州","travel_date":"2026-11-21"}',
    },
}
```

逐层读取：

| 表达式 | 得到的值 | Python类型 |
|---|---|---|
| call | 整条工具请求 | dict |
| call["id"] | weather_001 | str |
| call["function"] | name与arguments组成的对象 | dict |
| call["function"]["name"] | get_weather | str |
| call["function"]["arguments"] | 花括号包围的JSON文本 | str |

最后一个是字符串，虽然长得像字典。对它直接执行`arguments["city"]`会失败，因为字符串不能用`"city"`当下标。

需要先做：

```python
arguments = json.loads(call["function"]["arguments"])
# 现在arguments是Python字典
# {"city": "杭州", "travel_date": "2026-11-21"}
```

`loads`可以理解为“从字符串加载JSON”；`dumps`是“把Python对象编码成JSON字符串”。不要把两者方向记反。

## 5. 一步步执行同一个例子

第一步，列表里只有需求，长度为1：

```python
messages = [{"role": "user", "content": "查教学天气。"}]
```

第二步，把assistant请求追加进去，长度变2：

```python
messages.append({
    "role": "assistant",
    "content": None,
    "tool_calls": [call],
})
```

这里`content=None`表示这条消息没有普通文字；它的有效内容放在`tool_calls`里。`tool_calls`仍然是列表，因为一次回复可能请求多个工具。

第三步，解析参数，并通过注册表执行：

```python
name = call["function"]["name"]
arguments = json.loads(call["function"]["arguments"])
result = registry.execute(name, arguments)
```

在注册表内部，会先确认`name`属于允许列表，再检查参数类型和必填字段，最后执行类似下面的调用：

```python
registry.tools.get_weather(city="杭州", travel_date="2026-11-21")
```

`**arguments`的作用，就是把字典展开为这种具名参数。`getattr`只在注册表已经确认工具名以后使用；没有把模型文本交给`eval`执行。

第四步，把结果编码并追加，长度变3：

```python
messages.append({
    "role": "tool",
    "tool_call_id": call["id"],
    "content": json.dumps(result, ensure_ascii=False),
})
```

`ensure_ascii=False`让中文在输出中直接可读，而不是变成Unicode转义序列。它不改变工具结果的业务含义。

## 6. 为什么还要有ID

假设同一条assistant消息请求两次天气：一次杭州，一次别的城市。两个工具名都可能叫`get_weather`，仅靠名称就分不清哪个结果对应哪次请求。

ID相当于本次请求的流水号：

```text
assistant.tool_calls[0].id = weather_001
                     ↕ 必须匹配
tool.tool_call_id          = weather_001
```

本项目检查同一批调用ID非空且不重复。随后对每个请求追加对应结果。当前教学来源可能在不同用户回合复用固定ID；这不代表生产系统应该依赖ID固定值，真正的配对依据始终是消息顺序与调用ID。

错误实验故意在同一批放两个`same`，Agent会在执行工具之前停止，不让结果配对变得含糊。

## 7. 三种错误，不要混成一句“API坏了”

| 错误 | 示例 | 哪层发现 | 本项目处理 |
|---|---|---|---|
| JSON语法错误 | `'{"city":'` | json.loads | 生成工具错误结果 |
| Schema错误 | 只有city，没有travel_date | 注册表 | ok=False，说明缺字段 |
| 协议错误 | 没有ID、重复ID、function不是对象 | Agent | 停止当前运行 |

工具错误仍要回传一条`role=tool`消息。否则assistant已经提出请求，却一直没有对应结果，下一次模型API可能直接拒绝整段历史。

可以把“查不到地点”作为工具结果告诉模型；但如果连哪条结果属于哪个请求都无法确定，就不能假装继续正常对话。

## 8. 练习与参考答案

**A.** `json.loads`会执行JSON里写的Python代码吗？

<details><summary>答案</summary>
不会。它只解析JSON的数据语法。注册表再依据允许列表选择本地函数。`eval`与JSON解析不是同一种操作，本项目没有让模型提交任意Python代码执行。
</details>

**B.** 把`travel_date`改成`date`，哪一步会报错？

<details><summary>答案</summary>
JSON文本仍可以成功解析，但Schema要求`travel_date`且拒绝未知字段，所以注册表检查失败。不是网络错误，也不是日期计算错误。
</details>

**C.** 在工具执行失败时直接`continue`，不追加tool消息，可以吗？

<details><summary>答案</summary>
不可以这样处理整个协议。应该把`{"ok":false,"error":"..."}`编码进配对的tool消息，再让模型根据错误修正。否则留下没有结果的调用请求。
</details>

**D.** 一条assistant消息里有两个调用，意味着工具一定并行运行吗？

<details><summary>答案</summary>
不意味着。本项目用`for call in calls`逐个执行。一次批量提出请求是消息层的能力，并行执行是应用层的调度选择。
</details>

**E.** 给正确结果故意换一个`tool_call_id`，如何检查？

<details><summary>答案</summary>
打印assistant中的ID列表，再打印紧随其后的tool结果ID列表，逐项比对。先在离线教学脚本观察，不需要花API额度来制造这种已知错误。
</details>

## 9. 面试表达与追问

题库入口：[Q13–Q16](INTERVIEW_BANK.md#q13)。

> Function Calling在这个项目中是一套结构化请求协议。模型输出工具名称和JSON参数，本地注册表验证后调用Python函数，再把执行结果通过相同tool_call_id交回模型。模型提出调用，并不等于远端直接执行了我的Python代码。

追问“为什么把错误也返回？”：为了保持请求与结果配对，并提供可修正的信息。追问“Schema能保证业务正确吗？”：它主要检查形状和参数范围，交通和预算仍要由工具计算，最终结果还要按表单重新检查。

## 10. 本课完成标准

能在不看原文件时写出一条assistant工具请求和对应tool结果；能解释两个JSON转换方向；能从报错判断是在JSON层、Schema层还是消息协议层。完成后进入[第5课](LESSON_05.md)。
