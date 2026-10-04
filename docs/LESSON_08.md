# 第8课 会话记忆：存下来与放进上下文

日期：2026-10-04。本课材料已生成，不代表用户已经掌握。

## 本课目标

完成一次修改预算和天气的重排，保留原来人数；模拟服务重启后仍能恢复，理解完整历史与模型上下文的区别。

## 文件和运行入口

`memory.py`；`service.py`；SQLite的sessions表。

```bash
cd /path/to/weekend-agent  # 替换为你自己的项目目录
python3 examples/lesson08/01_session_memory.py
```

配套脚本有中文注释，复用实际业务模块。先运行，再按下面顺序跟踪。

## 输入

第一轮3人；第二轮只修改雨天和预算80。使用同一个数据库路径和session_id。教学脚本数据库在临时目录，结束后自动清理；正式网页用outputs/sessions.sqlite3。

## 按执行顺序理解

### 1. 首次创建

生成随机会话ID，在sessions保存模式、消息、request、结果和version。没有模型密钥字段。

### 2. 重启恢复

新PlanningService对象仍读取同一SQLite。session_id指向原记录，不能用其他会话的人数。

### 3. 合并条件

先取旧request，再用新字段覆盖；未提供的group_size仍是3。合并后重新验证时间、预算和类型。

### 4. 选上下文

select_context保留system及最近完整结构化回合，不按随意消息条数切割。检查字符上限，单回合超限会明确报错；没有实现摘要压缩。

### 5. 保存完整历史

retained记录进入本轮之前的上下文消息数。保存时把旧完整历史加本轮新增消息，而不是把截断后的上下文当成全部历史覆盖。

### 6. 事务与并发

version防止旧数据覆盖新数据，会话锁阻止同一会话同时规划；with connection管理事务，finally close释放连接，两者不是同一件事。

## 关键代码

```python
request = TripRequest.from_dict({**saved["request"], **values})
agent.messages = select_context(saved["messages"])
retained = len(agent.messages)
run = agent.run(question, request)
history = prior + agent.messages[retained:]
store.save(session_id, history, request.to_dict(), result, version)
```

代码片段用于定位核心逻辑，不要求替换整个业务文件。完整实现以项目文件为准。

## 预期结果

人数保持3，预算变80，rain变True；version为2；只取最近1回合的消息数小于完整历史。

## 自己做一个改动

第二轮增加group_size=5，观察这个字段才被覆盖；再新建一个会话，解释为什么它不继承3人。观察select_context中每个tool结果是否仍有前面的请求。

## 本课面试训练

先不看答案，用自己的话回答；参考思路和追问见 [题库](INTERVIEW_BANK.md)。

- [Q29](INTERVIEW_BANK.md#q29)：长期存储和模型上下文是一回事吗？
- [Q30](INTERVIEW_BANK.md#q30)：为什么不能把所有消息直接截到最后十条？
- [Q31](INTERVIEW_BANK.md#q31)：修改预算时怎样避免丢掉人数和日期？
- [Q32](INTERVIEW_BANK.md#q32)：同一会话同时提交两个请求会发生什么？

## 验收

能区分存储、上下文、结构化条件三种状态；能说明截掉的历史仍在数据库里，但模型当前看不到。

## 当前边界

没有跨会话语义记忆、摘要器、过期清理或中间工具节点检查点。成功回合保存，失败请求不会覆盖已完成历史。
