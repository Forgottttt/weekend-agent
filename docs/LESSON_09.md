# 第9课 网页与HTTP：让项目可以演示

日期：2026-10-04。本课材料已生成，不代表用户已经掌握。

## 本课目标

把点击按钮理解成一次可追踪的数据流，不需要先学习完整前端框架。

## 文件和运行入口

`server.py`；`service.py`；`web/index.html`、`app.js`和`style.css`。

```bash
cd /path/to/weekend-agent  # 替换为你自己的项目目录
python3 examples/lesson09/01_http_request.py
```

配套脚本有中文注释，复用实际业务模块。先运行，再按下面顺序跟踪。

## 输入

浏览器提交request、mode、question和session_id；临时HTTP示例提交雨天、预算80，运行demo。

## 按执行顺序理解

### 1. 前端收集

表单字段读出字符串，需要把预算和人数转成Number；复选框读checked；不限室内外转换成null。JSON.stringify把对象编码成文本。

### 2. 发送请求

fetch POST /api/plan，Content-Type为application/json。前端禁用生成按钮，避免重复点击；同一会话服务器也有锁。

### 3. 服务检查

HTTP层检查Host/Origin、请求体长度和字段；业务条件由TripRequest校验。服务只绑定127.0.0.1，不提供公网账号系统。

### 4. 执行并保存

PlanningService创建或恢复会话，Agent执行，应用最终校验，SQLite保存，返回结果JSON。模型密钥留在服务进程的环境变量中。

### 5. 前端展示

用textContent展示文本，避免把模型或资料当HTML插入。网页用应用重算结果显示时间和费用。

### 6. 错误提示

输入错400；并发冲突409；已处理的模型失败502。用户得到可读信息，内部异常用通用500。GET /api/session能恢复最近一次完成结果。

## 关键代码

```javascript
const response = await fetch("/api/plan", {
  method: "POST", headers: {"Content-Type": "application/json"},
  body: JSON.stringify({request, mode, question, session_id})
});
const result = await response.json();
```

代码片段用于定位核心逻辑，不要求替换整个业务文件。完整实现以项目文件为准。

## 预期结果

临时HTTP脚本返回planned，并显示雨天80元预算下每人67元的教学方案。正式网页启动：python3 main.py --serve，然后打开http://127.0.0.1:8765。

## 自己做一个改动

在网页依次用80、20元预算生成，比较通过与未找到候选；刷新观察恢复。切换运行模式前新建会话。不要为了测试而在浏览器填写密钥。

## 本课面试训练

先不看答案，用自己的话回答；参考思路和追问见 [题库](INTERVIEW_BANK.md)。

- [Q33](INTERVIEW_BANK.md#q33)：网页点击按钮之后，数据走过哪些层？
- [Q34](INTERVIEW_BANK.md#q34)：模型密钥怎样配置，为什么不能放前端？
- [Q35](INTERVIEW_BANK.md#q35)：请求失败时怎样区分用户输入错误与模型服务错误？
- [Q36](INTERVIEW_BANK.md#q36)：线程、协程和工具并行分别解决什么问题？

## 验收

能画出浏览器→HTTP→Service→Agent→Verifier→数据库→浏览器的链路；能指出前端输入检查不能替代服务端检查。

## 当前边界

这是本地演示服务。公网部署需另外做账号鉴权、配额、存储隔离、监控等；当前未公开部署。
