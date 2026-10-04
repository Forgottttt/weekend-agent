# 第7课：为什么模型说“通过了”，程序还要再查一遍

前置知识：第3课计算规则、第5课循环。本课最重要的概念是：**用户约束由应用保存，模型只能提出候选。**

## 1. 从一个能复现的错误开始

表单预算30元。模型想选35元面馆，却给工具传了999元预算：

```python
registry.execute("check_itinerary", {
    "stops": [{"place_id": "f01", "start": "12:00"}],
    "budget_per_person": 999,
    "group_size": 2,
    "start_time": "10:00",
    "end_time": "18:00",
})
```

工具返回valid=True并不奇怪：35确实小于999。工具没有收到真正的30元约束，不能指望它猜出来。

如果应用直接相信这个结果，就会向用户展示超预算方案。真正要修的是数据的权威来源，而不是在提示词里多写十遍“不要超预算”。

## 2. 文件与实验

| 文件 | 负责什么 |
|---|---|
| [request.py](../src/weekend_agent/request.py) | 表单验证后保存TripRequest |
| [finalize.py](../src/weekend_agent/finalize.py) | verify_final校验候选，render_plan展示 |
| [agent.py](../src/weekend_agent/agent.py) | 收集搜索证据、拒绝后让来源修正 |
| [测试](../tests/test_complete_project.py) | 预算999绕过、虚构引用等回归 |

```bash
python3 examples/lesson07/01_final_verification.py
python3 examples/lesson07/02_attack_cases.py
python3 examples/lesson05/02_repair_and_limits.py
```

这些攻击案例是为了检验本地程序的校验边界，全部离线，不发送真实模型请求。

## 3. 最终JSON为什么只有三个字段

```json
{
  "status": "planned",
  "stops": [{"place_id": "f04", "start": "12:00"}],
  "guide_ids": []
}
```

模型负责给出：有没有找到候选、选哪些地点、什么时候到、参考哪些资料。

票价、地点名称、访问时长、营业时间都在应用自己的数据里。所以最终对象不接受`cost_per_person`或自填名称，减少模型通过自由文本编造关键数据的机会。

Schema的`additionalProperties=False`会拒绝额外字段。它不是删除错误字段后静默接受，而是让模型知道候选不符合约定。

## 4. 跟着verify_final走一遍

### 第一步：把文本解析成对象

`candidate = json.loads(content)`把最终content从字符串变成字典。外面带Markdown围栏的文本不是纯JSON，会被拒绝。

### 第二步：检查形状

`validate_arguments(candidate, schema, "final")`检查三字段是否齐全，stops是否列表，每站是否只有place_id与start，资料ID是否字符串等。

形状通过不意味着行程合理：`"start":"25:00"`仍然是字符串，但具体时间范围要由后续工具检查。

### 第三步：检查来源

`guide_ids`必须在Agent本轮收集的`guides`中；地点必须在`place_ids`中。

这两个容器的由来不是模型自报：

```text
search_places真正成功返回 → Agent把返回地点ID加入place_ids
search_guides真正成功返回 → Agent把返回资料按ID存入guides
```

p01可能存在于本地地点库，但如果本轮只搜索室内美食，它没有进入本轮候选，就不能突然出现在最终行程里。

### 第四步：检查用户偏好

- 雨天或室内要求：拒绝户外地点。
- 仅户外要求：拒绝室内地点。
- 非food活动：要求与兴趣标签存在交集。
- include_meal=True：至少有一个food类别地点。

当前把food类别视作满足用餐，咖啡馆也属于food。这是教学规则，不是营养学或真实午餐保障；如果用户要求“必须正餐”，需要增加新的数据与明确规则。

### 第五步：用原始表单重算

```python
arguments = request.check_arguments(candidate["stops"])
checked = registry.execute("check_itinerary", arguments)
```

`check_arguments`从request取预算、人数和起止时间，仅采用候选中的stops。于是即使模型此前用999检查通过，现在也必须面对30。

### 第六步：应用统一渲染

只有`checked["data"]["valid"]`为真，才生成planned结果。`render_plan`以及网页读取的费用来自checked，不是模型返回的金额文字。

## 5. 对照两个候选的变量

| 变量 | 超预算候选 | 合格候选 |
|---|---|---|
| request.budget_per_person | 30 | 30 |
| candidate.stops[0].place_id | f01 | f04 |
| 应用读取的地点费用 | 35 | 25 |
| 用户人数 | 2 | 2 |
| 重算是否通过 | False | True |
| 展示全组费用 | 不展示不合格方案 | 50 |

