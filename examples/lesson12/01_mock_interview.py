"""第十二课：--list 只看题目；无此参数时进入交互练习。"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from weekend_agent.interview import practice

if "--list" in sys.argv:
    path = Path(__file__).resolve().parents[2] / "src/weekend_agent/data/interview.json"
    bank = json.loads(path.read_text(encoding="utf-8"))
    print("题库共", len(bank), "题。先回答再看提示，评分由自己完成。")
    for question in bank:
        if question["lesson"] == 12:
            print(question["id"], question["question"])
else:
    practice(topic="project", count=3)
