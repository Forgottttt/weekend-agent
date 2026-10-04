# 第9课：从点击按钮到返回安排，读懂网页与HTTP

本课不要求先学习React。我们只有HTML、CSS、JavaScript和Python标准库服务，目的是让你看清每层输入输出。

## 1. 学完应当能做什么

看到网页报错时，判断问题发生在浏览器、HTTP输入检查、业务层还是模型接口；能用一个很小的请求绕开界面复现问题；能解释为什么浏览器不应拿到模型密钥。

先记住完整链路：

```text
index.html表单
 → app.js收集值并发送JSON
 → server.py接收HTTP
 → PlanningService恢复会话和条件
 → TripAgent调用来源与工具
 → verify_final重新校验
 → SQLite保存完成结果
 → server.py返回JSON
 → app.js按数据创建页面元素
```

## 2. 文件与运行入口

| 文件 | 读哪部分 |
|---|---|
| [index.html](../src/weekend_agent/web/index.html) | 表单id、按钮、结果容器 |
| [app.js](../src/weekend_agent/web/app.js) | submit监听、fetch、render、restore |
| [server.py](../src/weekend_agent/server.py) | do_GET、do_POST、send |
| [service.py](../src/weekend_agent/service.py) | plan及错误类型 |

```bash
python3 examples/lesson09/01_http_request.py
python3 examples/lesson09/02_http_failures.py
```

这两个实验会临时绑定127.0.0.1的随机端口，不访问真实模型。若运行环境禁止监听本机端口，需要允许本地网络；不要把权限错误误认成Agent逻辑错误。

正式界面：`python3 main.py --serve`，然后打开`http://127.0.0.1:8765`。

## 3. HTML的id怎样连接到JavaScript

HTML里有：

```html
<input id="budget" type="number" value="200">
```

JavaScript里定义：

```javascript
const $ = id => document.getElementById(id);
```

因此`$('budget')`得到该输入框元素，`$('budget').value`得到它当前的值。

箭头函数先按普通函数理解即可：输入一个id，返回对应元素。它与后端Python的字典查找没有关系，也不是jQuery库；这里只是项目自己起的短函数名。

## 4. 浏览器值为什么还要转类型

即使HTML是`type="number"`，`.value`仍然是字符串。例如输入80得到`"80"`。服务端Schema要求数字，因此代码用`Number(...)`转换。

| 页面值 | JavaScript转换 | JSON值 | Python解析后 |
|---|---|---|---|
| 预算"80" | Number(value) | 80 | int |
| 雨天复选框 | .checked | true | True |
| 不限室内外 | 选项any转null | null | None |
| 兴趣"拍照，美食" | split、trim、filter | ["拍照","美食"] | list[str] |

`filter(Boolean)`会去掉分割后的空字符串，所以尾部多一个逗号不会自动变成空标签。但最终服务端仍会检查标签数量与长度。

## 5. 点击按钮后，submit回调做什么

```javascript
event.preventDefault();
```

它阻止浏览器按传统表单方式跳转整页。然后程序读取各字段，组装request对象，并暂时禁用表单控件，防止生成过程中又切换模式或改条件导致页面状态混淆。

请求示意：

```json
{
  "request": {"city":"杭州","budget_per_person":80,"rain":true},
  "mode": "demo",
  "question": "请根据表单规划行程。",
  "session_id": null
}
```

`session_id=null`表示新建会话；已有ID表示继续原会话。表单里实际还会发送人数、时间、兴趣等字段。

## 6. fetch、await和JSON.stringify分别是什么

```javascript
const response = await fetch('/api/plan', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({request, mode, question, session_id})
});
const result = await response.json();
```

- `JSON.stringify`：把JavaScript对象编码成JSON文本，类似Python的json.dumps。
- `fetch`：发出HTTP请求，返回一个Promise。
- `await`：让这个异步函数等到请求完成后再往下执行；等待时浏览器仍能响应其他事件。
- `response.json()`：读取响应体并解析成JavaScript对象。

`fetch`收到HTTP400不一定自动抛异常。因此代码还要检查`response.ok`；错误时读取后端的error字段并显示。

## 7. 后端怎样检查输入

`do_POST`先检查路径和来源，再读取请求体：

1. Host必须对应本地服务地址；Origin存在时必须是允许的本地来源。
2. Content-Type必须是application/json。
3. Content-Length在1到65536字节之间。
4. JSON能被解析，且不接受NaN/Infinity。
5. 最外层只允许request、question、mode、session_id。
6. Service再调用TripRequest检查业务类型与约束。

