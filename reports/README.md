# 真实模型评测证据

本目录保存**真实 DeepSeek API 调用**产生的原始评测报告与调用 trace，用于替代口头声明。
`outputs/` 是运行目录且被 Git 忽略，因此这里保留的是固化副本；文件内容未经人工修改。

## 运行环境

| 项目 | 值 |
|---|---|
| 日期 | 2026-10-04 / 10-05（周末，空闲时段，价格为高峰时段的一半） |
| 模型 | `deepseek-flash`（DeepSeek-V4.1-Flash） |
| 接入方式 | 官方 `https://api.deepseek.com`，非思考模式（`thinking: disabled`） |
| 配置 | `max_tokens=4096`、`timeout=60s`、`max_retries=1` |
| Python | 3.14.6（项目要求 ≥3.11） |

## 三套评测的结果

| 套件 | 数据集 | 结果 |
|---|---|---|
| Agent 回归 | 12 例固定场景 | **12/12**，70 次模型请求，中位 8.05 秒，**0/12 触发修复轮** |
| 槽位抽取 | 20 例口语化输入 | **槽位准确率 96.0%**（71/74）、**幻觉误填率 3.2%**（4/126）、**追问触发正确率 95.0%**（19/20） |
| 检索 | 201 篇语料 / 44 条标注查询 | BM25 **recall@5 67.0%**、MRR 0.706；TF-IDF recall@5 65.9%、MRR 0.712 |

对话流程的离线规则基线：12/12、0 次模型请求、约 1 毫秒，用于对照。

## 文件清单

| 文件 | 内容 |
|---|---|
| `2026-10-04_demo_baseline_12of12.json` | 离线规则基线，0 次模型请求 |
| `2026-10-04_live_run1_12of12.json` | 首次真实评测 |
| `2026-10-04_live_run2_12of12.json` | 第二次，验证重复运行一致性 |
| `2026-10-04_live_run3_11of12.json` | 第三次，**暴露方差**：`meal_under25` 返回 `error` |
| `2026-10-04_live_run4_after_fix_12of12.json` | 修复用餐约束口径后 |
| `2026-10-05_live_agent_run5_12of12.json` | 修复 JSON 解析后，**0/12 触发修复轮** |
| `2026-10-05_extraction_20cases.json` | 槽位抽取评测明细 |
| `2026-10-05_retrieval_201docs_44queries.json` | BM25 与 TF-IDF 对比明细 |
| `2026-10-04_live_trace_self_correction.json` | 模型靠工具反馈做 3 轮预算自我修正 |
| `2026-10-04_live_trace_meal_mismatch.json` | 用餐约束口径不一致的现场 |
| `2026-10-04_live_trace_after_fix_tool_warns_early.json` | 修复后工具提前提示，一轮收敛 |
| `2026-10-05_live_trace_leading_prose_root_cause.json` | **JSON 解析失败的真实现场（关键证据）** |

## 缺陷一：工具层给出假绿灯（已修复）

用例 `meal_under25`：每人预算 20 元且要求安排用餐，而地点库中最便宜的餐厅为 25 元（`f04`），
正确输出应为 `{"status":"no_plan"}`。第 3 次运行返回 `error`：

```text
error: 最终方案连续三次未通过应用校验
provider_calls: 9, tool_calls: 13, input_tokens: 37341, output_tokens: 1682
```

机制（见 `2026-10-04_live_trace_meal_mismatch.json`）：

1. 预算 20 元下，模型找到一份不含餐厅但花费 ≤20 元的行程；
2. `check_itinerary` 返回 `valid=True` —— 因为该工具**没有 `include_meal` 参数，不检查用餐要求**；
3. 模型据此提交终审，`verify_final` 依据 `include_meal` 拒绝："用户要求用餐，但最终行程没有用餐地点"；
4. 连续三次后触发 `RuntimeError`，评测记为该例失败。

**修复**：照搬既有的 `rain` 模式，把 `include_meal` 作为**用户级约束在构造 `TripTools` 时注入**
（`TripTools(rain=..., include_meal=...)`），而不是做成工具参数。好处有两个：工具判定与终审口径一致；
模型**无法通过在工具调用里传 `include_meal=false` 来放宽约束**（Schema 的 `additionalProperties: false`
会直接拒绝该字段）。`verify_final` 的独立检查予以保留，作为纵深防御。

## 缺陷二：最终输出不是干净 JSON（已修复，但过程值得记录）

这是本项目最值得讲的一段排查过程，因为**第一次修复基于错误假设，而且把问题改得更糟**。

