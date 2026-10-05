"""长文档切片：按句子边界切分，并在相邻切片间保留重叠区域。

**为什么要重叠**：一句话如果正好被切断在切片边界上，相邻两个切片都拿不到完整语义，
检索就会用错误的碎片去匹配。重叠让边界附近的句子至少在一个切片里是完整的。

**重叠比例怎么定**：工业界常见 10%–20%，但这个数字不该照抄。本项目把它做成参数，
并在评测里对比 0% / 15% / 30% 三档，用 recall 决定取值（见 `retrieval_eval.py`）。
默认 15% 只是起点，不是结论。

切片粒度同样是权衡：切片越大，单块语义越完整但越容易被无关内容稀释；
越小，匹配越精准但越容易丢失上下文。评测里一并对比。
"""

# 中文句末标点与换行都视作句子边界。
_SENTENCE_END = "。！？；!?;\n"


def split_sentences(text: str) -> list[str]:
    """按中英文句末标点切句，保留标点，丢弃空白片段。"""
    if not isinstance(text, str):
        raise ValueError("待切分文本必须是字符串")
    sentences: list[str] = []
    buffer = ""
    for char in text:
        buffer += char
        if char in _SENTENCE_END:
            if buffer.strip():
                sentences.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        sentences.append(buffer.strip())
    return sentences


def _tail(text: str, limit: int) -> str:
    """取 text 末尾不超过 limit 个字符的完整句子，用于构造重叠区。"""
    if limit <= 0:
        return ""
    sentences = split_sentences(text)
    kept: list[str] = []
    total = 0
    for sentence in reversed(sentences):
        if kept and total + len(sentence) > limit:
            break
        kept.insert(0, sentence)
        total += len(sentence)
    overlap = "".join(kept)
    # 单句本身就超过 limit 时，退回按字符截尾，避免重叠区反而比切片还长。
    return overlap[-limit:] if len(overlap) > limit else overlap


def chunk_text(text: str, size: int = 300, overlap: float = 0.15) -> list[str]:
    """把一段长文本切成若干带重叠的片段。

    size 是目标字符数；**片段长度上界是 `size + int(size * overlap)`**——
    因为新片段可能以重叠前缀开头，再加一个几乎满额的句子。
    单句本身超过 size 时会被硬切，不会产生无法切分的片段。
    overlap 是重叠比例，取值 [0, 0.5)。
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("切片文本不能为空")
    if type(size) is not int or size < 40:
        raise ValueError("切片大小必须是不小于 40 的整数")
    if not isinstance(overlap, (int, float)) or not 0 <= overlap < 0.5:
        raise ValueError("重叠比例必须在 [0, 0.5) 之间")

    # 先把超长单句硬切，避免单个句子永远无法进入任何片段。
    pieces: list[str] = []
    for sentence in split_sentences(text):
        while len(sentence) > size:
            pieces.append(sentence[:size])
            sentence = sentence[size:]
        if sentence:
            pieces.append(sentence)

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) > size:
            chunks.append(current)
            current = _tail(current, int(size * overlap))
        current += piece
    if current.strip():
        chunks.append(current)
    return chunks


def chunk_documents(documents: list[dict], size: int = 300, overlap: float = 0.15) -> list[dict]:
    """把文档列表切成带父文档信息的片段列表。

    每个片段保留 `parent_id` 与 `chunk_index`，并生成形如 `<doc_id>#<n>` 的片段 id，
    这样检索结果既能定位到片段，也能回指原文档（评测用文档级相关性判定）。
    """
    if not isinstance(documents, list):
        raise ValueError("documents 必须是列表")
    chunks: list[dict] = []
    for document in documents:
        for index, piece in enumerate(chunk_text(document["text"], size, overlap)):
            chunks.append({
                "id": f"{document['id']}#{index}",
                "parent_id": document["id"],
                "chunk_index": index,
                "title": document["title"],
                "text": piece,
            })
    return chunks


class ChunkedIndex:
    """按片段建索引、按**文档**返回结果。

    为什么不能直接把 top-k 片段当结果返回：同一篇长文档的多个片段很容易占满前 5 个位置
    （实测在 30% 重叠下有 32/44 条查询出现这种情况），去重后能覆盖的不同文档数
    从 4.93 掉到 3.95，文档级召回反而下降。

    做法是**超额召回再按父文档去重**：先取 `top_k × oversample` 个片段，
    按父文档去重后返回 top_k 篇不同文档。这样既保留了切片带来的排序精度，
    又不会因为同源片段挤占名额而损失召回。
    """

    def __init__(self, documents: list[dict], size: int = 300, overlap: float = 0.15,
                 oversample: int = 6):
        from .retrieval import GuideIndex
        if type(oversample) is not int or oversample < 1:
            raise ValueError("oversample 必须是正整数")
        self.documents = list(documents)
        self.by_parent = {document["id"]: document for document in self.documents}
        self.chunks = chunk_documents(self.documents, size, overlap)
        self.index = GuideIndex(documents=self.chunks)
        self.oversample = oversample

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        if type(top_k) is not int or not 1 <= top_k <= 5:
            raise ValueError("top_k 必须是 1–5 的整数")
        wanted = top_k * self.oversample
        ordered: list[dict] = []
        seen: set[str] = set()
        for hit in self.index.rank(query):
            parent_id = hit["parent_id"]
            if parent_id in seen:
                continue
            seen.add(parent_id)
            ordered.append({**self.by_parent[parent_id], "score": hit["score"],
                            "matched_chunk": hit["id"]})
            if len(ordered) >= top_k:
                break
            if len(seen) >= wanted:
                break
        return ordered
