"""检索评测：用同一套合成标注查询比较 BM25 与 TF-IDF 余弦基线。

报告里的数字只反映两种词法方法在这套自动生成数据上的相对排序差异，
不代表真实城市数据或真实用户查询上的检索质量。详见报告里的 limitations 字段。
"""

import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path

from .config import PROJECT_ROOT
from .retrieval import GuideIndex, tokenize

LIMITATIONS = ("合成语料与自动标注：语料由 scripts/build_corpus.py 用固定随机种子生成，"
               "相关文档标签来自生成时的主题归属，不是人工撰写或人工标注；"
               "查询只有正例、没有负例和分级相关性，因此 recall@k 与 MRR 只反映 "
               "BM25 与 TF-IDF 在这套合成数据上的相对表现，不能推断真实检索质量，"
               "也不能用来证明某一种方法在真实场景更好。")


class TfidfIndex:
    """纯标准库的 TF-IDF + 余弦相似度基线，search 接口与 GuideIndex 保持一致。"""

    def __init__(self, path: Path | None = None):
        path = path or Path(__file__).parent / "data" / "guides.json"
        self.documents = json.loads(path.read_text(encoding="utf-8"))
        counts = [Counter(tokenize(document["title"] + " " + document["text"]))
                  for document in self.documents]
        total = len(self.documents)
        document_frequency = Counter(word for count in counts for word in count)
        self.idf = {word: math.log((1 + total) / (1 + frequency)) + 1
                    for word, frequency in document_frequency.items()}
        # 语料里没出现过的查询词按 df=0 处理，只影响查询向量长度、不影响文档排序。
        self.default_idf = math.log(1 + total) + 1
        self.vectors = [self._weigh(count) for count in counts]
        self.norms = [math.sqrt(sum(value * value for value in vector.values()))
                      for vector in self.vectors]

    def _weigh(self, count: Counter) -> dict:
        """对数词频乘以逆文档频率；未在语料中出现的词用 default_idf。"""
        return {word: (1 + math.log(frequency)) * self.idf.get(word, self.default_idf)
                for word, frequency in count.items()}

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        if not isinstance(query, str) or not query.strip() or len(query) > 300:
            raise ValueError("检索问题需要 1–300 个字符")
        if type(top_k) is not int or not 1 <= top_k <= 5:
            raise ValueError("top_k 必须是 1–5 的整数")
        query_vector = self._weigh(Counter(tokenize(query)))
        query_norm = math.sqrt(sum(value * value for value in query_vector.values()))
        if not query_norm:
            return []
        ranked = []
        for document, vector, norm in zip(self.documents, self.vectors, self.norms):
            if not norm:
                continue
            dot = sum(value * vector.get(word, 0.0) for word, value in query_vector.items())
            if dot <= 0:
                continue
            ranked.append({**document, "score": round(dot / (query_norm * norm), 4)})
        return sorted(ranked, key=lambda item: (-item["score"], item["id"]))[:top_k]


def _summarize(rows: list[dict], method: str, top_k: int) -> dict:
    """把一个方法的逐条结果汇总成 recall@k、MRR 和命中查询数。"""
    recalls = [row[method]["recall"] for row in rows]
    reciprocal_ranks = [row[method]["reciprocal_rank"] for row in rows]
    count = len(rows)
    return {
        "recall_at_k": round(sum(recalls) / count, 4) if count else 0.0,
        "mrr": round(sum(reciprocal_ranks) / count, 4) if count else 0.0,
        "hits": sum(1 for row in rows if row[method]["hit"]),
        "misses": [row["id"] for row in rows if not row[method]["hit"]],
        "top_k": top_k,
    }


def _run(index, query: str, relevant: list[str], top_k: int) -> dict:
    """跑一条查询：命中数、名次、recall 和 reciprocal rank。"""
    retrieved = [document["id"] for document in index.search(query, top_k)]
    ranks = [retrieved.index(doc_id) + 1 for doc_id in relevant if doc_id in retrieved]
    found = len(ranks)
    return {
        "retrieved": retrieved,
        "found": found,
        "ranks": ranks,
        "hit": bool(ranks),
        "recall": round(found / len(relevant), 4) if relevant else 0.0,
        "reciprocal_rank": round(1 / min(ranks), 4) if ranks else 0.0,
    }


def evaluate_retrieval(top_k: int = 5, output_dir: Path | None = None) -> dict:
    """在合成标注集上比较 BM25(GuideIndex) 与 TF-IDF(TfidfIndex)，写盘并返回报告。"""
    if type(top_k) is not int or not 1 <= top_k <= 5:
        # GuideIndex.search 只接受 1–5，评测保持一致。
        raise ValueError("top_k 必须是 1–5 的整数")
    data_dir = Path(__file__).parent / "data"
    guides_path = data_dir / "guides.json"
    cases = json.loads((data_dir / "retrieval_cases.json").read_text(encoding="utf-8"))
    bm25 = GuideIndex(guides_path)
    tfidf = TfidfIndex(guides_path)

    rows = []
    for case in cases:
        relevant = list(case["relevant"])
        rows.append({
            "id": case["id"],
            "query": case["query"],
            "relevant": relevant,
            "bm25": _run(bm25, case["query"], relevant, top_k),
            "tfidf": _run(tfidf, case["query"], relevant, top_k),
        })

    now = datetime.now()
    report = {
        "dataset": "retrieval_cases_v1_synthetic",
        "corpus": "guides.json（6 篇手写 + 195 篇脚本生成）",
        "case_count": len(rows),
        "corpus_size": len(bm25.documents),
        "top_k": top_k,
        "generated_at": now.isoformat(timespec="seconds"),
        "bm25": _summarize(rows, "bm25", top_k),
        "tfidf": _summarize(rows, "tfidf", top_k),
        "limitations": LIMITATIONS,
        "cases": rows,
    }
    target_dir = output_dir or PROJECT_ROOT / "outputs"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / now.strftime("retrieval_%Y%m%d_%H%M%S_%f.json")
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
                      encoding="utf-8")
    report["report_path"] = str(target)
    return report
