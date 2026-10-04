# 第8课：会话、数据库和模型上下文，分别记住了什么

本课建议拆成两次学习：先理解保存与恢复，再理解历史裁剪和并发。前置知识是字典合并、消息列表、函数调用。

## 1. 一个真实使用场景

第一轮你填3个人、预算200元。第二轮只说“下雨了，预算改80”。我们希望人数仍为3；关掉程序重新打开后，还能恢复最近完成的安排。

这里至少有三种状态，不能混成一句“大模型有记忆”：

| 状态 | 存放位置 | 作用 |
|---|---|---|
| 结构化条件request | SQLite及本轮TripRequest对象 | 明确人数、预算、时间 |
| 完整已完成历史 | SQLite的messages字段 | 恢复、追踪和保留记录 |
| 本次模型上下文 | agent.messages列表 | 这次真正发给模型的消息 |

数据库里存着，不代表模型这次全都看得到。反过来，本次临时加入的消息如果运行失败，也未必已经保存到数据库。

## 2. 文件与实验入口

- [memory.py](../src/weekend_agent/memory.py)：SessionStore与select_context。
- [service.py](../src/weekend_agent/service.py)：恢复、合并、执行、保存的总流程。
- [基本恢复实验](../examples/lesson08/01_session_memory.py)：模拟重启后保留人数。
- [上下文实验](../examples/lesson08/02_context_window.py)：五轮历史与最近两轮比较。

```bash
python3 examples/lesson08/01_session_memory.py
python3 examples/lesson08/02_context_window.py
```

两个脚本使用临时数据库，结束后清理，不覆盖网页中自己的行程记录。正式运行保存在被Git忽略的`outputs/sessions.sqlite3`。

## 3. SQLite表里的字段是什么

| 字段 | 含义 | 示例 |
|---|---|---|
| id | 随机会话标识 | uuid生成的32字符字符串 |
| mode | 离线还是模型模式 | demo或live |
| messages | 完整已完成消息，JSON文本 | system、user、assistant、tool列表 |
| request | 最近完成的权威条件，JSON文本 | group_size为3 |
| result | 最近完成的展示与统计结果 | 行程、调用数、token用量 |
| version | 成功保存次数对应的版本 | 0→1→2 |
| updated_at | 最近写入时间 | 数据库生成 |

SQLite只负责保存值，不会理解这些JSON里的旅行含义。`json.dumps`负责把对象转文本，`json.loads`负责取出时转回对象。

随机session_id也不是生产级账号鉴权。本项目服务只供本机使用，没有用户账号权限系统。

## 4. 第一轮的生命周期

```text
验证新表单
 → create(mode)插入空会话，version=0
 → load读取会话
 → 组装TripRequest、工具与来源
 → Agent完成并通过最终校验
 → save更新messages/request/result，version=1
```

create不是完成一次规划。它只是分配一个存储位置，只有成功save之后才有完成结果。

## 5. 第二轮为什么保留3个人

核心代码是：

```python
merged = {**saved["request"], **values}
request = TripRequest.from_dict(merged)
```

假设旧值：

```python
saved_request = {"group_size": 3, "budget_per_person": 200, "rain": False}
values = {"budget_per_person": 80, "rain": True}
```

`**`先展开旧字典，再展开新字典。同名键以右边为准；没有出现在右边的键保留旧值。结果为：

```python
{"group_size": 3, "budget_per_person": 80, "rain": True}
```

随后必须对合并后的整体重新验证。比如旧结束时间22:00，新开始时间19:00，如果错误地先按默认结束时间18:00验证新字段，就会拒绝本来合法的修改。这也是现有回归测试覆盖的例子。

网页通常发送完整表单，CLI也可发送完整条件；Service支持部分更新，因此自身仍要正确实现合并。

## 6. 新对象为什么还能恢复旧会话

对象只是内存里的实例，SQLite文件才是持久存储：

```python
first = PlanningService(database).plan({"group_size": 3})
service = PlanningService(database)  # 新对象
second = service.plan({"rain": True}, session_id=first["session_id"])
```

只要数据库路径和session_id相同，第二个对象就能load到旧记录。这不是Python对象穿越了重启，也不是模型在服务商那里自动记住了你。

如果新建另一个session_id，它有自己的request和messages，不应继承前一个会话的3人条件。

## 7. 为什么不直接取messages[-10:]

第4课的消息必须配对。如果倒着切最后10条，第一条可能是tool结果，而触发它的assistant工具请求已经被切掉。

本项目按完整用户回合切：找`role=user`且内容以`STRUCTURED_REQUEST:`开头的位置。这个标记代表一条新的结构化用户请求；最终校验失败时追加的user反馈不算新回合。

```python
starts = [i for i, message in enumerate(messages)
          if message["role"] == "user"
          and message["content"].startswith("STRUCTURED_REQUEST:\n")]
```

`enumerate`同时提供位置i和消息对象。`starts[-max_turns:]`选最近若干个回合起点，再从最早被保留的起点一直取到结束。