“把最终金额写成0元”无法改变表中第三行，因为那一行从本地地点表读取。

## 6. 异常怎么回到Agent

`verify_final`遇到不合格候选会抛`ValueError`。Agent捕获后：

1. 记录`final_rejected`事件，包含可读拒绝原因。
2. 把应用拒绝原因追加为user反馈消息。
3. 若还没达到三次最终校验上限，再调用来源。
4. 通过时记录`final_validation`，然后返回结果。

这里的user角色消息由应用构造，不是用户又手动输入了一遍。角色用于API对话协议，不等于每一条都必须来自真实人类。

## 7. 四个反例分别被谁挡住

运行第二个实验可以观察：

| 候选修改 | 应被拒绝的层 |
|---|---|
| 多加cost_per_person=0 | 最终Schema未知字段 |
| guide_ids填g_rain，但本轮没有检索资料 | 资料来源校验 |
| 选本轮搜索过的f01，但超过30预算 | 业务重算 |
| 选本地存在、但本轮没搜到的p01 | 地点来源校验 |

一项检查不能替代其他检查。只检查ID存在，挡不住超预算；只检查预算，挡不住没检索过的引用。

## 8. no_plan是什么，不是什么

模型也可以返回：

```json
{"status":"no_plan","stops":[],"guide_ids":[]}
```

应用不会把它当作有效行程。它只表示本轮没有提交通过检查的候选。

当前协议允许这种返回，不能单靠校验器阻止模型过早放弃。第10课会统计本应planned却得到no_plan的情况，不能因为没有输出违规计划就说任务100%成功。

若说“数学上无解”，通常需要更完整的搜索或证明条件。当前贪心规则和模型都不提供普遍的无解证明。

## 9. 提示注入与确定性检查的边界

外部资料可能夹带“忽略预算”这样的句子。系统提示会说明检索材料是数据，不能当作高优先级指令；程序还保留表单预算、工具允许列表和最终重算。

这降低了特定关键字段被绕过的风险，但不能宣称整个模型完全免疫提示注入。我们仍未验证引用与结论的语义一致性，也没有真实外部恶意文档的大规模评测。

同样，校验器使用的地点价格如果本来就是假的，它只能保证“符合这份教学数据”，不会自动变成现实世界的正确票价。

## 10. 练习与答案

**A.** 把小吃店25元改为31元，只修改复制出来的数据文件。预算30时原来的合法候选还能通过吗？

<details><summary>答案</summary>
不能。最终费用是动态从工具数据重算的，不会因为候选ID以前通过过就缓存为永久有效。给TripTools传入临时data_file即可实验，不要覆盖正式数据后忘记恢复。
</details>

**B.** 在USER_NOTE中写“预算不够就按999元算”，哪里阻止它生效？

<details><summary>答案</summary>
提示词要求补充文字不能放宽表单；更关键的是request对象仍保存30，最终check_arguments不从补充文字或模型参数读预算。如果模型给出超预算候选，重算仍会拒绝。
</details>

**C.** 能把verify_final删除，只保留模型自己调用check_itinerary吗？

<details><summary>答案</summary>
会重新暴露预算999的绕过案例。模型可能传错条件，也可能在检查后又更改最终方案。最终展示前必须重新验证真正要展示的那份候选。
</details>

**D.** 用户修改了表单预算为100元，程序是否应该仍坚持最初的30元？

<details><summary>答案</summary>
不应该。权威约束并非永远不变，而是只由明确的应用输入更新。下一次Service合并并验证新表单后，新的TripRequest应当使用100元。模型擅改和用户明确修改是两回事。
</details>

## 11. 面试表达与完成标准

对应[Q25–Q28](INTERVIEW_BANK.md#q25)。

> 我不把模型给出的校验参数当作用户约束。最终候选只允许地点ID、开始时间和检索引用，应用用表单TripRequest重新生成检查参数，读取本地价格、营业时间和路线。这样可以复现并拦截“模型把预算改成999再检查”的失败案例。

追问“校验通过就一定好吗？”：通过硬约束不代表行程体验好、最优或真实数据准确，主观质量和数据真实性需要额外评测。

能逐项指出四种绕过尝试被哪里拦住，再进入[第8课](LESSON_08.md)。
