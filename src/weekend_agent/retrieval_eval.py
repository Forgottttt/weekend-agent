"""检索评测：用同一套合成标注查询比较 BM25 与 TF-IDF 余弦基线。

报告里的数字只反映两种词法方法在这套自动生成数据上的相对排序差异，
不代表真实城市数据或真实用户查询上的检索质量。详见报告里的 limitations 字段。
"""

import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path

from .chunking import ChunkedIndex, chunk_documents
from .config import PROJECT_ROOT
from .embedding import ExpansionEmbedding
from .hybrid import DenseIndex, HybridIndex, LLMReranker
from .retrieval import GuideIndex, tokenize

LIMITATIONS = ("合成语料与自动标注：语料由 scripts/build_corpus.py 用固定随机种子生成，"
               "相关文档标签来自生成时的主题归属，不是人工撰写或人工标注；"
               "查询只有正例、没有负例和分级相关性，因此 recall@k 与 MRR 只反映 "
               "BM25 与 TF-IDF 在这套合成数据上的相对表现，不能推断真实检索质量，"
               "也不能用来证明某一种方法在真实场景更好。")


class TfidfIndex:
    """纯标准库的 TF-IDF + 余弦相似度基线，search 接口与 GuideIndex 保持一致。"""

    def __init__(self, path: Path | None = None, documents: list[dict] | None = None):
        if documents is not None:
            self.documents = list(documents)
        else:
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


class CallableIndex:
    """把「查询 → 结果列表」的函数包装成带 search 方法的索引，便于统一评测。"""

    def __init__(self, search):
        self.search = search


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


# ---------------------------------------------------------------------------
# 切片对照实验：长文档语料上「整篇检索」vs「切片检索」
# ---------------------------------------------------------------------------

def _score_parents(retrieved_ids: list[str], relevant: list[str],
                   parent_map: dict[str, str] | None) -> dict:
    """把检索到的片段或文档映射回父文档，再去重、计算文档级指标。

    去重是必要的：切片检索很容易让同一篇长文档的多个片段占满前 k 个位置，
    如果不去重，文档级 recall 会被系统性高估。
    """
    parents: list[str] = []
    for doc_id in retrieved_ids:
        parent = parent_map[doc_id] if parent_map else doc_id
        if parent not in parents:
            parents.append(parent)
    found = [parent for parent in parents if parent in relevant]
    return {
        "retrieved": retrieved_ids,
        "parents": parents,
        "found": len(found),
        "hit": bool(found),
        "recall": round(len(found) / len(relevant), 4) if relevant else 0.0,
        "reciprocal_rank": round(1 / (parents.index(found[0]) + 1), 4) if found else 0.0,
    }


def evaluate_chunking(top_k: int = 5, output_dir: Path | None = None,
                      size: int = 300, overlaps: tuple[float, ...] = (0.0, 0.15, 0.30)) -> dict:
    """在长文档语料上对比切片策略，指标为**文档级** recall@k。

    对照组是「整篇作为一篇文档检索」；实验组按给定重叠比例切片，
    检索到片段后映射回父文档再算指标（这就是真实系统里切片检索的用法）。
    """
    if type(top_k) is not int or not 1 <= top_k <= 5:
        raise ValueError("top_k 必须是 1–5 的整数")
    data_dir = Path(__file__).parent / "data"
    long_docs = json.loads((data_dir / "guides_long.json").read_text(encoding="utf-8"))
    cases = json.loads((data_dir / "chunk_cases.json").read_text(encoding="utf-8"))

    variants: list[tuple[str, object, dict[str, str] | None, int]] = [
        ("whole_document", GuideIndex(documents=long_docs), None, len(long_docs)),
    ]
    for overlap in overlaps:
        chunks = chunk_documents(long_docs, size, overlap)
        parent_map = {chunk["id"]: chunk["parent_id"] for chunk in chunks}
        # 对照组：直接取 top-k 片段，命中后映射回父文档（这是最朴素的切片检索）。
        variants.append((f"chunk_flat_{int(overlap * 100)}pct",
                         GuideIndex(documents=chunks), parent_map, len(chunks)))
        # 实验组：超额召回后按父文档去重，返回 top-k 篇不同文档。
        variants.append((f"chunk_dedup_{int(overlap * 100)}pct",
                         ChunkedIndex(long_docs, size, overlap), None, len(chunks)))

    rows = []
    for case in cases:
        row: dict = {"id": case["id"], "query": case["query"], "relevant": case["relevant"]}
        for name, index, parent_map, _ in variants:
            hits = index.search(case["query"], top_k)
            row[name] = _score_parents([hit["id"] for hit in hits], case["relevant"], parent_map)
        rows.append(row)

    summary = {}
    for name, _, _, unit_count in variants:
        recalls = [row[name]["recall"] for row in rows]
        ranks = [row[name]["reciprocal_rank"] for row in rows]
        summary[name] = {
            "unit_count": unit_count,
            "recall_at_k": round(sum(recalls) / len(rows), 4) if rows else 0.0,
            "mrr": round(sum(ranks) / len(rows), 4) if rows else 0.0,
            "hits": sum(1 for row in rows if row[name]["hit"]),
        }

    now = datetime.now()
    report = {
        "dataset": "chunk_cases_v1_synthetic",
        "corpus": f"guides_long.json（{len(long_docs)} 篇长文档，脚本合成）",
        "case_count": len(rows),
        "corpus_size": len(long_docs),
        "chunk_size": size,
        "overlaps": list(overlaps),
        "top_k": top_k,
        "generated_at": now.isoformat(timespec="seconds"),
        "variants": summary,
        "limitations": ("长文档由脚本把多篇短文档按固定窗口拼接而成，不是真实长文；"
                        "相关性标注直接继承自短文档级标注，因此这里的数字只用于"
                        "比较切片策略之间的**相对**差异，不能推断真实语料上的检索质量。"),
        "cases": rows,
    }
    target_dir = output_dir or PROJECT_ROOT / "outputs"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / now.strftime("chunking_%Y%m%d_%H%M%S_%f.json")
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
                      encoding="utf-8")
    report["report_path"] = str(target)
    return report


