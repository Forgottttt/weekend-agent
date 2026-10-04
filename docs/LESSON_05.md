# 第5课：Agent循环、失败修正和停止条件

前置知识：第4课的消息配对。本课把一次工具调用放进循环，理解程序为什么要多次请求模型，以及什么时候应该停止。

## 1. 本课的三个问题

1. 谁决定下一步查天气、搜地点还是给出答案？
2. 工具结果怎样进入下一次模型请求？
3. 模型一直出错，程序会不会永远运行？

读懂后，你应该能拿着一段日志按轮次复述，而不是只说“Agent会自己规划”。

## 2. 文件和实验

| 文件 | 关注点 |
|---|---|
| [agent.py](../src/weekend_agent/agent.py) | TripAgent.run的外层轮数循环、内层工具循环 |
| [planning.py](../src/weekend_agent/planning.py) | DayDemoProvider及build_demo_stops |
| [providers.py](../src/weekend_agent/providers.py) | ChatProvider协议和APIProvider |
| [service.py](../src/weekend_agent/service.py) | 根据demo/live选择实现 |

```bash
python3 examples/lesson05/01_agent_loop.py
python3 examples/lesson05/02_repair_and_limits.py
```

第二个实验的“修正”是我们手写好的脚本化序列，用来观察执行器，不代表真实DeepSeek已经完成自我修复。

## 3. 先把对象关系画出来

```text
PlanningService
  ├─ TripRequest：保存用户条件
  ├─ TripTools → ToolRegistry：提供本地工具
  ├─ DayDemoProvider 或 APIProvider：提供下一条assistant消息
  └─ TripAgent：把消息、工具、结束条件串起来
```

`provider`可以先理解为“消息来源”。Agent只要求它有`complete(messages, tools)`，并返回assistant字典；不关心消息是规则拼出来的，还是网络模型生成的。

这就是接口抽象的用途：用固定输入输出约定隔开实现。它让你能在不花API费用的情况下测试循环，也让换模型时不用重写预算工具。

## 4. 进入循环前发生了什么

`TripAgent.__init__`先创建一条system消息。调用`run(question, request)`时，追加一条user消息，因此正常第一轮来源调用前有2条消息。

其中结构化条件被编码成以下内容：

```text
STRUCTURED_REQUEST:
{"city":"杭州","budget_per_person":30,...}
USER_NOTE:
按30元预算安排
```

表单条件是权威约束。补充文字可以说“尽量多拍照”，但不能靠一句“忽略预算”把表单30元改成999元。

`events=[]`收集本次调用事件；`place_ids=set()`收集本轮真正搜索到的地点；`guides={}`收集本轮检索到的资料。每次新的用户请求都会重新初始化这些证据，不能直接拿上一轮的候选冒充本轮搜索结果。

## 5. 读外层for循环

把业务细节暂时折叠，剩下这条主线：

```python
for round_index in range(1, self.max_rounds + 1):
    message = provider.complete(messages, schemas)
    calls = message.get("tool_calls") or []
    # 先检查消息形状与调用ID
    messages.append(message)
    if not calls:
        # 把content作为最终候选校验
        # 通过则return；不通过则追加反馈并continue
        ...
    for call in calls:
        # 解析、执行、追加tool结果
        ...
```

`range(1, max_rounds + 1)`把右端加1，是因为range不包括右端。例如上限3时轮次是1、2、3。

`message.get("tool_calls") or []`把字段缺失或`None`统一成空列表。但收到一个非空字典冒充列表时，随后仍会检查类型并报错。

`return`离开整个`run`函数；`continue`开始下一轮外层循环。第1课见过这个区别，现在它决定“任务结束”还是“让模型再改一次”。

## 6. 用一个3轮实验跟踪变量

`ScriptedRepair`内部有`stage`。每次被调用就加1：

- stage=1：请求搜索美食地点。
- stage=2：提交35元的面馆，但用户预算30元。
- stage=3：改为25元小吃店。

| 来源调用前 | messages长度 | 最后一条角色 | 来源输出 | 执行器处理 |
|---|---:|---|---|---|
| 第1轮 | 2 | user | search_places请求 | 执行搜索，追加tool结果 |
| 第2轮 | 4 | tool | 35元面馆候选 | 校验拒绝，追加user反馈 |
| 第3轮 | 6 | user | 25元小吃店候选 | 校验通过，return |

为什么第2轮之后长度从4变6？先追加了assistant候选，再追加了应用拒绝反馈。下一轮模型同时看得到自己上次提了什么，以及为什么被拒绝。

