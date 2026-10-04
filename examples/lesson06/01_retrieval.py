"""第六课：观察中文字符二元组和 BM25 检索结果。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from weekend_agent.retrieval import GuideIndex, tokenize

print("雨天室内 →", tokenize("雨天室内"))
index = GuideIndex()
for query in ["雨天室内", "每人预算交通", "unmatchedxyz"]:
    print("\n查询：", query)
    documents = index.search(query, top_k=2)
    print("返回数量：", len(documents))
    for document in documents:
        print(document["id"], document["title"], "相关分数", document["score"])