前端有数字框，不代表任何请求都来自这个数字框。用户可以用脚本直接调用接口，所以服务端检查不能省略。

## 8. 状态码应当对应什么问题

| 状态码 | 本项目含义 | 示例 |
|---|---|---|
| 200 | 请求已处理并返回结果 | planned或no_plan都可能是200 |
| 400 | 输入或配置类错误 | group_size=True、预算是字符串 |
| 403 | 本地来源检查失败 | 非本地Origin |
| 404 | 路径或会话不存在 | GET不存在的session |
| 409 | 当前任务冲突 | 同会话正在生成 |
| 502 | 已处理的模型或规划运行失败 | 上游401、输出截断、轮数上限 |
| 500 | 未预料内部错误 | 返回通用信息，避免泄漏内部详情 |

注意：DeepSeek返回的401会被APIProvider转换成运行错误，再由本地服务返回502，正文会指出上游HTTP401。你看到的是两个不同服务各自的状态码，不矛盾。

第二个实验预期输出依次包含200、400、400、403。预算字符串和bool人数都应在真正规划前被拒绝。

## 9. 为什么页面使用textContent

结果内容可能来自模型或外部资料。`textContent`会把内容当文本显示；如果使用`innerHTML`，字符串中的标签就可能被浏览器解释成HTML。

项目用`document.createElement`创建固定结构，再向里面放文本。费用来自`plan.checked`，不是从模型的一段散文里用正则猜金额。

“查看生成过程”里显示模型名、逻辑调用数、HTTP尝试数、工具数、最终校验次数及已返回token用量。它帮助你区分慢在模型、重试还是多轮修复。

## 10. 刷新恢复与切换模式

浏览器localStorage只保存最近的session_id，不保存API密钥。刷新后：

```text
读取session_id → GET /api/session?id=... → 取得已完成结果 → fill表单 → render行程
```

如果会话失效，页面清除旧ID。点击“新建会话”也会清除当前ID和显示区域，但不会删除SQLite中的旧记录。

新版切换demo/live时会自动新建会话并保留表单，避免把离线模式历史误当成live会话。后端仍保留模式一致性检查，不能只靠界面遵守。

## 11. 模型配置提示意味着什么

网页GET `/api/health`取得脱敏配置状态；后端只返回模型名、地址、限制和密钥是否存在，不返回密钥内容，也不会为健康检查发起模型请求。

“本地配置已就绪”只说明字段读取成功，不代表密钥有效、余额充足或真实工具调用已通过。真正连通测试由第11课的`--check-api`完成。

填完.env后刷新页面可重新检查。当前运行的旧版Python进程不会自动加载新代码，所以代码升级后需要重启服务；新版代码每次创建live配置时会重新读取.env。

## 12. 并发与异步别混淆

浏览器的async/await、Python的ThreadingHTTPServer、同会话Lock、Agent中的顺序工具循环，分别处于不同层。

浏览器异步等待不等于后端工具并行；HTTP服务能用线程接多个请求，也不意味着同一会话可以无锁同时修改。Service最多允许两个规划任务，同一会话仍只允许一个。

目前没有流式响应。用户要等完整计划校验并保存后，才能收到最终结果。增加SSE流式显示是未来功能，不能称为已实现。

## 13. 练习与答案

**A.** 把实验中的预算从80改成字符串"80"，为什么应返回400？

<details><summary>答案</summary>
JSON解析保留了字符串类型，而TripRequest预算Schema要求number。隐式把任意字符串转数字可能掩盖客户端错误，当前接口要求客户端明确发送数字。
</details>

**B.** no_plan为什么可以返回200？

<details><summary>答案</summary>
HTTP请求正常完成，只是业务结果未找到方案。HTTP成功、业务找到候选、候选质量高，是不同判断。
</details>

**C.** 禁用按钮能彻底防止重复请求吗？

<details><summary>答案</summary>
不能。另一个标签页或脚本仍可请求，因此服务端还需要锁与并发限制。界面禁用用于改善体验，后端负责真正的约束。
</details>

**D.** 直接把服务绑定0.0.0.0就能当公网产品吗？

<details><summary>答案</summary>
不能据此宣称可上线。当前没有账号鉴权、用户隔离和生产配额；地址绑定只是监听范围设置，不会自动补齐这些能力。本课仅验证本机演示。
</details>

## 14. 面试表达与过关标准

对应[Q33–Q36](INTERVIEW_BANK.md#q33)。能按层画出完整数据流，说明为什么API密钥在Python服务端、为何前端校验仍不够，以及如何用HTTP实验复现输入错误。下一课：[评测](LESSON_10.md)。
