"""小型 BM25 词法检索。中文用字符二元组，不使用 embedding 或向量数据库。"""

import json
import math
import re
from collections import Counter
from pathlib import Path


def tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    for segment in re.findall(r"[\u4e00-\u9fff]+", text):
        tokens.extend(segment[i:i + 2] for i in range(len(segment) - 1))
        if len(segment) == 1:
            tokens.append(segment)
    return tokens


class GuideIndex:
    def __init__(self, path: Path | None = None, documents: list[dict] | None = None):
        if documents is not None:
            # 允许直接传文档列表，便于对切片结果等临时语料建索引。
            self.documents = list(documents)
        else:
            path = path or Path(__file__).parent / "data" / "guides.json"
            self.documents = json.loads(path.read_text(encoding="utf-8"))
        self.counts = [Counter(tokenize(d["title"] + " " + d["text"])) for d in self.documents]
        self.lengths = [sum(count.values()) for count in self.counts]
        self.average_length = sum(self.lengths) / max(1, len(self.lengths))
        self.document_frequency = Counter(word for count in self.counts for word in count)

    def rank(self, query: str) -> list[dict]:
        """返回所有得分大于零的文档，按分数排序（不截断）。

        对外接口 `search` 只给 top_k；片段检索需要先拿到更多候选再按父文档去重，
        因此把打分与截断拆开。
        """
        if not isinstance(query, str) or not query.strip() or len(query) > 300:
            raise ValueError("检索问题需要 1–300 个字符")
        words = set(tokenize(query))
        ranked = []
        for document, count, length in zip(self.documents, self.counts, self.lengths):
            score = 0.0
            for word in words:
                frequency = count[word]
                if not frequency:
                    continue
                df = self.document_frequency[word]
                idf = math.log(1 + (len(self.documents) - df + 0.5) / (df + 0.5))
                denominator = frequency + 1.2 * (1 - 0.75 + 0.75 * length / self.average_length)
                score += idf * frequency * 2.2 / denominator
            if score > 0:
                ranked.append({**document, "score": round(score, 4)})
        return sorted(ranked, key=lambda item: (-item["score"], item["id"]))

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        if type(top_k) is not int or not 1 <= top_k <= 5:
            raise ValueError("top_k 必须是 1–5 的整数")
        return self.rank(query)[:top_k]
