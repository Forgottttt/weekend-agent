# 第11课 模型API：切换实现，保留调用协议

日期：2026-10-04。本课材料已生成，不代表用户已经掌握。

## 本课目标

先观察API的地址、请求体和响应结构，再由你配置自己的服务完成一条真实调用。

## 文件和运行入口

`providers.py`；`config.py`；`.env.example`；`service.py`。

```bash
cd /path/to/weekend-agent  # 替换为你自己的项目目录
python3 examples/lesson11/01_api_without_network.py
```

配套脚本有中文注释，复用实际业务模块。先运行，再按下面顺序跟踪。

## 输入

教学脚本用example.invalid和mock响应，密钥是无效占位符；不会发网络请求或产生费用。

## 按执行顺序理解

### 1. 接口抽象

ChatProvider要求complete(messages,tools)返回assistant字典。两个实现分别来自离线规则和真实HTTP，因此Agent不需要为供应商重新写循环。

### 2. 请求编码

APIProvider构造model、messages、tools、tool_choice、stream和输出上限；Authorization单独放在请求头，不打印。DeepSeek域名使用disabled thinking以简化教学和会话保存。

### 3. 响应解析

读取choices[0].message，保留协议需要的content与tool_calls。usage只保留非负整数的输入、输出token计数；mock里的10和5不是真实用量。

### 4. 异常与重试

429、5xx、连接或超时最多重试一次，401或参数错误不重试。模型逻辑轮数与HTTP实际尝试数不同，网络失败可能已产生费用。

### 5. 密钥配置

程序直接读取环境变量，不自动加载.env。不要把真实密钥发到聊天、写进源码或前端。当前默认DeepSeek模型名依据2026-10-03官方文档为deepseek-flash，可通过LLM_MODEL改。

### 6. 真实验收

先单个问题，再低预算或雨天修改，保留实际trace和APIusage。确认最终方案是否通过、是否有格式错误，再考虑批量live评测。当前未完成该联网步骤。

## 关键代码

```python
payload = {"model": config.model, "messages": messages,
           "tools": tools, "tool_choice": "auto", "stream": False}
# 编码为 UTF-8 JSON，通过请求头传递密钥
message = result["choices"][0]["message"]
```

代码片段用于定位核心逻辑，不要求替换整个业务文件。完整实现以项目文件为准。

## 预期结果

打印示例请求地址、字段、模拟回答和模拟usage；所有内容明确标为mock。真实调用前必须由你配置自己的服务。

## 自己做一个改动

在mock响应里返回一个tool_calls，解释下一步怎样进入Agent循环。读懂后在自己的终端配置环境变量，执行下方live命令并检查日志。

## 本课面试训练

先不看答案，用自己的话回答；参考思路和追问见 [题库](INTERVIEW_BANK.md)。

- [Q41](INTERVIEW_BANK.md#q41)：真实模型接入需要改动Agent循环吗？
- [Q42](INTERVIEW_BANK.md#q42)：模型选择怎样比较能力、稳定性和成本？
- [Q43](INTERVIEW_BANK.md#q43)：RAG和微调各解决什么问题，你实际做过什么？
- [Q44](INTERVIEW_BANK.md#q44)：LoRA的基本思想是什么，它和项目有什么关系？

## 验收

能解释HTTP请求与Agent轮数的关系；能指出供应商适配应改哪一层；能说清未验证的联网状态。

## 当前边界

提供兼容接口实现不保证所有模型服务都能直接使用。真实模型效果、额度、延迟和费用由你的实际运行验证。

## 自己配置后再运行真实模型

以下是macOS默认zsh写法，密钥输入不回显：

```bash
read -s "LLM_API_KEY?请输入自己的模型API密钥："
export LLM_API_KEY
export LLM_BASE_URL='https://api.deepseek.com'
export LLM_MODEL='deepseek-flash'
python3 main.py --live --question '请按表单规划，优先拍照。'
```

联网调用可能收费。先跑一条，再阅读trace；不先批量跑12条。其他服务按其官方配置填写。

模型名及请求参数依据：[DeepSeek官方接口文档](https://api-docs.deepseek.com/api/create-chat-completion/)。