system消息单独保留，因此新上下文是：`system + 最近完整回合`。

## 8. 用五轮实验理解长度变化

当前默认规则方案每个已完成回合增加15条消息，初始system占1条。运行示例可得到：

| 完成回合 | 数据库version | 完整历史条数 | 本轮执行前保留的旧上下文条数 |
|---|---:|---:|---:|
| 1 | 1 | 16 | 1 |
| 2 | 2 | 31 | 16 |
| 3 | 3 | 46 | 31 |
| 4 | 4 | 61 | 46 |
| 5 | 5 | 76 | 46 |

第五轮开始前，完整旧历史有61条，但最多保留最近三个完整旧回合：`1 + 3×15 = 46`。新用户消息是在随后run时追加的。

“每回合15条”是当前这组离线输入的结果，不是协议固定长度。不同工具数量、最终修复次数、真实模型决策都会改变消息数。

## 9. retained为什么重要

假设完整旧历史61条，本轮选出的旧上下文46条：

```python
prior = saved["messages"]          # 完整61条
agent.messages = select_context(prior)  # 保留46条
retained = len(agent.messages)     # 46
run = agent.run(question, request) # 后面追加本轮新消息
history = prior + agent.messages[retained:]
```

切片`[retained:]`只取本轮新增消息，再接回完整旧历史。若错误地直接保存`agent.messages`，数据库里被裁掉的历史就真的丢了，下一次无法恢复。

所以“裁模型上下文”和“删数据库历史”要分别处理。当前程序只做前者。

## 10. 字符上限和token上限不是同一个概念

`select_context`默认限制序列化后的40,000个字符。超限时继续删除最旧完整回合；若最近一个完整回合仍过长，就明确要求新会话。

这是简化的保护措施，不是精准token预算。中文、英文、数字和模型分词方法会影响token数。当前也没有摘要器，所以不能说“实现了长期记忆压缩”。

API返回的usage能说明已处理请求的token量，但不能代替发送之前的精准tokenizer估算。

## 11. 锁、版本和事务解决什么问题

| 机制 | 解决的问题 | 不解决的问题 |
|---|---|---|
| 同会话Lock | 同一服务进程里同会话同时生成 | 多进程共享锁 |
| BoundedSemaphore(2) | 同时最多两个规划任务 | API供应商的完整限流策略 |
| version条件更新 | 旧版本覆盖新版本 | 自动合并两个不同结果 |
| SQLite事务 | 一次保存的写入一致性 | 中途模型工具步骤恢复 |

版本更新的条件类似：

```sql
UPDATE sessions SET ..., version=version+1
WHERE id=? AND version=?
```

你加载时version=1，另一个请求已保存到2，你再按1更新就影响0行。程序检测rowcount并报错，而不是静默覆盖。

`with connection`用于事务提交/回滚，但不等于自动关闭连接。项目的contextmanager在finally显式close，避免持续运行时泄漏连接。

## 12. 和DeepSeek接入的关系

当前官方DeepSeek请求固定关闭thinking。模型返回的`reasoning_content`可以在本次内存协议里保留，但不会写入学习历史。

如果将来开启thinking，必须先解决跨回合工具历史中该字段的回传要求，再谈重启恢复。不能仅修改一个开关就宣称思考模式的多轮记忆已兼容。详见[第11课](LESSON_11.md)。

## 13. 练习与答案

**A.** 第二轮显式传group_size=5，会继续保留3吗？

<details><summary>答案</summary>
不会。右侧values覆盖同名键，新的权威人数为5。只有未提供的字段才保留。
</details>

**B.** 如果把完整历史保存成agent.messages，会丢什么？

<details><summary>答案</summary>
被select_context裁掉的旧回合会从数据库消失。正确保存方式是完整prior加本轮新增部分，不是“本次发送给模型的全部内容”。
</details>

**C.** 直接取最后两条消息为什么危险？

<details><summary>答案</summary>
本例最后两条是tool和assistant，缺少触发tool的assistant调用请求，也缺system及用户条件。实验会打印角色，不能只看文本似乎有用就直接发送。
</details>

**D.** 规划中途失败，能从最后一次工具节点恢复吗？

<details><summary>答案</summary>
当前不能。只保存成功完成的回合，失败不会覆盖之前完成结果；没有节点检查点。把数据库持久化等同于任意中途恢复，是面试中容易被追问出来的错误。
</details>

## 14. 面试表达与完成标准

对应[Q29–Q32](INTERVIEW_BANK.md#q29)，连接[Q52](INTERVIEW_BANK.md#q52)。

> 我把结构化条件、完整持久历史和模型上下文分开管理。SQLite保存完成回合，部分更新先合并旧条件再验证；模型只取最近三个完整回合，避免截断工具配对。保存时用完整历史加本轮新增消息，同会话锁与版本条件更新避免覆盖。

能解释五轮表格，能画出prior、retained、history的关系，再进入[第9课](LESSON_09.md)。
