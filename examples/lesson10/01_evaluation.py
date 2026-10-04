"""第十课：运行固定评测，区分回归结果与模型效果。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from weekend_agent.evaluation import evaluate

report = evaluate()
print("场景结果：", report["passed"], "/", report["case_count"])
print("返回计划数：", report["planned_count"], "通过最终约束的计划数：", report["validated_plan_count"])
print("硬编码基线满足约束的场景数：", report["baseline_valid_count"])
print("真实模型请求数：", report["model_calls"])
print(report["limitations"])
print("报告路径：", report["report_path"])
