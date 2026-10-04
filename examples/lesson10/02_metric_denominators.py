"""一个刻意包含失败的小表，训练分母判断；数字不是实测结果。"""
rows = [
    {"expected": "planned", "actual": "planned", "checked": True},
    {"expected": "planned", "actual": "error", "checked": False},
    {"expected": "planned", "actual": "no_plan", "checked": False},
    {"expected": "no_plan", "actual": "no_plan", "checked": False},
]
passed = sum(row["expected"] == row["actual"] for row in rows)
planned = [row for row in rows if row["actual"] == "planned"]
print("教学假设数据，总用例数：", len(rows))
print("状态符合预期：", passed, "/", len(rows))
print("返回计划中的校验通过率：", sum(row["checked"] for row in planned), "/", len(planned))
print("如果只看最后一项，会遗漏第二条报错与第三条漏解。")
print("永远返回no_plan时的通过数：", sum(row["expected"] == "no_plan" for row in rows))