本实验结束时：`provider_calls=3`、`tool_calls=1`、`final_checks=2`。一个数字不能替代另一个。

## 7. 为什么“没有tool_calls”还不能立即展示

没有工具调用仅意味着来源这一次选择输出普通content。模型可能输出不完整JSON、没搜索过的地点或超预算方案。

结构化模式下，Agent把content交给`verify_final`。若失败：

```text
events追加 final_rejected
final_checks增加
未达上限 → messages追加拒绝原因 → 下一轮
达到上限 → 报错停止
```

通过后调用`render_plan`，展示应用重新计算的结果。详见第7课。

## 8. 三种上限解决不同问题

| 上限 | 本项目行为 | 防止什么 |
|---|---|---|
| max_rounds | Service使用12轮 | 来源无限继续对话 |
| max_tool_calls | Service使用20次工具请求 | 单轮或多轮工具调用膨胀 |
| 最终校验次数 | 连续候选最多检查3次 | 不停提交不合格最终答案 |

假设第一轮返回30个工具请求，不能因为“才第一轮”就全部执行。工具数量上限要在执行这批之前检查。

达到工具上限时，程序会移除那条尚未执行的assistant调用消息，避免保留一组没有对应结果的请求。达到轮数上限则明确报告本轮没有最终答案。

APIProvider还有自己的HTTP重试上限。一次来源调用遇到429后重试，会产生多个HTTP尝试，但在Agent的`provider_calls`中仍是同一轮。网页现在同时展示这两个数字。

## 9. 离线规则流程与真实Agent的关系

`DayDemoProvider`按写好的阶段顺序运行：天气→地点→资料→路线→行程检查→最终候选。`build_demo_stops`用贪心规则最多选六站，每次从当前可行地点中按偏好、费用、结束时间等排序取一个。

“贪心”指每步选当前最合适者，不枚举所有整条路线。因此局部选择可能挡住后面更好的方案，没找到候选也不证明数学上无解。

`APIProvider`则把工具说明和当前消息交给DeepSeek，由模型返回下一步请求。两者共用执行器，便于比较和回归，但不能把离线12/12宣传成模型能力。

本项目工具仍按顺序执行，没有多Agent协作。手写执行器是为了先看清底层协议，之后才适合讨论LangGraph的节点、状态和边。

## 10. 动手练习

**A.** 把修正实验`max_rounds`设为2，为何没有最终答案？

<details><summary>参考答案</summary>
第二轮仅提出了35元方案，应用拒绝后需要第三轮才能拿到25元方案。轮数已经耗尽，程序不能把被拒绝的候选当成完成结果。
</details>

**B.** 把`ScriptedRepair`第3轮也设为f01，会发生什么？

<details><summary>参考答案</summary>
如果允许足够多来源轮次，最终候选会连续三次被拒绝，然后报最终方案校验失败；若轮数更小，可能先触发轮数上限。哪个护栏先达到，哪个先停止运行。
</details>

**C.** 第一轮请求两个工具且都成功，`tool_calls`加几，`provider_calls`加几？

<details><summary>参考答案</summary>
工具加2，来源调用加1。最终校验还没有发生，因此此时`final_checks`不增加。
</details>

**D.** 只增大`max_rounds`是否能保证更高成功率？

<details><summary>参考答案</summary>
不能。可能只是多付费用并更晚失败。先看失败事件属于参数、知识、约束、协议还是截断，再调整提示词、工具或配置，并用相同评测集比较。
</details>

## 11. 面试时组织答案

对应[Q17–Q20](INTERVIEW_BANK.md#q17)。

> 我先实现统一的消息来源接口和工具执行循环，离线阶段用规则来源做可复现回归，live阶段替换为DeepSeek。每轮记录工具输入输出与最终拒绝原因，设置来源轮数、工具次数、最终校验次数上限。模型提出候选，应用负责按用户条件重算，所以生成不代表通过。

追问“为什么没有多Agent？”：本任务规模小、工具共享同一个结构化请求。先把单Agent协议、评测和故障处理做清楚，比增加角色数量更容易定位问题。未来只有出现可独立验证的子任务时再考虑分工。

## 12. 过关标准

不用看代码，解释3轮修正的消息长度为什么是2、4、6；指出`continue`与`return`的位置；解释为什么3轮来源调用不一定等于3次HTTP请求。然后进入[第6课](LESSON_06.md)。
