# 周末去哪玩

一个可运行、可逐课学习的城市行程Agent项目：表单输入→工具调用→资料检索→最终约束校验→网页展示→会话保存。

Python 3.11以上，只用标准库，不需要安装第三方运行依赖。项目版本0.2.0。**全部地点、天气、费用、路线和资料均为虚构教学数据。真实模型适配器已准备，当前尚未完成真实API调用及效果评测。**

## 打开网页

```bash
cd /path/to/weekend-agent  # 替换为你自己的项目目录
python3 main.py --serve
```

打开 [本地演示](http://127.0.0.1:8765)。可修改预算、人数、时间、兴趣、雨天、室内外和用餐要求；刷新恢复最近完成结果。切换离线/模型模式时新建会话。

离线演示只理解表单条件，不理解自由文本，使用贪心规则流程。真实模型模式可以处理补充文本，但权威表单约束仍由应用控制；修改预算请明确改表单，不能仅在补充文本里放宽条件。

## 命令行演示

```bash
python3 main.py --demo
python3 main.py --demo --rain --budget 80
python3 main.py --demo --budget 20
python3 main.py --demo --budget 0 --no-meal
python3 main.py --demo --chat
```

交互中`/budget 80`修改预算，`/rain`切换教学雨天，`exit`退出。demo不理解其他自然语言修改。`--session 会话ID`恢复保存的会话，条件从保存记录读取。

默认规则规划得到多站安排，不强制填满所有时间；低预算且要求用餐时可返回未找到候选。费用仅含地点和相邻交通，不含往返起点及其他消费。没找到方案不等于证明无解。

早期两站固定示例仍可用`python3 main.py --legacy-demo`查看，晴天每人37元、雨天57元，便于对照第一版教材。默认`--demo`已换成多站版本。

## 十二课与面试训练

从 [统一课程入口](docs/LEARNING.md)开始。每课都有具体文件、可运行脚本、执行过程、变量变化、改动练习和面试问题。

| 课次 | 内容 |
|---|---|
| 1 | 字典、列表、JSON与地点筛选 |
| 2 | Schema、参数检查与工具注册 |
| 3 | 预算、交通和营业时间 |
| 4 | assistant/tool消息与调用ID |
| 5 | Agent循环、规则基线和终止条件 |
| 6 | BM25资料检索与RAG边界 |
| 7 | 权威约束与最终结果重算 |
| 8 | SQLite持久化与近期上下文 |
| 9 | 网页、HTTP、错误与并发 |
| 10 | 固定回归、指标与弱基线 |
| 11 | 真实模型适配、重试和usage |
| 12 | 项目介绍、追问、现场修改 |

[54题面试题库](docs/INTERVIEW_BANK.md) · [训练计划](docs/INTERVIEW_TRAINING.md) · [中文面经调研](docs/RESEARCH.md) · [简历表述](docs/RESUME.md)。

```bash
python3 main.py --practice --topic tools --count 3
python3 main.py --practice --topic rag --count 3
python3 main.py --practice --topic project --count 3
```

先作答，再展示参考思路、代码证据与追问，最后自评；保存到outputs/practice。自评分不是自动能力评估，代码生成也不表示用户已掌握。

## 验证与评测

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 main.py --evaluate
```

测试包含业务约束、协议错误、最终预算绕过、伪造引用、会话恢复、上下文配对、并发与本地HTTP。12例固定评测是开发期离线回归，demo真实模型调用为0；不能称为真实模型成功率。报告在outputs/eval_*.json，另有较弱的硬编码行程基线。

## 接入自己的模型

兼容Chat Completions工具调用协议的接口可通过环境变量配置。macOS默认zsh中输入密钥不回显：

```bash
read -s "LLM_API_KEY?请输入自己的模型API密钥："
export LLM_API_KEY
export LLM_BASE_URL='https://api.deepseek.com'
export LLM_MODEL='deepseek-flash'
python3 main.py --live --question '请按表单规划，优先拍照。'
```

模型名依据2026-10-03检索的 [DeepSeek官方文档](https://api-docs.deepseek.com/api/create-chat-completion/)，可自行改为所用服务支持的模型。`.env.example`只是说明，不自动加载。DeepSeek默认使用非thinking模式；接口对429、5xx或连接超时最多重试一次。其他服务差异需要实测。

先验证单条调用，再考虑`--evaluate --live`批量调用；真实API可能收费。网页模型模式也需要在启动服务的终端配置环境变量。旅行数据仍为教学数据。

## 核心文件

```text
src/weekend_agent/
  request.py       表单权威条件
  tools.py         五个工具、Schema与参数校验
  retrieval.py     字符二元组BM25
  providers.py     模型API适配与早期固定演示
  planning.py      多站离线规则流程
  agent.py         消息循环与调用护栏
  finalize.py      最终方案校验与应用渲染
  memory.py        SQLite与上下文选择
  service.py       会话和业务组装
  server.py        仅本机HTTP服务
  evaluation.py   固定回归与弱基线
  interview.py    面试练习
  web/            HTML、CSS、JavaScript
  data/           虚构地点、资料、用例和题库
examples/lesson01–lesson12/ 课程实验
docs/                      逐课教材与求职材料
tests/                     业务、协议和集成测试
```

完整设计与取舍见 [ARCHITECTURE.md](docs/ARCHITECTURE.md)，当前验证状态见 [STATUS.md](docs/STATUS.md)。

当前没有LangGraph、MCP服务、embedding、向量库、真实地图、LLM微调、线上用户或公网部署。作为简历项目，应在理解、亲自修改和真实API验证后按实际结果表述。
