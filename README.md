# 周末去哪玩

一个可运行、可逐课学习的城市一日游 Agent：自然语言或表单输入 → 工具调用 → 资料检索 → 最终约束校验 → 网页展示 → 会话保存。

Python 3.11 以上，**只用标准库，零第三方运行依赖**，核心代码约 2900 行。

**全部地点、天气、费用、路线和资料均为虚构教学数据。**

## 真实模型实测结果

2026-10-04/05，DeepSeek `deepseek-flash`（V4.1-Flash），非思考模式。原始报告与调用 trace 见 [reports/](reports/README.md)。

| 套件 | 数据集 | 真实模型 | 离线规则基线 |
|---|---|---|---|
| Agent 回归 | 12 例固定场景 | **12/12、12/12、12/12**；54–68 次请求；中位 6.6–7.5 秒 | 12/12，约 1 毫秒 |
| 槽位抽取 | 20 例口语化输入 | 准确率 **96.0%** · 幻觉误填率 **1.6%** · 追问正确率 **100%** | 不适用 |
| 引用评审 | 12 例方案引用 | 命中率 **70.4%** · 召回率 **95.0%** · 无关引用率 29.6% | 不适用 |
| 资料检索 | 201 篇 / 44 条标注查询 | BM25 recall@5 **67.0%** / MRR 0.706；TF-IDF 65.9% / 0.712 | 同（词法检索不依赖模型） |

三次 agent 回归**全部 0/12 触发修复轮、0/12 走文本兜底通道**——方案全部通过 `submit_plan` 工具提交。

## 最终交付走工具调用，不走文本

早期实现让模型把方案作为**普通文本**输出，应用再解析。真实评测显示这条路很脆：模型会把 JSON 包进 Markdown 围栏，或在 JSON 前面加一段解释文字，导致解析失败并多烧一轮完整上下文。第一次修复基于错误假设（以为只是围栏问题），只剥离围栏，**结果把同用例的修复轮从 5/6 改成了 6/6**；记录下被拒原文后才发现真因。完整排查过程见 [reports/README.md](reports/README.md)。

现在改为 `submit_plan` 工具调用：`arguments` 由接口保证是合法 JSON，**格式问题在结构上就不存在**。文本解析只作为兜底保留，是否被使用记录在 `RunResult.submitted_via` 上，可以直接度量——实测 0/12。

代价是终止条件变了（不再是"模型不再调用工具"），以及一个容易踩的坑：提交成功后必须给同批次里**所有** `tool_call` 补上配对结果，否则下一轮接口会直接拒绝。测试里有一条专门锁住这个行为。

## 让模型真正承重的那一步：自然语言 → 结构化条件（支持多轮追问）

```bash
python3 main.py --live --ask "这周六下午想带爸妈出去走走，人均一百五以内，最好能坐下吃个饭"
```

```text
还需要你确认：同行人数。补充之后我再生成安排。
你的补充： 一共三个人
从这句话抽取到的条件： {"travel_date": "2026-10-10", "budget_per_person": 150, "group_size": 3, "tags": ["散步"], "include_meal": true}
经过 1 轮补充后条件已齐全。
已合并进表单条件，开始规划。
10:00–11:00 示例河边步道
11:15–12:15 示例面馆
...
每人 86 元，全组 258 元。
```

模型在这里做三件不可替代的事：**把相对日期换算成 ISO 日期**、**把口语整理成可校验的槽位**、**对缺失的关键条件主动追问**。追问循环会把用户每次补充**并回完整描述**再重新抽取，模型始终看到全部上下文。

安全边界与终审同源：模型只负责**提出候选值**，写入 `TripRequest` 之前一律经过与表单**完全相同的校验器**。

网页上点「解析这句话」同样支持多轮：缺少条件时表单保留已确定的部分，输入框清空等待补充。

**幻觉误填率**是这一层最重要的指标——衡量"用户没说的条件，模型有没有自己编一个"，实测 1.6%。

## 架构：一次请求经过五层

