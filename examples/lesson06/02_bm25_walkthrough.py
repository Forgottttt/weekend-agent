"""把真实索引的一份文档拆成逐词贡献，核对最终分数。"""
import math
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from weekend_agent.retrieval import GuideIndex, tokenize

index = GuideIndex()
query = "雨天室内"
words = sorted(set(tokenize(query)))
print("查询词项：", words)
position = next(i for i, doc in enumerate(index.documents) if doc["id"] == "g_rain")
count, length = index.counts[position], index.lengths[position]
print("文档g_rain长度：", length, "；平均文档长度：", round(index.average_length, 4))
score = 0.0
for word in words:
    tf, df = count[word], index.document_frequency[word]
    contribution = 0.0
    if tf:
        idf = math.log(1 + (len(index.documents) - df + 0.5) / (df + 0.5))
        denominator = tf + 1.2 * (1 - 0.75 + 0.75 * length / index.average_length)
        contribution = idf * tf * 2.2 / denominator
    score += contribution
    print(word, "tf=", tf, "df=", df, "贡献=", round(contribution, 4))
ranked = index.search(query, 5)
actual = next(doc["score"] for doc in ranked if doc["id"] == "g_rain")
assert round(score, 4) == actual
print("手工分项求和=实际工具分数：", actual)
print("排序：", [(doc["id"], doc["score"]) for doc in ranked])
print("无重合词项：", index.search("unmatchedxyz", 3))
