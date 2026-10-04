# 周末去哪玩

一个可运行、可逐课学习的城市一日游 Agent：自然语言或表单输入 → 工具调用 → 资料检索 → 最终约束校验 → 网页展示 → 会话保存。

Python 3.11 以上，**只用标准库，零第三方运行依赖**，核心代码约 2200 行。

**全部地点、天气、费用、路线和资料均为虚构教学数据。**

## 真实模型实测结果

2026-10-04/05，DeepSeek `deepseek-flash`（V4.1-Flash），非思考模式。原始报告与调用 trace 见 [reports/](reports/README.md)。

| 套件 | 数据集 | 真实模型 | 离线规则基线 |
|---|---|---|---|
| Agent 回归 | 12 例固定场景 | **12/12**，中位 8.05 秒，**0/12 触发修复轮** | 12/12，约 1 毫秒 |
| 槽位抽取 | 20 例口语化输入 | **槽位准确率 96.0%** · **幻觉误填率 3.2%** · **追问触发正确率 95.0%** | 不适用（离线不调用模型） |
| 资料检索 | 201 篇语料 / 44 条标注查询 | BM25 **recall@5 67.0%** / MRR 0.706；TF-IDF 65.9% / 0.712 | 同（词法检索不依赖模型） |

单例平均约 6 次模型请求、每秒级延迟、空闲时段约 0.02 元。开发全过程（含反复调试）合计 622 次请求、约 2.77 元。

## 让模型真正承重的那一步：自然语言 → 结构化条件

表单能填的条件有限，真实用户只会说一句话：

```bash
python3 main.py --live --ask "这周六下午想带爸妈出去走走，人均一百五以内，最好能坐下吃个饭"
```

```text
从这句话抽取到的条件： {"travel_date": "2026-10-10", "budget_per_person": 150, "tags": ["散步"], "include_meal": true}
还需要你确认：同行人数。补充之后我再生成安排。
```

模型在这里做三件不可替代的事：**把相对日期换算成 ISO 日期**、**把口语整理成可校验的槽位**、
**对缺失的关键条件主动追问**而不是替用户假设。

安全边界与最终校验同源：模型只负责**提出候选值**，写入 `TripRequest` 之前一律经过与表单
**完全相同的校验器**，因此它无法放宽或伪造权威约束。网页上也可以点「解析这句话」，
解析结果会填进表单供你核对后再生成。

**幻觉误填率**是这一层最重要的指标——它衡量"用户没说的条件，模型有没有自己编一个"。
实测 3.2%（126 个未声明槽位里填错 4 个），因为模型会把"出去走走"推断成 `tags: ["散步"]`。

## 一次真实的自我修正

真实模型在雨天 80 元预算下的一次规划，完全依靠工具返回的结构化 `issues` 自行收敛，无人工干预：

| 轮次 | 模型提案 | `check_itinerary` 判定 |
|---|---|---|
| round 3 | 4 站，171 元 | ✗ 预算超出 171 > 80；✗ 交通时间不足 |
| round 5 | 4 站，126 元 | ✗ 预算超出 126 > 80 |
| round 6 | 2 站，**77 元** | ✓ 通过 |

完整 trace：[reports/2026-10-04_live_trace_self_correction.json](reports/2026-10-04_live_trace_self_correction.json)。

## 架构：一次请求经过五层

```text
网页 / CLI（表单 或 一句自然语言）
  ↓
extraction.py          模型抽取槽位 → 与表单同一套校验 → 缺失则追问
  ↓
PlanningService        会话锁 + 全局并发上限 + 权威约束合并
  ↓
TripAgent 循环         协议校验、轮数与调用上限、工具结果回灌
  ↕
ChatProvider           同一接口的两个实现：离线规则 | 真实模型
  ↓
ToolRegistry           5 个工具 + JSON Schema 参数校验（错误即数据）
  ↓
verify_final           用用户原始条件重算，模型说什么不算数
  ↓
SQLite + 网页 / CLI
```

四个关键设计：

- **两层校验**。`check_itinerary` 在规划途中给模型反馈；`verify_final` 是应用终审，永远用表单里的预算和时间重算，模型把参数改成 999 也无效。
- **用户级约束在构造时注入**。雨天和用餐要求都是 `TripTools(rain=..., include_meal=...)`，不是工具参数——**模型无法通过工具调用放宽约束**，Schema 会直接拒绝该字段。
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

网页可改预算、人数、时间、兴趣、雨天、室内外和用餐要求；可用一句话解析条件；刷新恢复最近完成结果；切换离线/模型模式会自动新建会话并保留表单条件。

离线演示只理解表单条件、不理解自由文本，使用贪心规则流程，可能漏掉可行解。`no_plan` 只表示没找到候选，不等于证明无解。费用仅含地点和相邻交通，不含往返起点及其他消费。

早期两站固定示例仍可用 `python3 main.py --legacy-demo` 查看，供第一版教材对照。

## 接入 DeepSeek