```text
网页 / CLI（表单 或 一句自然语言）
  ↓
extraction.py          模型抽取槽位 → 与表单同一套校验 → 缺失则多轮追问
  ↓
PlanningService        会话锁 + 全局并发上限 + 权威约束合并
  ↓
TripAgent 循环         协议校验、轮数与调用上限、工具结果回灌
  ↕
ChatProvider           同一接口的两个实现：离线规则 | 真实模型
  ↓
ToolRegistry           5 个业务工具 + submit_plan + JSON Schema 参数校验
  ↓
verify_plan            用用户原始条件重算，模型说什么不算数
  ↓
SQLite + 网页 / CLI
```

五个关键设计：

- **两层校验**。`check_itinerary` 在规划途中给模型反馈；`verify_plan` 是应用终审，永远用表单里的预算和时间重算。
- **用户级约束在构造时注入**。雨天和用餐要求都是 `TripTools(rain=..., include_meal=...)`，**模型无法通过工具调用放宽约束**（Schema 会直接拒绝该字段）。
- **证据白名单**。最终方案的地点必须来自本轮 `search_places`，引用必须来自本轮 `search_guides`。
- **错误即数据**。工具异常转成 `{"ok": false, "error": ...}` 回灌给模型；无结果时还会带 `hint` 给出判决性提示，避免模型换参数反复空转（实测把该场景的工具调用从 17 次降到 5 次）。
- **失败原文要留证据**。终审被拒时记录被拒文本开头——这条观测缺口正是定位 JSON 缺陷的关键。

模块职责与取舍见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 快速开始

```bash
python3 main.py --serve          # 打开 http://127.0.0.1:8765
python3 main.py --demo           # 命令行离线演示
python3 main.py --demo --rain --budget 80
python3 main.py --demo --chat    # /budget 80 改预算，/rain 切雨天，exit 退出
```

网页可改预算、人数、时间、兴趣、雨天、室内外和用餐要求；可用一句话解析条件（支持多轮补充）；**生成过程通过 SSE 实时显示工具调用进度**；刷新恢复最近完成结果。

## 接入 DeepSeek

详细步骤与错误解释见 [第 11 课](docs/LESSON_11.md)。项目自动读取根目录 `.env`，进程环境变量优先。

```bash
python3 main.py --doctor       # 不联网，只检查脱敏配置状态
python3 main.py --check-api    # 两轮真实请求，会消耗额度
python3 main.py --live --rain --budget 80
python3 main.py --live --ask "两个人，11月21号，预算200，想拍照"
python3 main.py --live --ask "预算500" --answer "11月21号" --answer "两个人"
```

`--answer` 可重复，用于脚本化地回答追问。默认关闭 thinking，输出上限 4096、超时 60 秒、最多重试 1 次。

**注意 `.env` 每行必须完整换行。** 曾出现两行粘连导致 `LLM_BASE_URL` 被并入 key 值、请求返回 401 的情况；本项目按第一个 `=` 切分，不会自动纠正这类错误。

## 验证与评测

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v   # 111 项，全部内存模拟响应，不联网
python3 main.py --evaluate                              # 离线规则回归
python3 main.py --evaluate --live                       # 真实模型回归
python3 main.py --evaluate --suite extraction --live    # 槽位抽取
python3 main.py --evaluate --suite citations --live     # 引用评审（LLM-as-judge）
python3 main.py --evaluate --suite retrieval            # BM25 vs TF-IDF，不联网
python3 scripts/build_corpus.py                         # 重新生成检索语料，固定种子、幂等
```

## 集成

**MCP 服务**（最小 stdio 实现，纯标准库）：

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  | PYTHONPATH=src python3 scripts/mcp_server.py
```

只暴露 5 个业务工具，按名字排除 `submit_plan`（复用 `tools.CONTROL_TOOLS`，避免两份名单分叉）。

**CI**：[.github/workflows/ci.yml](.github/workflows/ci.yml) 在 Python 3.11 / 3.13 上跑全部测试、离线回归、检索评测、语料幂等性，以及 MCP 服务的 stdout 纯净性。

## 已知边界

