"""检索栈的离线测试：切片、稠密后端、RRF 融合、LLM 重排。

这里验证的是**接口契约与边界**，不是检索效果；效果由 `retrieval_eval` 用标注集度量。
"""

import json
import unittest

from weekend_agent.chunking import ChunkedIndex, chunk_documents, chunk_text, split_sentences
from weekend_agent.embedding import ExpansionEmbedding, cosine
from weekend_agent.hybrid import DenseIndex, HybridIndex, LLMReranker, reciprocal_rank_fusion
from weekend_agent.retrieval import GuideIndex
from weekend_agent.tools import ToolRegistry, TripTools

DOCS = [
    {"id": "a1", "title": "雨天室内安排", "text": "下雨时优先选择室内展览馆。书店也是不错的选择。"},
    {"id": "a2", "title": "拍照与营业时间", "text": "拍照活动要留意营业时段。展览馆在十点开放。"},
    {"id": "a3", "title": "美食与午餐", "text": "美食兴趣可以匹配面馆和家常菜馆。午餐要留出一小时。"},
]


class FakeEmbedding:
    """确定性假向量：用字符出现情况当特征，仅用于验证接口与排序逻辑。"""

    name = "fake"

    def embed(self, texts):
        return [[float(text.count(ch)) for ch in "雨室内拍照美食午"] for text in texts]


class ChunkingTests(unittest.TestCase):
    def test_split_sentences_keeps_punctuation(self):
        self.assertEqual(split_sentences("第一句。第二句！第三句？"),
                         ["第一句。", "第二句！", "第三句？"])

    def test_chunk_respects_size_and_produces_overlap(self):
        text = "".join(f"这是第{i}句测试文本。" for i in range(20))
        size, overlap = 60, 0.3
        chunks = chunk_text(text, size=size, overlap=overlap)
        self.assertGreater(len(chunks), 1)
        # 上界见 chunk_text 的 docstring：size 加上重叠前缀。
        self.assertTrue(all(len(c) <= size + int(size * overlap) for c in chunks))
        # 重叠意味着相邻片段有公共子串，而不是首尾相接。
        self.assertTrue(any(chunks[i][-6:] in chunks[i + 1] for i in range(len(chunks) - 1)))

    def test_zero_overlap_has_no_shared_tail(self):
        text = "".join(f"第{i}句。" for i in range(40))
        chunks = chunk_text(text, size=40, overlap=0.0)
        for i in range(len(chunks) - 1):
            self.assertFalse(chunks[i][-4:] and chunks[i][-4:] in chunks[i + 1])

    def test_oversized_single_sentence_is_hard_split(self):
        chunks = chunk_text("甲" * 250, size=100, overlap=0.15)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= 100 + 15 for c in chunks))

    def test_invalid_arguments_are_rejected(self):
        for size, overlap in ((10, 0.1), (100, 0.6), (100, -0.1)):
            with self.assertRaises(ValueError):
                chunk_text("测试文本。", size, overlap)
        with self.assertRaises(ValueError):
            chunk_text("   ")

    def test_chunk_documents_keeps_parent_link(self):
        chunks = chunk_documents(DOCS, size=40, overlap=0.0)
        self.assertTrue(all("#" in c["id"] and c["parent_id"] in ("a1", "a2", "a3")
                            for c in chunks))


class ChunkedIndexTests(unittest.TestCase):
    def test_returns_distinct_documents_not_chunks(self):
        # 相关句集中在同一篇文档里时，朴素 top-k 片段会被同源片段占满；
        # ChunkedIndex 必须返回不同的父文档。
        long_doc = {"id": "L1", "title": "合辑",
                    "text": "雨天室内优先。书店也可以。" * 12}
        other = {"id": "L2", "title": "无关", "text": "美食与午餐安排。" * 12}
        index = ChunkedIndex([long_doc, other], size=50, overlap=0.2)
        hits = index.search("雨天室内", top_k=3)
        ids = [hit["id"] for hit in hits]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids[0], "L1")
        self.assertIn("matched_chunk", hits[0])

    def test_invalid_top_k_rejected(self):
        index = ChunkedIndex(DOCS, size=40, overlap=0.0)
        for bad in (0, 6, "2"):
            with self.assertRaises(ValueError):
                index.search("雨天", bad)


