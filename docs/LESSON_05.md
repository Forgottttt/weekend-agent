# 第5课 Agent循环：用结果决定下一步

日期：2026-10-04。本课材料已生成，不代表用户已经掌握。

## 本课目标

读懂一次模型来源请求→工具执行→结果回传→再请求的循环，并能让循环按上限退出。

## 文件和运行入口

`agent.py`；`planning.py`；`providers.py` 的ChatProvider接口；`prompts.py`。

```bash
cd /path/to/weekend-agent  # 替换为你自己的项目目录
python3 examples/lesson05/01_agent_loop.py
```

配套脚本有中文注释，复用实际业务模块。先运行，再按下面顺序跟踪。

## 输入

默认表单：杭州、两人、每人200、拍照和美食、10:00–18:00、要求用餐。脚本使用DayDemoProvider规则来源。

## 按执行顺序理解

### 1. 构造对象

TripRequest保存权威条件；TripTools保存地点；ToolRegistry管理说明和执行；DayDemoProvider提供模拟assistant消息；TripAgent把这些对象接在一起。

### 2. 构造本轮消息

Agent先追加STRUCTURED_REQUEST的JSON和USER_NOTE。模型模式可以读取它们，离线来源只根据固定规则和工具结果行动。

### 3. 循环一次

provider.complete拿到消息和说明。存在tool_calls就执行每一个，追加tool结果，再继续循环；没有tool_calls时尝试最终结果处理。

### 4. 离线步骤

规则来源依次查天气、地点、资料，构造候选行程，再请求相邻路线和行程检查。它可以按表单变化生成不同方案，但仍然不是自由文本理解或大模型决策。

### 5. 计数

provider_calls按来源调用轮数计；tool_calls按模型协议里的工具请求计。一轮可以包含多个请求。最终应用重算单独计final_checks，内部纯函数计算不是模型工具请求。

### 6. 终止与护栏

max_rounds限制来源请求轮数；max_tool_calls限制工具请求数；最终结果失败最多检查三次。超限明确报错，不能继续无限修复。

## 关键代码

```python
for round_index in range(1, self.max_rounds + 1):
    message = self.provider.complete(self.messages, self.registry.schemas)
    calls = message.get("tool_calls") or []
    if not calls:
        # 处理并校验最终方案
        ...
    for call in calls:
        # 执行工具并追加结果
        ...
```

代码片段用于定位核心逻辑，不要求替换整个业务文件。完整实现以项目文件为准。

## 预期结果

打印工具顺序和通过最终校验的多站计划，真实模型请求显示0。当前默认规则结果每人53元，但修改排序或地点数据后该数字会变化。

## 自己做一个改动

只把max_rounds改成2，解释为什么无法得到最终结果；恢复后把max_tool_calls改成1，定位上限检查在执行下一批工具之前。

## 本课面试训练

先不看答案，用自己的话回答；参考思路和追问见 [题库](INTERVIEW_BANK.md)。

- [Q17](INTERVIEW_BANK.md#q17)：你的项目中 Workflow 和 Agent 的区别体现在哪里？
- [Q18](INTERVIEW_BANK.md#q18)：怎么防止工具调用死循环？
- [Q19](INTERVIEW_BANK.md#q19)：为什么单 Agent，不拆成多个 Agent？
- [Q20](INTERVIEW_BANK.md#q20)：为什么没有直接用 LangGraph？以后如何迁移？

## 验收

能从日志复述每一轮的输入和输出；能区分规则workflow与live模型选择工具；不把ReAct当作某个库的专属功能。

## 当前边界

这里是单Agent和同步工具执行。当前没有LangGraph、多Agent、并行工具或中间节点检查点恢复。