- 12 例回归是开发期小型集合、**不是盲测**；20 例抽取评测标签由作者人工标注；检索语料与标签**都由脚本生成**；引用评审是**模型评审模型**，且方案没有自由文本论证，测的是主题相关性而非严格语义蕴含。
- 检索是字符二元组 BM25，**没有 embedding 或向量库**。实测口语化近义词是词法检索的硬盲区（"胶卷" vs "胶片冲洗" 完全重叠为零）。
- 不保证填满 10:00–18:00；不处理起终点导航、实际票价、订票、跨城市或跨午夜。
- 会话保存完整已完成回合，最近三个完整回合进入模型上下文，**没有摘要压缩**；并发控制只在单进程内有效。
- 网页仅绑定 `127.0.0.1`，无账号鉴权，不应原样公开部署。
- MCP 服务是**最小子集**（initialize / tools/list / tools/call / ping），未实现 resources、prompts、sampling、取消与协议版本协商，**没有用真实 MCP 客户端验证过**。
- 当前**没有** LangGraph、向量库、真实地图、多 Agent、公网部署或线上用户。

### 三个已修复的缺陷（排查过程见 [reports/README.md](reports/README.md)）

1. **工具层给出假绿灯**：`check_itinerary` 曾不检查用餐要求而 `verify_final` 检查，两层口径不一致导致模型连续三次终审失败。修复为把 `include_meal` 与 `rain` 一样在构造时注入。
2. **最终输出不是干净 JSON**：第一次修复只剥 Markdown 围栏（假设错误，把修复轮从 5/6 变成 6/6）；记录被拒原文后改为提取第一个配平的 JSON 对象，修复轮降为 0/6；最终进一步改为 `submit_plan` 工具调用，从结构上消除该问题。
3. **无解场景空转**：模型在"要求用餐但预算内没有餐厅"时反复换参数搜索，耗尽工具调用额度。修复为在无解时返回判决性 `hint`，工具调用从 17 次降到 5 次。

## 十二课与面试训练

从 [统一课程入口](docs/LEARNING.md) 开始。第三至十二课为完整精读讲义。[学习记录](docs/STUDY_LOG.md) 留给你填写，不自动标记掌握。

[54 题面试题库](docs/INTERVIEW_BANK.md) · [训练计划](docs/INTERVIEW_TRAINING.md) · [中文面经调研](docs/RESEARCH.md) · [简历表述](docs/RESUME.md)。

## 核心文件

```text
src/weekend_agent/
  request.py         表单权威条件
  extraction.py      自然语言 → 槽位抽取 + 多轮追问
  tools.py           5 个业务工具 + submit_plan + Schema 与参数校验
  retrieval.py       字符二元组 BM25
  retrieval_eval.py  TF-IDF 基线与 recall@k / MRR
  jsonio.py          模型输出的容错 JSON 解析
  config.py          .env、环境变量及调用限制
  diagnostics.py     离线配置检查与两轮 API 连通测试
  providers.py       模型 API 适配与早期固定演示
  planning.py        多站离线规则流程
  agent.py           消息循环、调用护栏、submit_plan 终审通道
  finalize.py        最终方案校验与应用渲染
  memory.py          SQLite 与上下文选择
  service.py         会话和业务组装
  server.py          仅本机 HTTP 服务（含 SSE 进度流）
  evaluation.py      固定回归、弱基线与修复轮统计
  extraction_eval.py 抽取准确率 / 幻觉误填率 / 追问正确率
  citation_eval.py   引用命中率 / 召回率（LLM-as-judge）
  interview.py       面试练习
  web/               HTML、CSS、JavaScript
  data/              虚构地点、资料、用例和题库
scripts/build_corpus.py  确定性生成检索语料与标注查询
scripts/mcp_server.py    最小 MCP stdio 服务
reports/           真实模型评测报告与调用 trace
examples/lesson01–lesson12/  课程实验（调用同一业务代码）
docs/              逐课教材与求职材料
tests/             业务、协议和集成测试（111 项）
```

完整设计与取舍见 [ARCHITECTURE.md](docs/ARCHITECTURE.md)，当前验证状态见 [STATUS.md](docs/STATUS.md)。

## 本机网页与数据库历史

见 [本机使用说明](docs/LOCAL_WEB.md)。网页由 Python 后端调用本地配置的模型 API，SQLite 保存会话和每次成功生成的快照；网页可恢复历史。有模型配置时新会话默认使用真实模型。
