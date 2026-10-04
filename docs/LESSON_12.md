# 第12课 面试训练：从解释到现场修改

日期：2026-10-04。本课材料已生成，不代表用户已经掌握。

## 本课目标

把项目知识变成能独立解释、举反例、改代码并承认边界的面试回答。生成代码不等于你已掌握全部代码。

## 文件和运行入口

`interview.py`；`data/interview.json`；`docs/INTERVIEW_BANK.md`、`INTERVIEW_TRAINING.md`与`RESUME.md`。

```bash
cd /path/to/weekend-agent  # 替换为你自己的项目目录
python3 examples/lesson12/01_mock_interview.py --list
```

配套脚本有中文注释，复用实际业务模块。先运行，再按下面顺序跟踪。

## 输入

54道训练题来自近期中文面经主题与本项目设计，答案是项目相关参考思路，不是任何公司的官方标准答案。

## 按执行顺序理解

### 1. 先作答

不要先看参考答案。60–90秒讲结论、流程、代码例子和限制；终端输入只是一种记录方式，重点是你能口头说明。

### 2. 找证据

每题打开evidence指向的函数或测试。看懂类与对象关系，能跟踪变量，不能只说“框架自动做的”。

### 3. 回答追问

说明为什么选这种设计、什么时候失效、怎么证明。不要把尚未接入的LangGraph、向量数据库、MCP或LLM微调说成已实现。

### 4. 现场修改

优先做每人预算改全组预算、返回来源ID检查、上下文截断反例、增加评测场景四项。先预测影响，再修改运行并解释。

### 5. 自评

0不会；1会背；2能结合代码解释；3能改代码并说明限制。评分由你完成，不是自动能力评估；课程也不会因脚本跑通就被标记已掌握。

### 6. 真实履历

AI协助生成初始代码如实说明。百度经历只讲已确认的YOLO视觉微调与陶瓷、管道缺陷检测；具体数据和指标需你回忆确认，不能编造。

## 关键代码

```bash
python3 main.py --practice --topic tools --count 3
python3 main.py --practice --topic rag --count 3
python3 main.py --practice --topic project --count 3
```

代码片段用于定位核心逻辑，不要求替换整个业务文件。完整实现以项目文件为准。

## 预期结果

--list只列题目，无该参数进入交互。每题先回答，再展示思路、证据和追问，最后自评；记录保存到outputs/practice。

## 自己做一个改动

录一段90秒项目介绍，删掉自己无法打开代码证明的术语。然后做“模型把预算改999”的追问，最后现场新增一条失败回归测试。

## 本课面试训练

先不看答案，用自己的话回答；参考思路和追问见 [题库](INTERVIEW_BANK.md)。

- [Q45](INTERVIEW_BANK.md#q45)：请用90秒介绍这个项目。
- [Q46](INTERVIEW_BANK.md#q46)：这个项目的代码有多少是AI生成的，你自己的贡献是什么？
- [Q47](INTERVIEW_BANK.md#q47)：从视觉算法实习转向Agent，怎样解释自己的优势和不足？
- [Q48](INTERVIEW_BANK.md#q48)：如果再给你两周，会优先改进什么？
- [Q49](INTERVIEW_BANK.md#q49)：MCP与Function Calling是什么关系？
- [Q50](INTERVIEW_BANK.md#q50)：LangGraph的State、Node、Edge会怎样对应本项目？
- [Q51](INTERVIEW_BANK.md#q51)：Transformer的注意力在做什么？
- [Q52](INTERVIEW_BANK.md#q52)：SQLite事务上下文为什么仍需要显式关闭连接？
- [Q53](INTERVIEW_BANK.md#q53)：面试要求手写一个简化工具注册表，你会怎样组织？
- [Q54](INTERVIEW_BANK.md#q54)：如何从大量线上日志整理有限评测集？

## 验收

能讲一个亲自理解并修改过的失败案例；能坦诚区分AI生成、自己修改、未实测、未实现四种状态。

## 当前边界

题库是准备材料，不保证覆盖每家公司；算法、Python、SQL与模型基础还需要独立训练。
