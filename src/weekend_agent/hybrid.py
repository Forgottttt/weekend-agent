"""混合检索与重排。

三件事分开做，因为它们的失败模式不同，混在一起就没法归因：

1. **稠密索引**（`DenseIndex`）：用向量余弦找一个"语义候选集"，
   它能召回词面不重叠但主题相近的文档。
2. **RRF 融合**（`reciprocal_rank_fusion`）：把稀疏（BM25）与稠密两路结果按**名次**
   融合，而不是按分数——两路的分值量纲完全不同，直接加权是常见的错误做法。
   RRF 只用名次，因此不需要调权重。
3. **重排**（`LLMReranker`）：对融合后的候选做一次精排。重排模型能看到
   "查询 + 候选全文"的交互，比双塔式的召回更准，代价是每次查询多一次模型调用。
   这是工业界的标准三段式：召回 → 融合 → 精排。
"""

import json

from .embedding import EmbeddingProvider, cosine
from .jsonio import parse_json_object
from .tools import validate_arguments

RERANK_SCHEMA = {
    "type": "object",
    "properties": {
        "order": {"type": "array", "maxItems": 20, "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
    "required": ["order", "reason"],
    "additionalProperties": False,
}

RERANK_SYSTEM = """你是检索结果重排器。给定一个查询和若干候选资料，请按与查询的相关程度**从高到低**重新排序。

判断标准：
- 资料是否真的能回答查询所问的内容，而不是仅仅出现相同的关键词
- 用词不同但语义相同的资料应当排在前面
- 只提到宽泛主题（如"杭州"）而没有针对性的资料应当排在后面

只输出一个 JSON 对象，不要 Markdown 代码围栏，不要解释文字：
{"order": ["资料ID", ...], "reason": "一句话说明排序依据"}

order 必须包含全部候选 ID，每个 ID 只能出现一次，不能编造 ID。"""


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60) -> list[str]:
    """Reciprocal Rank Fusion：按名次融合多路检索结果。

    每篇文档得分 = Σ 1/(k + rank)。只用名次，因此不需要给不同检索器调权重，
    这也是它比"分数加权求和"更稳妥的原因（BM25 分数与余弦相似度量纲不同）。
    """
    if not isinstance(rankings, list):
        raise ValueError("rankings 必须是列表的列表")
    if type(k) is not int or k < 1:
        raise ValueError("RRF 常数 k 必须是正整数")
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda doc_id: (-scores[doc_id], doc_id))


class DenseIndex:
    """向量检索。文档向量由后端一次性给出或现场计算。"""

    def __init__(self, documents: list[dict], provider: EmbeddingProvider):
        if not documents:
            raise ValueError("稠密索引需要至少一篇文档")
        self.documents = list(documents)
        self.provider = provider
        # 少数后端（如二阶共现）的文档向量与查询向量不在同一构造路径上，
        # 因此优先使用它显式给出的文档向量。
        if hasattr(provider, "document_vectors"):
            self.vectors = provider.document_vectors()
        else:
            self.vectors = provider.embed([d["title"] + " " + d["text"] for d in self.documents])
        if len(self.vectors) != len(self.documents):
            raise ValueError("文档向量数量与文档数量不一致")

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("检索问题不能为空")
        if type(top_k) is not int or top_k < 1:
            raise ValueError("top_k 必须是正整数")
        query_vector = self.provider.embed([query])[0]
        ranked = []
        for document, vector in zip(self.documents, self.vectors):
            score = cosine(query_vector, vector)
            if score > 0:
                ranked.append({**document, "score": round(score, 4)})
        return sorted(ranked, key=lambda item: (-item["score"], item["id"]))[:top_k]


class HybridIndex:
    """稀疏 + 稠密双路召回，RRF 融合。

    两路各自取 `recall_k` 个候选再融合，取融合后的前 `top_k`。
    注意 Python 的关键字参数不能与位置参数重名，这里刻意用了 `recall_k`。
    """

    def __init__(self, sparse_index, dense_index: DenseIndex, rrf_k: int = 60):
        self.sparse = sparse_index
        self.dense = dense_index
        self.rrf_k = rrf_k
        # 融合需要按 id 找回文档，稀疏索引与稠密索引共用同一批文档。
        self.by_id = {document["id"]: document for document in dense_index.documents}

    def fuse(self, query: str, recall_k: int = 10) -> list[dict]:
        """返回融合后的完整候选列表（不截断），供精排使用。"""
        sparse_hits = self.sparse.search(query, min(recall_k, 5))
        dense_hits = self.dense.search(query, recall_k)
        fused = reciprocal_rank_fusion(
            [[hit["id"] for hit in sparse_hits], [hit["id"] for hit in dense_hits]],
            self.rrf_k)
        # 融合结果里可能有只被稠密路召回的文档，统一从索引取回完整内容。
        results = []
        for rank, doc_id in enumerate(fused, start=1):
            document = self.by_id.get(doc_id)
            if document:
                results.append({**document, "score": round(1.0 / (self.rrf_k + rank), 4)})
        return results

    def search(self, query: str, top_k: int = 5, recall_k: int = 10) -> list[dict]:
        if type(top_k) is not int or not 1 <= top_k <= 5:
            raise ValueError("top_k 必须是 1–5 的整数")
        return self.fuse(query, recall_k)[:top_k]


class LLMReranker:
    """用对话模型对候选做精排（LLM-as-reranker）。

    为什么放在最后而不是替代召回：重排要给"查询 × 每个候选"打分，成本随候选数线性增长，
    因此只适合对少量候选做精排；召回阶段仍然用便宜的词法/向量检索。
    """

    name = "llm_rerank"

    def __init__(self, provider, max_candidates: int = 10, strict: bool = True):
        self.provider = provider
        self.max_candidates = max_candidates
        # 严格模式下模型编造候选之外的 ID 就直接报错；
        # 非严格模式丢弃这些 ID 并计数——因为"丢弃"是安全动作，
        # 而记下来的数量本身就是一个有用的可靠性指标。
        self.strict = strict
        self.model_calls = 0
        self.hallucinated_ids: list[str] = []

    def rerank(self, query: str, candidates: list[dict]) -> list[dict]:
        if not candidates:
            return []
        if len(candidates) > self.max_candidates:
            raise ValueError(f"重排候选不能超过 {self.max_candidates} 条")
        listing = "\n".join(f"[{c['id']}] {c['title']}：{c['text'][:120]}" for c in candidates)
        messages = [
            {"role": "system", "content": RERANK_SYSTEM},
            {"role": "user", "content": f"查询：{query}\n\n候选资料：\n{listing}"},
        ]
        self.model_calls += 1
        message = self.provider.complete(messages, [])
        if not isinstance(message, dict) or message.get("tool_calls"):
            raise RuntimeError("重排模型没有返回有效结果")
        verdict = parse_json_object(message.get("content"), "重排结果")
        validate_arguments(verdict, RERANK_SCHEMA, "rerank")
        by_id = {candidate["id"]: candidate for candidate in candidates}
        unknown = [doc_id for doc_id in verdict["order"] if doc_id not in by_id]
        if unknown:
            self.hallucinated_ids.extend(unknown)
            if self.strict:
                raise ValueError(f"重排结果包含候选之外的 ID：{unknown}")
        # 模型可能漏掉部分候选；漏掉的按原顺序补在后面，保证不丢文档。
        ordered = [by_id[doc_id] for doc_id in dict.fromkeys(verdict["order"]) if doc_id in by_id]
        seen = {item["id"] for item in ordered}
        ordered.extend(candidate for candidate in candidates if candidate["id"] not in seen)
        return ordered
