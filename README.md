# 周末去哪玩

一个可运行、可逐课学习的城市一日游 Agent：表单输入 → 工具调用 → 资料检索 → 最终约束校验 → 网页展示 → 会话保存。

Python 3.11 以上，**只用标准库，零第三方运行依赖**，核心代码约 1400 行。

**全部地点、天气、费用、路线和资料均为虚构教学数据。** 真实模型适配器已接入 DeepSeek 官方 API 并完成实测，数据见下。

## 真实模型实测结果

2026-10-04，DeepSeek `deepseek-flash`（V4.1-Flash），非思考模式，12 例固定回归跑 3 次独立运行：

| 指标 | 真实模型（live） | 离线规则（demo） |
|---|---|---|
| 通过率 | **35/36 = 97.2%**（12/12、12/12、11/12）→ 修复后 12/12 | 12/12 |
| 单例中位耗时 | 7.7 秒 | 约 0.001 秒 |
| 单例模型请求 | 5.5 次 | 0 次 |
| 单例成本 | ≈ 0.022 元 | 0 元 |
| 触发过的重试 | 0 / 339 次请求 | — |
| 弱基线对照 | 基线仅 3/12 有效 | 同 |

原始报告与调用 trace 保存在 [reports/](reports/README.md)，未经修改；复现命令见下方"验证与评测"。

**真实评测跑出了模拟测试发现不了的方差**：第 3 次运行有 1 例失败，根因是工具层与终审层校验口径不一致（工具给出假绿灯）。该缺陷已修复并验证——修复后真实评测 12/12，原失败用例定向复测 6/6 正确。归因过程与剩余问题见 [reports/README.md](reports/README.md)。

## 一次真实的自我修正

真实模型在雨天 80 元预算下的一次规划，完全依靠工具返回的结构化 `issues` 自行收敛，无人工干预：

| 轮次 | 模型提案 | `check_itinerary` 判定 |
|---|---|---|
| round 3 | 4 站，171 元 | ✗ 预算超出 171 > 80；✗ 交通时间不足 |
| round 5 | 4 站，126 元 | ✗ 预算超出 126 > 80 |
| round 6 | 2 站，**77 元** | ✓ 通过 |

完整 trace：[reports/2026-10-04_live_trace_self_correction.json](reports/2026-10-04_live_trace_self_correction.json)。

## 架构：一次请求经过四层

```text
网页 / CLI
  ↓
PlanningService        会话锁 + 全局并发上限 + 权威约束合并
  ↓
TripAgent 循环        协议校验、轮数与调用上限、工具结果回灌
  ↕
ChatProvider           同一接口的两个实现：离线规则 | 真实模型
  ↓
ToolRegistry           5 个工具 + JSON Schema 参数校验（错误即数据）
  ↓
verify_final           用用户原始条件重算，模型说什么不算数
  ↓
SQLite + 网页 / CLI
```

三个关键设计：

- **两层校验**。`check_itinerary` 在规划途中给模型反馈；`verify_final` 是应用终审，永远用表单里的预算和时间重算，模型把参数改成 999 也无效。
- **证据白名单**。最终方案里的地点必须来自本轮 `search_places`，引用必须来自本轮 `search_guides`，伪造引用直接被拒。
- **错误即数据**。工具异常转成 `{"ok": false, "error": ...}` 回灌给模型，让它自我修正，而不是让循环崩溃。

模块职责与取舍见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 快速开始

```bash
python3 main.py --serve          # 打开 http://127.0.0.1:8765
python3 main.py --demo           # 命令行离线演示
python3 main.py --demo --rain --budget 80
python3 main.py --demo --budget 0 --no-meal
python3 main.py --demo --chat    # /budget 80 改预算，/rain 切雨天，exit 退出
```

网页可改预算、人数、时间、兴趣、雨天、室内外和用餐要求；刷新恢复最近完成结果；切换离线/模型模式会自动新建会话并保留表单条件。

离线演示只理解表单条件、不理解自由文本，使用贪心规则流程，可能漏掉可行解。`no_plan` 只表示没找到候选，不等于证明无解。费用仅含地点和相邻交通，不含往返起点及其他消费。

早期两站固定示例仍可用 `python3 main.py --legacy-demo` 查看（晴天每人 37 元、雨天 57 元），供第一版教材对照。

## 接入 DeepSeek

详细步骤与错误解释见 [第 11 课](docs/LESSON_11.md)。项目自动读取根目录 `.env`，进程环境变量优先。首次使用运行 `cp -n .env.example .env` 并填写 `LLM_API_KEY`；不要把真实密钥写进 `.env.example` 或聊天。

```bash
python3 main.py --doctor       # 不联网，只检查脱敏配置状态
python3 main.py --check-api    # 两轮真实请求：工具调用与回传，会消耗额度
python3 main.py --live --rain --budget 80
```

`ready=true` 只表示本地配置就绪，不代表认证成功。默认关闭 thinking，输出上限 4096、单次超时 60 秒、最多重试 1 次。截断响应会明确停止，401/402/429 等错误给出对应处理提示。

