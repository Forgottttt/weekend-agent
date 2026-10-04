# 第11课：接入自己的DeepSeek‑V4.1‑Flash，先懂协议再做真实调用

核验日期：2026-10-04。用户已确认使用DeepSeek官方平台。本课分为离线理解、配置检查、两轮连通测试和真实规划四步，不需要一开始就批量消耗API额度。

## 1. 先把三个名字分清

| 你看到的名字 | 含义 | 本项目填写值 |
|---|---|---|
| DeepSeek‑V4.1‑Flash | 官方模型产品名称 | 用来说明所选模型 |
| model | API请求里的模型标识 | deepseek-flash |
| base_url | 服务基础地址 | https://api.deepseek.com |

截至核验日期，官方`deepseek-flash`指向V4.1 Flash。它是服务端模型标识，未来服务商更新时可能改变对应版本，并非永远固定的模型快照。依据[官方首次调用说明](https://api-docs.deepseek.com/zh-cn/)。

项目会在基础地址后拼接`/chat/completions`，因此不要把完整接口地址又填进LLM_BASE_URL，造成路径重复。

## 2. 文件之间怎样配合

```text
.env或进程环境变量
       ↓
ModelConfig.from_env → 验证字段，得到配置对象
       ↓
APIProvider.complete(messages, tools)
       ↓ 编码JSON、带Authorization头、发HTTPS
DeepSeek返回choices和usage
       ↓
适配为assistant消息 → TripAgent继续执行工具或校验最终候选
```

| 文件 | 本课重点 |
|---|---|
| [config.py](../src/weekend_agent/config.py) | read_env_file、ModelConfig、public_info |
| [providers.py](../src/weekend_agent/providers.py) | complete、_request及HTTP错误分类 |
| [diagnostics.py](../src/weekend_agent/diagnostics.py) | doctor、check_api |
| [.env.example](../.env.example) | 可以提交的配置模板 |
| [连接测试](../tests/test_model_connection.py) | 全部mock，不读真实密钥、不联网 |

## 3. 先跑不联网的模拟实验

```bash
python3 examples/lesson11/01_api_without_network.py
python3 examples/lesson11/02_tool_roundtrip_mock.py
```

第二个脚本虽然打印官方URL，但使用mock替换urlopen，网络函数不会真正执行。使用的是无效测试密钥，不读取你的.env。

它会打印两组消息角色：

```text
第1次：[system, user]
第2次：[system, user, assistant, tool]
```

这正是第4课的协议。第一次模型请求工具，程序执行后追加assistant和tool，再发第二次模型请求得到文本结束信息。

打印的20个输入token、10个输出token来自预先写好的模拟响应，不是DeepSeek实际计费结果。

## 4. 配置你的密钥

项目根目录已有本地`.env`模板时，直接编辑它。换电脑克隆后可执行：

```bash
cp -n .env.example .env
chmod 600 .env
```

`cp -n`避免覆盖已有.env。密钥只填进本地.env，不要填进会上传GitHub的.env.example，也不要粘贴到聊天中。

只改第一项的占位内容，其余保持如下：

```dotenv
LLM_API_KEY=replace_with_your_key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-flash
LLM_TIMEOUT_SECONDS=60
LLM_MAX_TOKENS=4096
LLM_MAX_RETRIES=1
```

注意`replace_with_your_key`必须换成你自己的值；仅复制模板不算配置成功。当前程序会把该占位文字识别为未配置。

### 这些限制分别控制什么

| 字段 | 默认值 | 意义 |
|---|---:|---|
| TIMEOUT_SECONDS | 60 | 单次网络操作的超时设置，不是整项任务总时限 |
| MAX_TOKENS | 4096 | 每次模型响应的输出上限 |
| MAX_RETRIES | 1 | 第一次尝试失败后最多再尝试1次 |

项目只允许超时5–300秒、输出64–16384 token、重试0–2次。这是教学项目自己的限制，不是DeepSeek模型的最大能力。

## 5. .env的读取规则，避免“我改了却没生效”

`read_env_file`只支持一行一个`KEY=VALUE`、独立注释行和成对引号，不支持执行shell、变量展开或多行值。

读取不会修改整个进程的`os.environ`，而是在配置对象中合并：

```text
进程环境变量优先
       ↓ 若没有对应覆盖
项目根目录.env
       ↓ 没配置则使用代码默认值
```

密钥也支持`DEEPSEEK_API_KEY`别名。若进程里已设置这个别名，它优先于文件中的LLM_API_KEY。配置错行时只报告行号和规则，不把该行密钥打印出来。

如果你之前在终端export过旧密钥，修改.env可能仍被旧环境变量覆盖。确认后可以在自己的终端执行：

```bash
unset LLM_API_KEY DEEPSEEK_API_KEY
```

这只清除当前终端进程环境里的变量，不会删除.env，也不会撤销平台密钥。由当前终端重新启动的程序才会继承变化；已有服务进程的环境不会被另一个终端改变。

## 6. 第一次检查：doctor，不联网

```bash
python3 main.py --doctor
```

它只读取配置，输出模型名、基础地址、限制和布尔状态，不打印密钥。

| 输出 | 怎么理解 |
|---|---|
| network_used=false | 这条命令没有调用模型 |
| key_configured=false | 没填密钥或仍是占位符 |
| ready=true | 本地配置有值并且格式检查通过 |

`ready=true`不证明密钥有效或余额足够。你随便填一串非占位文字也可能通过“存在性检查”，真正认证必须到下一步。

## 7. 第二次检查：check-api，两轮真实请求

```bash
python3 main.py --check-api
```

这条命令会使用你的API额度。其流程固定且很小：

1. 提供天气工具说明，让模型查询杭州2026-11-21的教学天气。
2. 检查模型只返回一次正确工具调用，解析并执行本地get_weather。
3. 追加tool结果，再请求模型用一句话结束。
4. 输出逻辑请求数、HTTP尝试数、usage和连通说明。

正常成功有2轮逻辑请求；默认每轮最多重试一次，因此最多可能发起4次HTTP尝试。若第一步就失败，会提前停止。

这比只问一句“你好”多验证了工具请求、参数、调用ID和回传结果，但仍不代表完整行程规划已经通过，更不代表12例真实模型评测通过。

## 8. APIProvider在发送什么

有工具时，请求体包含：

```json
{
  "model": "deepseek-flash",
  "messages": [{"role":"user","content":"..."}],
  "tools": ["这里实际放工具Schema对象"],
  "tool_choice": "auto",
  "stream": false,
  "thinking": {"type":"disabled"},
  "max_tokens": 4096
}
```

上面的tools字符串只是为展示缩短，实际代码发送第2课的Schema字典。

没有工具时会省略tools和tool_choice，而不是发送空工具数组，减少兼容性问题。密钥在`Authorization: Bearer ...`请求头中，不放在messages、工具参数或网页里。

`json.dumps(..., ensure_ascii=False, allow_nan=False).encode("utf-8")`依次完成：对象转JSON文本、保留中文可读性、拒绝非有限JSON数字、文本转网络字节。

## 9. 响应里真正使用哪些部分

典型响应的核心结构：

```json
{
  "choices": [{
    "finish_reason": "tool_calls",
    "message": {
      "role": "assistant",
      "content": null,
      "tool_calls": ["实际工具调用对象"]
    }
  }],
  "usage": {"prompt_tokens":100,"completion_tokens":30}
}
```

适配器读取`choices[0].message`，校验角色、content和tool_calls类型，再返回给Agent。usage只接受非负整数，逻辑层累计用于观测。

`finish_reason=length`表示输出被截断。本版会立刻报可读错误，不拿半截JSON执行工具。可以提高项目输出上限或缩小任务，再重新运行。响应字段与终止原因依据[官方Chat Completions文档](https://api-docs.deepseek.com/api/create-chat-completion/)。

## 10. 重试怎样计数

`_request`的循环范围是`range(max_retries + 1)`。默认1次重试，就有attempt=0、1两次尝试。

- 429、5xx、网络连接或超时：在额度允许时重试。
- 400、401、402、403、404、422：不因相同参数而盲目重试。
- 重试前等待`0.5 × 2**attempt`秒；最多两次重试时，等待0.5秒、1秒。

每次尝试发HTTP时，`http_attempts`都会增加；Agent的一次complete仍算一个逻辑轮次。重试不是免费的成功保证。

失败前已经收到的usage会保留在累计统计里；完全丢失响应的费用无法靠客户端精确还原。

## 11. 遇到错误，按证据处理

| 现象 | 先检查什么 | 不要直接做什么 |
|---|---|---|
| 尚未设置LLM_API_KEY | .env是否在项目根目录，是否仍是占位符 | 反复点生成 |
| HTTP400或422 | 请求参数、模型名、消息协议 | 无限重试相同请求 |
| HTTP401 | 密钥是否正确、有效 | 把密钥发到聊天求检查 |
| HTTP402 | 平台账户余额 | 修改预算字段企图修复认证 |
| HTTP404 | 是否把/chat/completions填进基础地址或模型ID写错 | 改业务行程算法 |
| HTTP429 | 请求频率与已有任务 | 同时再开十个窗口 |
| length | 输出上限或任务规模 | 尝试执行半截工具JSON |
| 超时 | 网络、服务状态、单次等待与重试设置 | 断言模型没有产生费用 |

401、402、429等含义依据[DeepSeek官方错误码](https://api-docs.deepseek.com/zh-cn/quick_start/error_codes/)。本地网页可能统一用502包装上游模型错误，但正文仍会标明上游代码。

如果遇到错误，可以把**不含密钥的报错文本和--doctor状态**发给我；我们在出错层定位后再继续，不需要推翻整个项目。

## 12. 为什么本版明确关闭思考模式

官方思考模式的工具调用要求后续请求回传相关`reasoning_content`。当前项目历史保存会去掉该字段，因此直接开启思考模式可能在恢复多轮会话时失败。依据[官方思考模式工具说明](https://api-docs.deepseek.com/zh-cn/guides/thinking_mode/)。

本版先固定非思考模式，仍然调用deepseek-flash并支持模型工具选择。若未来增加思考模式，要同时设计协议历史保存、上下文裁剪、展示隔离与恢复测试，不能只把disabled改成enabled就结束。

这也是面试中可讲的供应商适配细节：同样兼容Chat Completions，不意味着所有可选字段与状态管理完全相同。

## 13. 最后才运行真实规划

```bash
python3 main.py --live --budget 80 --rain --question '优先选择适合拍照的室内活动。'
```

程序会经历多轮模型调用，最终仍使用同一套虚构地点与校验器。看trace时检查：搜索返回了什么、模型选了什么、是否被最终拒绝、输入输出token是多少。

网页方式：重启新版服务，选择真实模型后生成。切换模式会新建会话；不能仅在补充文字里把表单80元放宽成200元，要真正修改表单预算。

在没有完成真实调用之前，文档只能写“适配与模拟测试通过”；真正跑完后，再保存真实报告说明结果，不预填成功率。

## 14. 动手练习与答案

**A.** --doctor成功后仍HTTP401，矛盾吗？

<details><summary>答案</summary>
不矛盾。doctor检查配置读取和格式，401来自服务端身份认证。把两层验证分开能避免误判。
</details>

**B.** 同一轮先429再成功，model_calls和http_attempts分别增加多少？

<details><summary>答案</summary>
逻辑模型调用增加1，HTTP尝试增加2。错误重试和Agent再次规划是两个不同循环。
</details>

**C.** 想换另一个兼容模型，优先修改哪些文件？

<details><summary>答案</summary>
先改配置中的基础地址和模型名；若协议差异存在，再改APIProvider及适配测试。TripTools的预算计算不应因为换供应商而重写。
</details>

**D.** 把模拟实验里的第二条响应改成空content，会怎样？

<details><summary>答案</summary>
连通测试拒绝把空回答当作结束成功。先在mock里构造这种响应，理解错误路径，再决定真实请求的重试策略。
</details>

## 15. 面试训练与完成标准

对应[Q41–Q44](INTERVIEW_BANK.md#q41)。除了说明接口抽象，还要能谈配置优先级、截断保护、错误分类和逻辑调用/实际尝试区别。

RAG把资料带进上下文；微调改变模型参数。本项目没有做LLM微调。你在百度做过视觉模型微调，不能自动换成“做过大语言模型LoRA”。

真正完成本课应有：不联网实验能解释、doctor读到正确模型、真实连通测试记录、一条通过最终校验的live行程；尚未完成的步骤如实标注。下一课：[面试复盘](LESSON_12.md)。
