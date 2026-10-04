"""先作答再看提示，自评记录不会被当成面试能力测量。"""

import json
import random
from datetime import datetime
from pathlib import Path

from .config import PROJECT_ROOT


def practice(topic: str = "tools", count: int = 3, seed: int = 42):
    bank = json.loads((Path(__file__).parent / "data" / "interview.json").read_text(encoding="utf-8"))
    candidates = [q for q in bank if topic == "all" or q["topic"] == topic]
    if not candidates:
        raise ValueError("没有该主题。可选：" + ", ".join(sorted({q["topic"] for q in bank})))
    questions = random.Random(seed).sample(candidates, min(count, len(candidates)))
    records = []
    print("先用自己的话回答，再看答案。评分由你自评；不会自动推断是否已掌握。")
    for question in questions:
        print(f"\n{question['id']} · {question['question']}")
        answer = input("你的回答（单行）：")
        print("参考思路：", question["answer"])
        print("代码证据：", question["evidence"])
        print("追问：", question["followup"])
        followup = input("追问回答（单行）：")
        print("追问提示：", question["followup_hint"])
        print("自评：0=不会；1=会背；2=能结合代码解释；3=能改代码并说明边界。")
        score = input("分数 0–3：").strip()
        records.append({"id": question["id"], "answer": answer, "followup": followup,
                        "self_score": int(score) if score in ("0", "1", "2", "3") else None})
    folder = PROJECT_ROOT / "outputs" / "practice"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / datetime.now().strftime("practice_%Y%m%d_%H%M%S_%f.json")
    target.write_text(json.dumps({"topic": topic, "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("练习记录已保存：", target)
