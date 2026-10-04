# 第7课 最终方案校验：应用保留决定权

日期：2026-10-04。本课材料已生成，不代表用户已经掌握。

## 本课目标

证明模型通过了一个工具检查，并不等于最终展示一定满足真实用户条件。

## 文件和运行入口

`request.py`；`finalize.py`；`agent.py` 的final_rejected路径；`tests/test_complete_project.py`。

```bash
cd /path/to/weekend-agent  # 替换为你自己的项目目录
python3 examples/lesson07/01_final_verification.py
```

配套脚本有中文注释，复用实际业务模块。先运行，再按下面顺序跟踪。

## 输入

权威每人预算30元；候选面馆35元或小吃店25元；最终JSON只允许status、stops、guide_ids。脚本手写searched_ids来演示这一层，实际Agent从本轮搜索结果收集它。

## 按执行顺序理解

### 1. 权威条件

TripRequest来自表单，不来自模型的最后一条工具参数。check_arguments每次用它重建预算、人数、开始和结束时间。

### 2. 结构检查

verify_final解析JSON，拒绝额外字段。模型不能在最终对象中添加price=0或自称total_group_cost=1；这些值由程序重算。

### 3. 证据检查

地点必须属于本轮实际搜索结果，资料ID必须属于本轮实际检索结果。只存在于本地库中仍不够。

### 4. 业务检查

活动兴趣、室内外偏好、用餐要求先检查；再由check_itinerary计算预算、交通、营业时间和重复地点。

### 5. 渲染

通过后render_plan只读应用计算出的schedule和费用，网页也用plan.checked展示。模型原始JSON不直接作为可信票价文字展示。

### 6. 修正与停止

live模型可收到最终拒绝原因并修正，最多三次。no_plan表示没找到方案，不证明无解；连续输出无方案也不能作为高完成率。

## 关键代码

```python
checked = registry.execute("check_itinerary",
                           request.check_arguments(candidate["stops"]))
if not checked["data"]["valid"]:
    raise ValueError("；".join(checked["data"]["issues"]))
# 通过后才用应用结果渲染
```

代码片段用于定位核心逻辑，不要求替换整个业务文件。完整实现以项目文件为准。

## 预期结果

f01被拒绝：35>30；f04通过：每人25元、两人50元。没有模型填写的低价字段。

## 自己做一个改动

给最终JSON增加cost_per_person=0，观察未知字段错误；把searched_ids设为空，观察本轮搜索证据错误。最后看测试中模型用预算999通过工具、应用按预算30拒绝的案例。

## 本课面试训练

先不看答案，用自己的话回答；参考思路和追问见 [题库](INTERVIEW_BANK.md)。

- [Q25](INTERVIEW_BANK.md#q25)：模型把预算改大后通过了工具检查，怎样防止展示超预算结果？
- [Q26](INTERVIEW_BANK.md#q26)：如何防止最终回答凭空写低票价或虚构地点？
- [Q27](INTERVIEW_BANK.md#q27)：检索资料夹带指令时怎样降低提示注入风险？
- [Q28](INTERVIEW_BANK.md#q28)：最终校验失败后程序怎样继续，什么时候停止？

## 验收

能解释权威条件与模型候选参数为什么分开；能指出两条绕过尝试被哪个检查拦住。

## 当前边界

结构校验不能验证现实数据，也不能保证引用语义忠实、模型完全免疫提示注入或方案最优。