**注意 `.env` 每行必须完整换行。** 曾出现两行粘连导致 `LLM_BASE_URL` 被并入 key 值、请求返回 401 的情况；本项目按第一个 `=` 切分，不会自动纠正这类错误。

## 验证与评测

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v   # 58 项，全部使用内存模拟响应，不联网
python3 main.py --evaluate                                 # 离线规则回归
python3 main.py --evaluate --live                          # 真实模型回归，消耗额度
```

测试覆盖业务约束、协议错误、最终预算绕过、伪造引用、会话恢复、上下文配对、并发与本地 HTTP。报告写入 `outputs/eval_*.json`，已完成的真实报告固化在 [reports/](reports/README.md)。

12 例是开发期小型回归集，不是盲测；不能据此推断真实模型的泛化能力。失败任务也会计入请求数，usage 只含已收到的响应，响应丢失时账单可能高于观测用量。

## 已知缺陷与边界

**头号未修复问题**：模型常把最终 JSON 包在 Markdown 代码围栏里，导致 `json.loads` 失败，**几乎每次会话都白白多烧一轮完整上下文**（约 2–4 万输入 token）。修复循环能救回正确答案，所以不影响正确性，只影响成本；且抛给模型的是 Python 原文报错。可选修法：解析前剥离围栏并把错误包装成中文，或终局改用服务商的 JSON 输出模式。详见 [reports/README.md](reports/README.md)。

**已修复**：`check_itinerary` 曾不检查用餐要求而 `verify_final` 检查，两层口径不一致会给出假绿灯，导致模型连续三次终审失败并报错（即 97.2% 中的那一次失败）。修复方式是把 `include_meal` 与既有的 `rain` 一样作为用户级约束在构造工具时注入，模型无法通过工具参数放宽；终审的独立检查保留作为纵深防御。新增 2 条回归测试，修复后真实评测 12/12。

**其他边界**：

- 不保证填满 10:00–18:00；不处理起终点导航、实际票价、订票、跨城市或跨午夜。
- 离线规划是贪心规则，可能漏解。
- 检索是字符二元组 BM25 词法检索，语料只有 6 篇自编资料，**不是 embedding 或向量库**，不足以证明 RAG 效果。
- 会话保存完整已完成回合，最近三个完整回合进入模型上下文，**没有摘要压缩**；同会话锁与全局双并发只在单进程内有效，不是分布式锁。
- 网页仅绑定 `127.0.0.1`，无账号鉴权，不应原样公开部署。密钥不进入浏览器、SQLite 或 trace。
- 当前**没有** LangGraph、MCP 服务、向量库、真实地图、多 Agent、工具并行编排、公网部署或线上用户。

## 十二课与面试训练

从 [统一课程入口](docs/LEARNING.md) 开始。第三至十二课为完整精读讲义：前置知识、文件关系、逐步变量推演、错误反例、练习答案与面试追问。现有 25 个分课脚本。[学习记录](docs/STUDY_LOG.md) 留给你填写，不自动标记掌握。

| 课次 | 内容 |
|---|---|
| 1–3 | 数据与筛选、Schema 与工具注册、预算与交通 |
| 4–6 | 工具调用消息协议、Agent 循环与护栏、BM25 检索 |
| 7–9 | 权威约束与最终重算、SQLite 与上下文、网页与 HTTP |
| 10–12 | 评测与弱基线、真实模型接入、项目介绍与现场修改 |

[54 题面试题库](docs/INTERVIEW_BANK.md) · [训练计划](docs/INTERVIEW_TRAINING.md) · [中文面经调研](docs/RESEARCH.md) · [简历表述](docs/RESUME.md)。

```bash
python3 main.py --practice --topic tools --count 3
python3 main.py --practice --topic rag --count 3
python3 main.py --practice --topic project --count 3
```

先作答，再展示参考思路、代码证据与追问，最后自评；保存到 `outputs/practice`。自评分不是自动能力评估。

## 核心文件

```text
src/weekend_agent/
  request.py       表单权威条件
  tools.py         五个工具、Schema 与参数校验
  retrieval.py     字符二元组 BM25
  config.py        .env、环境变量及调用限制
  diagnostics.py   离线配置检查与两轮 API 连通测试
  providers.py     模型 API 适配与早期固定演示
  planning.py      多站离线规则流程
  agent.py         消息循环与调用护栏
  finalize.py      最终方案校验与应用渲染
  memory.py        SQLite 与上下文选择
  service.py       会话和业务组装
  server.py        仅本机 HTTP 服务
  evaluation.py    固定回归与弱基线
  interview.py     面试练习
  web/             HTML、CSS、JavaScript
  data/            虚构地点、资料、用例和题库
reports/           真实模型评测报告与调用 trace
examples/lesson01–lesson12/  课程实验（调用同一业务代码）
docs/              逐课教材与求职材料
tests/             业务、协议和集成测试
```

完整设计与取舍见 [ARCHITECTURE.md](docs/ARCHITECTURE.md)，当前验证状态见 [STATUS.md](docs/STATUS.md)。
仓库：[Forgottttt/weekend-agent](https://github.com/Forgottttt/weekend-agent)（私有）。
