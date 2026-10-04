# 第3课 预算与时间：把约束变成可重复计算

日期：2026-10-04。本课材料已生成，不代表用户已经掌握。

## 本课目标

从一份两站计划算出每人费用、全组费用和时间冲突。不是先学公式，而是跟踪每次循环中的 cost、previous_end 和 issues。

## 文件和运行入口

`tools.py` 的 `to_minutes`、`get_route`、`check_itinerary`；`data/hangzhou_demo.json`。

```bash
cd /path/to/weekend-agent  # 替换为你自己的项目目录
python3 examples/lesson03/01_budget_and_time.py
```

配套脚本有中文注释，复用实际业务模块。先运行，再按下面顺序跟踪。

## 输入

公园 p01 从10:00开始，游玩90分钟，价格0；面馆 f01 从12:00开始，游玩60分钟，价格35；人数3，每人预算200，可用10:00–18:00。全部数据虚构。

## 按执行顺序理解

### 1. 时间字符串

to_minutes先split，再把小时分钟变成整数。10:00是600，11:30是690，12:00是720。字符串本身不能直接加90分钟。

### 2. 第一站

previous_id起初是None，因此第一站没有相邻交通。arrival=600，finish=690，cost=0，schedule增加公园。循环末把previous_id改成p01，previous_end改成690。

### 3. 第二站交通

网格[0,0]到[1,0]距离是1，教学公式得到15分钟和每人2元。先把cost从0加到2；最早能到690+15=705，即11:45。12:00到达不冲突。

### 4. 第二站地点费用

面馆访问到13:00，营业时间允许。cost再加35变成37，全组费用37×3=111。价格是每人金额，人数不用于把每人预算放大。

### 5. 记录问题

把面馆改成11:30，会把交通不足文本append到issues。检查函数仍继续计算并返回完整报告；这里没有像筛选函数一样continue跳过这个地点。

### 6. 返回真假

valid=not issues：空列表为False，not后变True。有问题的非空列表为True，not后变False。预算比较使用>，费用恰好等于预算可以通过。

## 关键代码

```python
arrival = to_minutes(stop["start"])
finish = arrival + place["visit_minutes"]
if arrival < previous_end + route["minutes"]:
    issues.append("交通时间不足")
cost += place["price_per_person"]
```

代码片段用于定位核心逻辑，不要求替换整个业务文件。完整实现以项目文件为准。

## 预期结果

正常、交通不足、预算不足三组的每人费用都是37、全组都是111。变化的是issues：第一组为空，第二组含交通不足，第三组含预算超出。

## 自己做一个改动

只把脚本里的正常预算200改成37，再改成36。预测valid和issues；不要改地点价格。加一站展览馆16:00，观察17:30离开展览馆与17:00关门的冲突。

## 本课面试训练

先不看答案，用自己的话回答；参考思路和追问见 [题库](INTERVIEW_BANK.md)。

- [Q09](INTERVIEW_BANK.md#q09)：每人预算、全组费用和预算范围怎样定义？
- [Q10](INTERVIEW_BANK.md#q10)：为什么把 HH:MM 转成分钟数再比较？
- [Q11](INTERVIEW_BANK.md#q11)：为什么预算和营业时间由代码校验，而不是只让模型判断？
- [Q12](INTERVIEW_BANK.md#q12)：没有找到行程是否意味着这个请求无解？

## 验收

能手算600→690→705→720→780，以及cost的0→2→37；能解释为什么发现冲突仍会返回schedule。

## 当前边界

当前不算往返起点交通，不处理跨午夜，不保证真实数据，重复地点也会被标记。