### 观察到的现象

修复缺陷一之后，用同一难点用例连续复测 6 次，`final_checks` 全部等于 2，
即每次都触发了一轮修复：模型提交的最终答案无法被 `json.loads` 解析。

### 第一次修复（错误）

根据错误信息 `Expecting value: line 1 column 1 (char 0)`，我假设模型把 JSON 包在了
Markdown 代码围栏里（System Prompt 里确实专门写了"不要使用围栏"）。于是写了"解析前剥离围栏"。

结果**更差**：同用例修复轮从 5/6 变成 **6/6**。因为真实原因不是围栏。

### 定位真因

我在 `final_rejected` 事件里补记了被拒原文的开头（此前只记错误字符串，事后完全无法判断是格式问题还是业务冲突）。
原文立刻暴露了真相（见 `2026-10-05_live_trace_leading_prose_root_cause.json`）：
**模型在 JSON 前面加了一段英文解释，而且没有用围栏。**

```text
Confirmed: even the minimum (one free photo spot + cheapest food place) costs 27/person > 20 budget.
No valid itinerary exists under the form's constraints.

{"status":"no_plan","stops":[],"guide_ids":[...]}
```

### 真正的修复

解析器改为按「围栏内容 → 整段文本 → 文本中第一个配平的 JSON 对象」依次尝试，
扫描配平花括号时正确跳过字符串字面量与转义引号（否则 `{"title": "预算{100}"}` 会被提前截断）。
同时收紧 System Prompt，明确禁止在 JSON 前后写解释文字。

### 修复前后（同一难点用例，各 6 次）

| 版本 | 需要修复轮的比例 |
|---|---|
| 原始版本 | 5/6 = 83% |
| 只剥离围栏（错误修复） | **6/6 = 100%（更糟）** |
| 提取第一个配平 JSON 对象 | **0/6 = 0%** |

修复后在完整 12 例回归上也是 **0/12 触发修复轮**。

### 这一段说明了什么

- `final_checks > 1` 是一个可量化的指标，但**原始评测报告并不记录它**，是这次才补上的；
- 失败用例如果不保存被拒原文，就只能靠猜，而猜测会把问题改得更糟；
- "错误信息看起来像 A"不等于"原因就是 A"。

## 其他失败归因

| 失败层 | 观测次数 | 状态 |
|---|---|---|
| 两层校验口径不一致（用餐要求） | 1/36 用例运行 → `error` | 已修复 |
| 最终输出不是干净 JSON（前置解释文字） | 修复前 6/6 次复测触发 | 已修复 |
| HTTP 429 / 5xx / 网络异常 | 0（622 次请求全部一次成功） | 无需处理 |
| 工具参数不符合 Schema | 0 | 无需处理 |
| 引用不在本轮检索结果内 | 0 | 无需处理 |
| 输出被截断（`finish_reason=length`） | 0 | 无需处理 |

## 成本

本次开发合计约 **622 次可统计的模型请求、2,302,538 输入 token、116,592 输出 token，
估算约 2.77 元**（空闲时段，未区分缓存命中；另有 20 次抽取调用未计入 token 统计）。
按 [DeepSeek 官方价目](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/) 折算：
`deepseek-flash` 输入（缓存未命中）空闲 1 元、高峰 2 元每百万 token；输出空闲 4 元、高峰 8 元。

## 这些数字不能说明什么

- Agent 回归只有 12 例，是开发期小型回归集，**不是盲测**，不能推断真实模型的泛化能力。
- 抽取评测只有 20 例，标签由本仓库作者人工标注，口径以「用户明确说到」为准，
  兴趣标签的归类存在判断余地。
- 检索评测的语料与标签**都是脚本生成的**（`scripts/build_corpus.py`，固定种子），
  不是人工撰写或人工标注；查询只有正例、没有负例和分级相关性。
  因此 recall@5 与 MRR 只反映 BM25 与 TF-IDF 在这套合成数据上的相对表现，
  **不能推断真实检索质量**。
- 所有地点、天气、费用与资料均为虚构教学数据。

## 如何复现

```bash
python3 main.py --doctor                       # 离线检查配置，不联网
python3 main.py --check-api                    # 两轮真实请求验证工具协议
python3 main.py --evaluate --live              # 12 例 agent 回归
python3 main.py --evaluate --suite extraction --live   # 20 例槽位抽取
python3 main.py --evaluate --suite retrieval            # 检索对比，不联网
python3 scripts/build_corpus.py                # 重新生成语料，固定种子、幂等
```

真实调用会消耗 API 额度。
