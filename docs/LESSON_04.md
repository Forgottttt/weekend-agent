# 第4课 工具调用消息：请求和结果怎样配对

日期：2026-10-04。本课材料已生成，不代表用户已经掌握。

## 本课目标

只做一个天气工具请求，并把执行结果正确写回消息历史。不先加入循环，先看清三条消息。

## 文件和运行入口

`providers.py` 的 `tool_call`；`tools.py` 的注册表；`agent.py` 的消息追加。

```bash
cd /path/to/weekend-agent  # 替换为你自己的项目目录
python3 examples/lesson04/01_message_protocol.py
```

配套脚本有中文注释，复用实际业务模块。先运行，再按下面顺序跟踪。

## 输入

用户消息“查教学天气”；工具名get_weather，城市杭州，日期2026-11-21，调用ID weather_001。

## 按执行顺序理解

### 1. 用户消息

messages先是一个列表，里面只有role=user的字典。role表示这条消息在对话协议中的身份。

### 2. 工具请求

tool_call创建id、type、function。function中name是工具名，arguments是JSON字符串。它本身不会执行天气查询。

### 3. 助手消息

把请求放进role=assistant的tool_calls列表。content=None很正常，因为这一轮主要请求工具，而不是输出最终文字。

### 4. 执行请求

json.loads拿到参数字典，registry.execute检查并运行，得到ok/data结果。这是本地应用执行，不是模型执行。

### 5. 工具结果

追加role=tool消息，其tool_call_id必须等于weather_001，content是json.dumps后的结果。下一次模型请求要带上前面的请求和对应结果。

### 6. 协议与业务

ok=true只表示函数运行成功；天气仍是教学天气，不能把它当作真实天气。ID或字段损坏属于协议问题，不等于普通业务参数错误。

## 关键代码

```python
messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
result = registry.execute(name, json.loads(raw))
messages.append({"role": "tool", "tool_call_id": call["id"],
                 "content": json.dumps(result, ensure_ascii=False)})
```

代码片段用于定位核心逻辑，不要求替换整个业务文件。完整实现以项目文件为准。

## 预期结果

打印user、assistant、tool三条消息；最后“请求ID和结果ID相同”是True。没有网络请求或真实模型。

## 自己做一个改动

把call的id从weather_001改成另一个名字。结果仍能自动配对。然后故意在最后一条消息写一个不同ID，观察比较变False，解释这为什么不能发给真实模型。

## 本课面试训练

先不看答案，用自己的话回答；参考思路和追问见 [题库](INTERVIEW_BANK.md)。

- [Q13](INTERVIEW_BANK.md#q13)：assistant 的 tool_calls 与 tool 消息如何配对？
- [Q14](INTERVIEW_BANK.md#q14)：为什么工具结果常常还要 json.dumps？
- [Q15](INTERVIEW_BANK.md#q15)：工具参数不是有效 JSON 时怎样处理？
- [Q16](INTERVIEW_BANK.md#q16)：同一轮多个 tool_calls 是否等于并行执行？

## 验收

能指出工具说明、工具请求和工具结果是三种不同的数据；能解释为什么多个调用要分别返回结果。

## 当前边界

本课只模拟协议片段；完整模型响应解析、异常调用ID和循环上限在下一课理解。