class EmbeddingTests(unittest.TestCase):
    def test_cosine_bounds_and_zero_vectors(self):
        self.assertAlmostEqual(cosine([1, 0], [1, 0]), 1.0)
        self.assertAlmostEqual(cosine([1, 0], [0, 1]), 0.0)
        self.assertEqual(cosine([0, 0], [1, 1]), 0.0)
        with self.assertRaises(ValueError):
            cosine([1, 2], [1])

    def test_expansion_embedding_is_deterministic_and_shaped(self):
        first = ExpansionEmbedding(DOCS)
        second = ExpansionEmbedding(DOCS)
        self.assertEqual(first.document_vectors(), second.document_vectors())
        self.assertEqual(len(first.document_vectors()), len(DOCS))
        self.assertEqual(len(first.embed(["雨天"])[0]), len(DOCS))

    def test_expansion_rejects_empty_corpus(self):
        with self.assertRaises(ValueError):
            ExpansionEmbedding([])


class FusionTests(unittest.TestCase):
    def test_rrf_prefers_documents_ranked_high_by_both(self):
        fused = reciprocal_rank_fusion([["x", "y", "z"], ["y", "x", "w"]])
        self.assertEqual(fused[:2], ["x", "y"])
        self.assertIn("w", fused)

    def test_rrf_rejects_bad_k(self):
        with self.assertRaises(ValueError):
            reciprocal_rank_fusion([["a"]], k=0)


class DenseAndHybridTests(unittest.TestCase):
    def test_dense_index_uses_injected_provider(self):
        index = DenseIndex(DOCS, FakeEmbedding())
        hits = index.search("雨天室内", top_k=2)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["id"], "a1")

    def test_hybrid_returns_documents_from_both_paths(self):
        sparse = GuideIndex(documents=DOCS)
        hybrid = HybridIndex(sparse, DenseIndex(DOCS, FakeEmbedding()))
        hits = hybrid.search("雨天室内", top_k=3)
        self.assertTrue(hits)
        self.assertTrue(all("id" in hit for hit in hits))
        self.assertLessEqual(len(hits), 3)

    def test_hybrid_fuse_returns_more_candidates_than_search(self):
        sparse = GuideIndex(documents=DOCS)
        hybrid = HybridIndex(sparse, DenseIndex(DOCS, FakeEmbedding()))
        self.assertGreaterEqual(len(hybrid.fuse("雨天", 10)), len(hybrid.search("雨天", 1)))


class RerankerTests(unittest.TestCase):
    def provider(self, content=None, tool_calls=None):
        class Provider:
            def complete(self, messages, tools):
                return {"role": "assistant", "content": content, "tool_calls": tool_calls}
        return Provider()

    def test_rerank_reorders_and_keeps_all_candidates(self):
        content = json.dumps({"order": ["a3", "a1", "a2"], "reason": "测试"})
        reranker = LLMReranker(self.provider(content))
        ordered = reranker.rerank("雨天", list(DOCS))
        self.assertEqual([item["id"] for item in ordered], ["a3", "a1", "a2"])
        self.assertEqual(reranker.model_calls, 1)

    def test_missing_candidates_are_appended_not_dropped(self):
        content = json.dumps({"order": ["a3"], "reason": "只排了一条"})
        reranker = LLMReranker(self.provider(content))
        ordered = reranker.rerank("雨天", list(DOCS))
        self.assertEqual(len(ordered), 3)
        self.assertEqual(ordered[0]["id"], "a3")

    def test_invented_id_is_error_in_strict_mode_and_counted_otherwise(self):
        content = json.dumps({"order": ["不存在", "a1"], "reason": "编造"})
        with self.assertRaisesRegex(ValueError, "候选之外"):
            LLMReranker(self.provider(content)).rerank("雨天", list(DOCS))
        lenient = LLMReranker(self.provider(content), strict=False)
        ordered = lenient.rerank("雨天", list(DOCS))
        self.assertEqual(len(ordered), 3)
        self.assertEqual(lenient.hallucinated_ids, ["不存在"])

    def test_tool_calls_or_bad_json_are_rejected(self):
        with self.assertRaises(RuntimeError):
            LLMReranker(self.provider(None, [{"id": "x"}])).rerank("雨天", list(DOCS))
        with self.assertRaises(ValueError):
            LLMReranker(self.provider("我觉得都不错")).rerank("雨天", list(DOCS))

    def test_too_many_candidates_rejected(self):
        reranker = LLMReranker(self.provider(json.dumps({"order": [], "reason": "x"})),
                               max_candidates=2)
        with self.assertRaises(ValueError):
            reranker.rerank("雨天", list(DOCS))

    def test_markdown_fence_is_tolerated(self):
        content = "```json\n" + json.dumps({"order": ["a1"], "reason": "x"}) + "\n```"
        self.assertEqual(LLMReranker(self.provider(content)).rerank("雨天", list(DOCS))[0]["id"], "a1")


