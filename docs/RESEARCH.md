# 中文面经调研与技术依据

检索日期：2026-10-03。用户明确要求搜索中文互联网近期AI Agent实习面试问题。

## 如何理解这些样本

检索到的中文题目以牛客个人面经为主。个人自述不是公司的官方题库，也不能独立验证面试真实性；几个帖子不足以计算全国频率。下表用于确定训练覆盖，不能说“全国排名前十”或“某公司必考”。题库参考思路依据实际代码与官方技术资料编写，没有照抄帖子里的参考答案。

| 来源 | 页面日期或自述日期 | 用于本项目训练的主题 |
|---|---|---|
| [AI应用开发实习面经](https://www.nowcoder.com/feed/main/detail/40920533fad14136bff01c3928c7e953) | 正文明确面试2026-07-25，页面显示08-05 | AI辅助代码的个人贡献、模型选择、上下文管理、服务基础 |
| [字节AI Agent开发岗面经合集](https://www.nowcoder.com/discuss/922659486983036928) | 正文明确2026-07-03、06-23等，页面显示08-28 | 评测集、指标、工具调用、MCP、上下文、手写算法 |
| [曹操出行Agent实习面经](https://www.nowcoder.com/feed/main/detail/1650bd48a48644138ebf2362740abc86) | 页面08-17，未在正文单独标年 | 为什么需要Agent、框架选型、长链路稳定、评测和AI Coding |
| [Agent后端日常实习面经](https://www.nowcoder.com/discuss/932295617999622144?sourceSSR=home) | 页面09-24，正文自述09-23，未单独标年 | 项目设计依据、数据集质量、口语化输入、知识库与切块 |
| [AI初创Agent开发实习面经](https://www.nowcoder.com/feed/main/detail/632b151ada3a404894f1dc1c30dcbd19) | 页面04-17，未单独标年 | Python容器、RAG流程、记忆、切块与模型基础 |

这是从样本得出的训练优先级判断：优先练工具协议、项目取舍、状态与最终校验、检索和评测，再补Python、SQL、模型基础。多数题需要项目证据，单纯堆术语很容易被追问。

## 主题对应课程

| 主题 | 课程 | 实际能力或边界 |
|---|---|---|
| Python基础与数据 | 1–3 | 字典、列表、JSON、类型、变量变化、预算计算 |
| Function Calling | 2、4、5 | 参数检查、ID配对、循环和调用上限 |
| RAG | 6 | 实现BM25词法资料检索；没有embedding或向量库 |
| 防止幻觉与错误结果 | 7 | 权威条件、证据ID、最终重算；不承诺完全免疫注入 |
| 上下文与持久化 | 8 | 完整存储、近期回合上下文；没有语义长期记忆 |
| 服务与并发 | 9 | 本地HTTP、会话锁、乐观版本；不是生产系统 |
| 评测 | 10 | 12例开发回归和弱基线；不是模型成功率 |
| 模型接入 | 11 | 接口适配、超时、重试、usage；真实联网待完成 |
| 项目表达与补充基础 | 12 | 54题、追问、手写修改、诚实说明个人贡献 |

## 技术答案依据

- [DeepSeek工具调用](https://api-docs.deepseek.com/guides/tool_calls/)：请求函数后由应用执行，结果通过tool_call_id关联。当前项目遵循这一消息通路。
- [DeepSeek接口文档](https://api-docs.deepseek.com/api/create-chat-completion/)：2026-10-03检索页面列出deepseek-flash与deepseek-v4-pro，thinking可设disabled。本项目默认改为deepseek-flash；可用性及费用仍由实际账号验证，没有运行真实API。
- [LangGraph流程与Agent](https://docs.langchain.com/oss/python/langgraph/workflows-agents)：用于区分预定义流程、模型决策和图式迁移。本项目尚未引入该框架。
- [LangChain检索说明](https://docs.langchain.com/oss/python/langchain/retrieval)：检索为生成提供外部上下文。不能把本项目的词法检索声称为向量检索。
- [Elastic全文检索说明](https://www.elastic.co/docs/solutions/search/full-text/how-full-text-works)：BM25用于词项相关性排序；本项目是独立教学实现，不使用Elasticsearch。
- [Anthropic Agent评测说明](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)：用于训练任务、轨迹、结果与评测器的区分。当前回归集规模小，没有真实模型泛化结论。
- [MCP官方介绍](https://modelcontextprotocol.io/docs/getting-started/intro)：理解应用与工具/资源服务之间的标准连接；不把本地函数注册表等同于已接入MCP。
- [LoRA原始论文](https://arxiv.org/abs/2106.09685)：补充低秩参数更新基础。本项目没有微调大语言模型。
- [Attention Is All You Need](https://arxiv.org/abs/1706.03762)：补充注意力基础。本项目使用模型接口，没有训练Transformer。

## 后续调研如何更新

保存岗位、面试日期、问题类别、原始链接，优先原作者自述；将技术答案回到官方文档或论文校验。不要把聚合帖题量当频率，不因帖子谈到某项技术就强行加进简历。

## 2026-10-04：DeepSeek官方接入补充

用户明确选择DeepSeek官方API。核对[首次调用](https://api-docs.deepseek.com/zh-cn/)、[接口参数与finish_reason](https://api-docs.deepseek.com/api/create-chat-completion/)、[思考模式工具历史要求](https://api-docs.deepseek.com/zh-cn/guides/thinking_mode/)、[错误码](https://api-docs.deepseek.com/zh-cn/quick_start/error_codes/)。当前API模型ID为deepseek-flash，对应V4.1 Flash；项目固定非思考模式。教材11解释本项目的实现选择，不把配置完成或mock测试当成真实调用效果。