# ---------------------------------------------------------------------------
# 检索方法对比：稀疏 / 稠密 / 混合 / 混合+重排
# ---------------------------------------------------------------------------

def evaluate_methods(top_k: int = 5, output_dir: Path | None = None,
                     rerank_provider=None, embedding_provider=None,
                     recall_k: int = 10) -> dict:
    """在同一批标注查询上对比四种检索策略。

    对应工业界的三段式：召回（稀疏/稠密）→ 融合（RRF）→ 精排（LLM）。
    `rerank_provider` 为空时跳过重排，其余三种方法都是离线可跑的。
    """
    if type(top_k) is not int or not 1 <= top_k <= 5:
        raise ValueError("top_k 必须是 1–5 的整数")
    data_dir = Path(__file__).parent / "data"
    guides_path = data_dir / "guides.json"
    cases = json.loads((data_dir / "retrieval_cases.json").read_text(encoding="utf-8"))

    documents = json.loads(guides_path.read_text(encoding="utf-8"))
    sparse = GuideIndex(guides_path)
    # 不传后端就用零依赖的二阶共现实现；传了就用它（例如真实的 embedding API）。
    backend = embedding_provider or ExpansionEmbedding(documents)
    dense = DenseIndex(documents, backend)
    hybrid = HybridIndex(sparse, dense)

    methods = {
        "bm25_sparse": ("BM25 稀疏检索", lambda q, k: sparse.search(q, k)),
        "dense": (f"稠密检索（{backend.name}）", lambda q, k: dense.search(q, k)),
        "hybrid_rrf": ("稀疏 + 稠密 RRF 融合", lambda q, k: hybrid.search(q, k, recall_k)),
    }
    reranker = None
    if rerank_provider is not None:
        # 评测用非严格模式：模型偶尔会编造候选之外的 ID，丢弃即可（不能增加内容），
        # 但要把数量记下来——这本身是重排环节的可靠性指标。
        reranker = LLMReranker(rerank_provider, strict=False)
        methods["hybrid_rerank"] = (
            "融合候选经 LLM 精排",
            lambda q, k: reranker.rerank(
                q, hybrid.fuse(q, recall_k)[:reranker.max_candidates])[:k])

    rows = []
    for case in cases:
        relevant = list(case["relevant"])
        row: dict = {"id": case["id"], "query": case["query"], "relevant": relevant}
        for name, (_, search) in methods.items():
            row[name] = _run(CallableIndex(search), case["query"], relevant, top_k)
        rows.append(row)

    summary = {name: {"label": label, **_summarize(rows, name, top_k)}
               for name, (label, _) in methods.items()}
    now = datetime.now()
    report = {
        "dataset": "retrieval_cases_v1_synthetic",
        "corpus": f"guides.json（{len(documents)} 篇）",
        "case_count": len(rows),
        "corpus_size": len(documents),
        "top_k": top_k,
        "recall_k": recall_k,
        "embedding_backend": backend.name,
        "rerank_used": rerank_provider is not None,
        "rerank_model_calls": reranker.model_calls if reranker else 0,
        "rerank_hallucinated_ids": sorted(set(reranker.hallucinated_ids)) if reranker else [],
        "generated_at": now.isoformat(timespec="seconds"),
        "methods": summary,
        "limitations": ("语料与标注均为脚本合成的自动标注；查询只有正例、没有负例与分级相关性。"
                        f"稠密后端为 {backend.name}；若它不是语义 embedding 模型，"
                        "则不能代表真实向量检索的效果，四个数字只在彼此之间可比。"),
        "cases": rows,
    }
    target_dir = output_dir or PROJECT_ROOT / "outputs"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / now.strftime("methods_%Y%m%d_%H%M%S_%f.json")
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
                      encoding="utf-8")
    report["report_path"] = str(target)
    return report