if __name__ == "__main__":
    unittest.main()


class CorpusEmbedding:
    """与语料等长的确定性假后端，用于验证「有/无/坏」三条检索路径。"""

    name = "corpus"
    def __init__(self, documents):
        self.vectors = [[float(len(d["text"]) % 7), float(d["text"].count("雨"))]
                        for d in documents]
    def embed(self, texts):
        return [[float(len(t) % 7), float(t.count("雨"))] for t in texts]
    def document_vectors(self):
        return self.vectors


class BrokenEmbedding:
    name = "broken"
    def embed(self, texts):
        raise RuntimeError("连接被拒绝")


class RetrievalDegradationTests(unittest.TestCase):
    """检索后端的自动降级：缺配置、后端故障、语料不匹配都必须降级而非报错。"""

    @classmethod
    def setUpClass(cls):
        cls.corpus = GuideIndex().documents

    def search(self, tools):
        return ToolRegistry(tools).execute("search_guides", {"query": "雨天室内", "top_k": 2})

    def test_without_backend_uses_lexical_only(self):
        result = self.search(TripTools())
        self.assertEqual(result["data"]["retrieval_method"], "bm25_character_bigrams")
        self.assertNotIn("retrieval_degraded", result["data"])

    def test_working_backend_switches_to_hybrid(self):
        result = self.search(TripTools(embedding_provider=CorpusEmbedding(self.corpus)))
        self.assertEqual(result["data"]["retrieval_method"], "hybrid_rrf(bm25+dense)")
        self.assertNotIn("retrieval_degraded", result["data"])

    def test_broken_backend_degrades_with_visible_reason(self):
        result = self.search(TripTools(embedding_provider=BrokenEmbedding()))
        self.assertEqual(result["data"]["retrieval_method"], "bm25_character_bigrams")
        self.assertIn("已降级为 BM25", result["data"]["retrieval_degraded"])
        # 降级后必须仍然拿得到结果，而不是整体失败。
        self.assertTrue(result["data"]["documents"])

    def test_mismatched_corpus_degrades_instead_of_misaligning(self):
        result = self.search(TripTools(embedding_provider=CorpusEmbedding(self.corpus[:20])))
        self.assertEqual(result["data"]["retrieval_method"], "bm25_character_bigrams")
        self.assertIn("数量不一致", result["data"]["retrieval_degraded"])

    def test_degradation_happens_once_and_is_remembered(self):
        tools = TripTools(embedding_provider=BrokenEmbedding())
        first = self.search(tools)
        second = self.search(tools)
        self.assertIn("已降级为 BM25", first["data"]["retrieval_degraded"])
        # 第二次仍是同一原因，且不再重复尝试坏后端。
        self.assertIn("已降级为 BM25", second["data"]["retrieval_degraded"])
        self.assertIsNone(tools.embedding_provider)
