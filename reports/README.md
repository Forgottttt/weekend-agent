# 真实模型评测证据

本目录保存**真实 DeepSeek API 调用**产生的原始评测报告与调用 trace，用于替代口头声明。
`outputs/` 是运行目录且被 Git 忽略，因此这里保留的是固化副本；文件内容未经人工修改。

## 运行环境

| 项目 | 值 |
|---|---|
| 日期 | 2026-10-04（周日，空闲时段，价格为高峰时段的一半） |
| 模型 | `deepseek-flash`（DeepSeek-V4.1-Flash） |
| 接入方式 | 官方 `https://api.deepseek.com`，非思考模式（`thinking: disabled`） |
| 配置 | `max_tokens=4096`、`timeout=60s`、`max_retries=1` |
| 数据集 | `src/weekend_agent/data/eval_cases.json`，12 例固定回归 |
| Python | 3.14.6（项目要求 ≥3.11） |

## 文件清单

| 文件 | 内容 | 证明了什么 |
|---|---|---|
| `2026-10-04_live_run1_12of12.json` | 真实模型 12/12，61 次模型请求 | 通过率上限 |
| `2026-10-04_live_run2_12of12.json` | 真实模型 12/12，69 次模型请求 | 重复运行的一致性 |
| `2026-10-04_live_run3_11of12.json` | 真实模型 11/12，69 次模型请求 | **存在方差**；`meal_under25` 返回 `error` |
| `2026-10-04_live_run4_after_fix_12of12.json` | 修复后真实模型 12/12，75 次模型请求 | 修复消除了该失败模式 |
| `2026-10-04_demo_baseline_12of12.json` | 离线规则 12/12，0 次模型请求 | 离线规则基线，用于对照 |
| `2026-10-04_live_trace_self_correction.json` | 单次真实规划完整 trace | 模型靠工具反馈做 3 轮预算自我修正 |
| `2026-10-04_live_trace_meal_mismatch.json` | 失败用例复现 trace | 定位到工具层与终审层校验口径不一致 |
| `2026-10-04_live_trace_after_fix_tool_warns_early.json` | 修复后同用例 trace | 工具提前提示用餐要求，模型一轮就收敛到 `no_plan` |

## 汇总数字

```text
修复前通过率    35/36 = 97.2%（3 次独立运行：12/12、12/12、11/12）
修复后通过率    12/12，且原失败用例定向复测 6/6 正确
模型请求        339 次 = 274（4 次评测）+ 63（8 次 CLI 真实规划 trace）+ 2（check-api）
输入 token      1,176,869
输出 token      62,186
估算成本        ≈ 1.43 元（空闲时段，未区分缓存命中）
HTTP 尝试       与模型请求 1:1 —— 全程未触发任何 429/5xx 重试
单例平均        5.7 次模型请求 / 约 1.94 万输入 token / ≈ 0.023 元
中位耗时        6.6–8.9 秒（4 次运行）
离线基线        0 次模型请求 / 约 0.001 秒
```

以上全部由 `outputs/trace_*.json` 与 `outputs/eval_*.json` 逐条累加得到，不是估算。

成本按 [DeepSeek 官方价目](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/) 折算：
`deepseek-flash` 输入（缓存未命中）空闲 1 元、高峰 2 元每百万 token；输出空闲 4 元、高峰 8 元。

## 失败归因

| 失败层 | 观测次数 | 证据 | 状态 |
|---|---|---|---|
| 两层校验口径不一致（用餐要求） | 1/36 用例运行 → `error` | run3 + `..._meal_mismatch.json` | **已修复并验证** |
| 最终输出不是合法 JSON（Markdown 代码围栏） | 7 条 trace 中 6 条各触发 1 次 | `final_rejected: Expecting value: line 1 column 1` | **未修复，当前头号失败源** |
| HTTP 429 / 5xx / 网络异常 | 0 | 339 次请求对应 339 次 HTTP 尝试 | 无需处理 |
| 工具参数不符合 Schema | 0 | 全部 `ok=True` | 无需处理 |
| 引用不在本轮检索结果内 | 0 | 全部 citation 命中白名单 | 无需处理 |
| 输出被截断（`finish_reason=length`） | 0 | 无相关记录 | 无需处理 |

### 缺陷一：工具层给出假绿灯（已修复）

用例 `meal_under25`：每人预算 20 元且要求安排用餐，而地点库中最便宜的餐厅为 25 元（`f04`），
因此正确输出应为 `{"status":"no_plan"}`。第 3 次运行返回 `error`：

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
（`TripTools(rain=..., include_meal=...)`），而不是做成工具参数。
这样做有两个好处：工具判定与终审口径一致；模型**无法通过在工具调用里传 `include_meal=false` 来放宽约束**
（Schema 的 `additionalProperties: false` 会直接拒绝该字段）。`finalize.verify_final` 的独立检查予以保留，作为纵深防御。

**验证**：56→58 项单元测试全部通过（新增 2 条回归测试）；离线回归仍 12/12；
修复后真实评测 12/12；原失败用例定向复测 **6/6 正确**。

### 缺陷二：最终输出被包在 Markdown 代码围栏里（未修复）

修复缺陷一之后重新观察 6 次定向复测，`check_itinerary` **每次都提前提示了用餐问题**，
说明假绿灯已消除；但 5 次运行仍出现 `final_checks=2`，被拒理由**全部**是：

```text
Expecting value: line 1 column 1 (char 0)
```

这是 `json.loads` 的原生错误，说明模型没有遵守 System Prompt 里"不要 Markdown 代码围栏"的要求。
后果不是错误答案（修复循环能救回），而是**几乎每次会话都白白多烧一轮完整上下文**
（约 2–4 万输入 token，占单次成本的相当比例），并且错误提示是 Python 原文而非可读中文。

可选修法，按推荐顺序：

1. 解析前剥掉 ```json 围栏，并在 `verify_final` 里把 `JSONDecodeError` 包装成中文提示；
2. 终局那一轮改用服务商的 JSON 输出模式（DeepSeek 官方文档标注支持 Json Output），
   代价是需要在该轮去掉工具定义；
3. 两者都做。

## 如何复现

```bash
python3 main.py --doctor                  # 离线检查配置，不联网
python3 main.py --check-api               # 两轮真实请求验证工具协议
python3 main.py --evaluate --live         # 12 例真实模型回归
```

每次运行会生成新的 `outputs/eval_<时间戳>.json`。真实调用会消耗 API 额度。
