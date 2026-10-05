"""生成长文档语料与配套查询集，用于验证切片与重叠比例。

**为什么需要它**：现有 201 篇语料每篇只有 51–188 字，本身就是"一个切片"，
根本用不到切片逻辑，也无法证明切片有没有用。这里把若干篇短文档按固定窗口
合成一批约 1500 字的长文档，再把原查询的相关标注映射到长文档上，
就能做一组干净的对照实验：

    不切片（整篇一向量）  vs  切片（含重叠）  →  文档级 recall@5

预期现象（也是要验证的）：长文档里如果只有一小段相关内容，整篇表示会被
大量无关内容稀释，从而漏召回；切片后相关内容能独立参与竞争，召回率上升。

脚本确定性、幂等：重复运行结果逐字节相同。
"""

import json
import random
from pathlib import Path

SEED = 20261005
DATA_DIR = Path(__file__).resolve().parents[1] / "src" / "weekend_agent" / "data"
GUIDES = DATA_DIR / "guides.json"
CASES = DATA_DIR / "retrieval_cases.json"
LONG_GUIDES = DATA_DIR / "guides_long.json"
CHUNK_CASES = DATA_DIR / "chunk_cases.json"

WINDOW = 10   # 每篇长文档由多少篇短文档合成
STRIDE = 3    # 窗口滑动步长，决定长文档数量与重叠度


def build_long_documents(short_docs: list[dict]) -> tuple[list[dict], dict[str, list[str]]]:
    """按滑动窗口合成长文档，返回长文档列表与「短文档 id → 长文档 id 列表」的映射。"""
    long_docs: list[dict] = []
    membership: dict[str, list[str]] = {}
    index = 0
    while index + WINDOW <= len(short_docs):
        window = short_docs[index:index + WINDOW]
        long_id = f"L{len(long_docs) + 1:04d}"
        # 每篇正文清晰分段，段首保留原标题，便于人工核对与检索定位。
        body = "\n".join(f"【{doc['title']}】{doc['text']}" for doc in window)
        long_docs.append({
            "id": long_id,
            "title": f"合辑：{window[0]['title']} 等 {len(window)} 篇",
            "text": body,
            "source_ids": [doc["id"] for doc in window],
        })
        for doc in window:
            membership.setdefault(doc["id"], []).append(long_id)
        index += STRIDE
    return long_docs, membership


def build_cases(cases: list[dict], membership: dict[str, list[str]]) -> list[dict]:
    """把短文档级的相关标注映射到长文档级；没有映射到任何长文档的查询丢弃。"""
    mapped = []
    for case in cases:
        relevant = sorted({long_id for doc_id in case["relevant"]
                           for long_id in membership.get(doc_id, [])})
        if not relevant:
            continue
        mapped.append({"id": case["id"], "query": case["query"], "relevant": relevant,
                       "source_relevant": list(case["relevant"])})
    return mapped


def main() -> None:
    random.seed(SEED)   # 保留种子以便将来引入随机化时仍可复现
    short_docs = json.loads(GUIDES.read_text(encoding="utf-8"))
    cases = json.loads(CASES.read_text(encoding="utf-8"))

    long_docs, membership = build_long_documents(short_docs)
    mapped = build_cases(cases, membership)

    LONG_GUIDES.write_text(json.dumps(long_docs, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    CHUNK_CASES.write_text(json.dumps(mapped, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")

    lengths = [len(doc["text"]) for doc in long_docs]
    print(f"长文档 {len(long_docs)} 篇，正文 {min(lengths)}–{max(lengths)} 字，"
          f"平均 {sum(lengths) // len(lengths)} 字")
    print(f"映射查询 {len(mapped)} 条（原 {len(cases)} 条）")
    print(f"写入 {LONG_GUIDES.name} 与 {CHUNK_CASES.name}")


if __name__ == "__main__":
    main()
