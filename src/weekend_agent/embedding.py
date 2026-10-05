"""可插拔的向量化后端。

提供两种实现，接口一致，可以互换：

- `ApiEmbeddingProvider`：调用 OpenAI 兼容的 `/embeddings` 接口。
  智谱、阿里、百度、本地 Ollama 都兼容这个协议，因此换供应商只改配置。
  这是**生产路径**——只有真正的语义模型才能解决近义词问题。

- `ExpansionEmbedding`：纯标准库的离线后端，不需要任何外部服务。
  它用**二阶共现**构造稠密向量：先算文档两两的词法相似度矩阵 S，
  再把第 i 篇文档表示成 S 的第 i 行（n 维稠密向量）。
  查询向量是"查询与各文档的相似度"，落在同一空间里，因此可以直接算余弦。

  为什么这样能跨过词面差异：如果查询命中文档 A，而文档 B 与 A 高度相似，
  那么 B 的向量在位置 A 上也有高分，两者余弦会被抬起来。这就是
  文档扩展（document expansion）的思路，与 LSA 同源。

  **但它仍然是从词频出发的**：如果查询词与目标文档之间连"二阶"联系都没有
  （语料里没有任何中间文档把两者关联起来），它同样无能为力。这一点在评测里
  会如实体现，不会为了让数字好看而调整。
"""

import json
import math
import re
from collections import Counter
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .retrieval import tokenize


class EmbeddingProvider(Protocol):
    """把文本批量转成向量。两个实现必须可互换。"""

    name: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        """返回与输入等长的向量列表。"""
        ...


def cosine(left: list[float], right: list[float]) -> float:
    """余弦相似度；任一方为零向量时返回 0。"""
    if len(left) != len(right):
        raise ValueError("向量维度不一致")
    dot = norm_left = norm_right = 0.0
    for a, b in zip(left, right):
        dot += a * b
        norm_left += a * a
        norm_right += b * b
    if norm_left <= 0 or norm_right <= 0:
        return 0.0
    return dot / math.sqrt(norm_left * norm_right)


class ExpansionEmbedding:
    """纯标准库的离线稠密后端（二阶共现 / 文档扩展）。"""

    name = "expansion_cooccurrence"

    def __init__(self, documents: list[dict], max_features: int = 4000):
        if not documents:
            raise ValueError("向量化需要至少一篇文档")
        self.documents = documents
        counts = [Counter(tokenize(d["title"] + " " + d["text"])) for d in documents]
        # 低频词没有统计意义，只保留出现次数最高的若干特征，避免矩阵过大。
        frequency = Counter(word for count in counts for word in count)
        self.vocabulary = {word for word, _ in frequency.most_common(max_features)}
        total = len(documents)
        self.idf = {word: math.log((1 + total) / (1 + frequency[word])) + 1
                    for word in self.vocabulary}
        self.vectors = [self._weigh(count) for count in counts]
        self.norms = [math.sqrt(sum(v * v for v in vector.values())) for vector in self.vectors]
        # 文档两两相似度：n×n，n 是文档数。本项目量级（数百）完全放得下。
        self.similarity = [[self._sparse_cosine(i, j) for j in range(total)]
                           for i in range(total)]

    def _weigh(self, count: Counter) -> dict[str, float]:
        return {word: (1 + math.log(count[word])) * self.idf[word]
                for word in count if word in self.vocabulary}

    def _sparse_cosine(self, i: int, j: int) -> float:
        if i == j:
            return 0.0
        left, right = self.vectors[i], self.vectors[j]
        if len(left) > len(right):
            left, right = right, left
        dot = sum(value * right.get(word, 0.0) for word, value in left.items())
        if dot <= 0 or self.norms[i] <= 0 or self.norms[j] <= 0:
            return 0.0
        return dot / (self.norms[i] * self.norms[j])

    def _query_profile(self, text: str) -> list[float]:
        """查询与各文档的词法相似度，作为查询在同空间的表示。"""
        query = self._weigh(Counter(tokenize(text)))
        norm = math.sqrt(sum(v * v for v in query.values()))
        if norm <= 0:
            return [0.0] * len(self.documents)
        profile = []
        for vector, doc_norm in zip(self.vectors, self.norms):
            if doc_norm <= 0:
                profile.append(0.0)
                continue
            dot = sum(value * vector.get(word, 0.0) for word, value in query.items())
            profile.append(dot / (norm * doc_norm) if dot > 0 else 0.0)
        return profile

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._query_profile(text) for text in texts]

    def document_vectors(self) -> list[list[float]]:
        return [list(row) for row in self.similarity]


class ApiEmbeddingProvider:
    """OpenAI 兼容的 /embeddings 后端（智谱 / 阿里 / 百度 / 本地 Ollama 均可用）。"""

    def __init__(self, base_url: str, api_key: str, model: str,
                 timeout_seconds: int = 60, max_retries: int = 1):
        if not base_url.startswith("https://") and not base_url.startswith("http://127.0.0.1"):
            raise ValueError("embedding 基础地址必须是 https，或本机 http://127.0.0.1")
        if not model.strip():
            raise ValueError("embedding 模型名不能为空")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.name = f"api:{model}"
        self.http_attempts = 0

    def __repr__(self) -> str:  # 不泄漏密钥
        return f"ApiEmbeddingProvider(base_url={self.base_url!r}, model={self.model!r})"

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = json.dumps({"model": self.model, "input": texts}, ensure_ascii=False).encode("utf-8")
        request = Request(self.base_url + "/embeddings", data=payload, method="POST",
                          headers={"Content-Type": "application/json",
                                   "Authorization": f"Bearer {self.api_key}"})
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                self.http_attempts += 1
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    body = json.loads(response.read().decode("utf-8"))
                data = sorted(body["data"], key=lambda item: item.get("index", 0))
                vectors = [item["embedding"] for item in data]
                if len(vectors) != len(texts):
                    raise ValueError("embedding 返回条数与输入不一致")
                return vectors
            except HTTPError as error:
                code = error.code
                error.close()
                hint = {401: "embedding 密钥无效", 404: "embedding 接口或模型不存在",
                        429: "embedding 请求过于频繁"}.get(code, "embedding 服务不可用")
                last_error = RuntimeError(f"embedding 服务返回 HTTP {code}：{hint}")
                if attempt >= self.max_retries or (code != 429 and not 500 <= code <= 599):
                    break
            except (URLError, TimeoutError, KeyError, TypeError, ValueError) as error:
                last_error = RuntimeError(f"embedding 调用失败：{error}")
                if attempt >= self.max_retries:
                    break
        raise last_error or RuntimeError("embedding 调用没有完成")