详细步骤与错误解释见 [第 11 课](docs/LESSON_11.md)。项目自动读取根目录 `.env`，进程环境变量优先。首次使用运行 `cp -n .env.example .env` 并填写 `LLM_API_KEY`。

```bash
python3 main.py --doctor       # 不联网，只检查脱敏配置状态
python3 main.py --check-api    # 两轮真实请求：工具调用与回传，会消耗额度
python3 main.py --live --rain --budget 80
python3 main.py --live --ask "两个人，11月21号，预算200，想拍照"
```

`ready=true` 只表示本地配置就绪，不代表认证成功。默认关闭 thinking，输出上限 4096、单次超时 60 秒、最多重试 1 次。

**注意 `.env` 每行必须完整换行。** 曾出现两行粘连导致 `LLM_BASE_URL` 被并入 key 值、请求返回 401 的情况；本项目按第一个 `=` 切分，不会自动纠正这类错误。

## 验证与评测

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v   # 76 项，全部使用内存模拟响应，不联网
python3 main.py --evaluate                                # 离线规则回归
python3 main.py --evaluate --live                         # 真实模型回归
python3 main.py --evaluate --suite extraction --live      # 槽位抽取
python3 main.py --evaluate --suite retrieval              # BM25 vs TF-IDF，不联网
python3 main.py --evaluate --suite all --live             # 全部套件
python3 scripts/build_corpus.py                           # 重新生成检索语料，固定种子、幂等
```

测试覆盖业务约束、协议错误、最终预算绕过、伪造引用、用餐约束、JSON 解析容错、槽位抽取边界、会话恢复、上下文配对、并发与本地 HTTP。报告写入 `outputs/`，已完成的真实报告固化在 [reports/](reports/README.md)。

## 已知边界

- 12 例回归是开发期小型集合、**不是盲测**；20 例抽取评测的标签由作者人工标注；检索语料与标签**都由脚本生成**，不是人工标注，因此 recall@5 与 MRR 只反映两种词法方法在合成数据上的相对表现。
- 检索是字符二元组 BM25，**没有 embedding 或向量库**。实测口语化近义词是词法检索的硬盲区（"胶卷" vs "胶片冲洗" 完全不重叠，top5 全为无关文档）。
- 不保证填满 10:00–18:00；不处理起终点导航、实际票价、订票、跨城市或跨午夜。
- 会话保存完整已完成回合，最近三个完整回合进入模型上下文，**没有摘要压缩**；同会话锁与全局双并发只在单进程内有效，不是分布式锁。
- 网页仅绑定 `127.0.0.1`，无账号鉴权，不应原样公开部署。密钥不进入浏览器、SQLite 或 trace。
- 当前**没有** LangGraph、MCP 服务、向量库、真实地图、多 Agent、工具并行编排、公网部署或线上用户。

### 两个已修复的缺陷（排查过程见 [reports/README.md](reports/README.md)）

1. **工具层给出假绿灯**：`check_itinerary` 曾不检查用餐要求而 `verify_final` 检查，两层口径不一致导致模型连续三次终审失败。修复为把 `include_meal` 与 `rain` 一样在构造时注入。
2. **最终输出不是干净 JSON**：模型会在 JSON 前加一段解释文字。第一次修复只剥了 Markdown 围栏（假设错误，把修复轮从 5/6 变成 6/6）；记录下被拒原文后才发现真因，改为提取第一个配平的 JSON 对象，修复轮降为 **0/6**。

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
  request.py        表单权威条件
  extraction.py     自然语言 → 槽位抽取（模型承重的一层）
  tools.py          五个工具、Schema 与参数校验
  retrieval.py      字符二元组 BM25
  retrieval_eval.py TF-IDF 余弦基线与 recall@k / MRR 评测
  jsonio.py         模型输出的容错 JSON 解析
  config.py         .env、环境变量及调用限制
  diagnostics.py    离线配置检查与两轮 API 连通测试
  providers.py      模型 API 适配与早期固定演示
  planning.py       多站离线规则流程
  agent.py          消息循环与调用护栏
  finalize.py       最终方案校验与应用渲染
  memory.py         SQLite 与上下文选择
  service.py        会话和业务组装
  server.py         仅本机 HTTP 服务
  evaluation.py     固定回归与弱基线
  extraction_eval.py 抽取准确率 / 幻觉误填率 / 追问正确率
  interview.py      面试练习
  web/              HTML、CSS、JavaScript
  data/             虚构地点、资料、用例和题库
scripts/build_corpus.py  确定性生成检索语料与标注查询
reports/           真实模型评测报告与调用 trace
examples/lesson01–lesson12/  课程实验（调用同一业务代码）
docs/              逐课教材与求职材料
tests/             业务、协议和集成测试（76 项）
```

完整设计与取舍见 [ARCHITECTURE.md](docs/ARCHITECTURE.md)，当前验证状态见 [STATUS.md](docs/STATUS.md)。
