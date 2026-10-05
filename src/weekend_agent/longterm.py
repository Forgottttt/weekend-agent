"""长期记忆：结构化事实 + 滚动摘要。

分两层，因为两者的代价完全不同：

- **结构化事实**（`MemoryStore.remember` / `recall`）：把用户条件作为带时间戳的事实存下来，
  冲突时新值覆盖旧值但保留历史版本。**零额外模型调用**——事实直接来自已经校验过的
  `TripRequest`，不需要再问模型一次。

- **滚动摘要**（`summarize_history`）：把超出上下文窗口的旧回合压缩成要点。
  这一步需要一次模型调用，因此默认不启用，只在上层显式要求时执行。

为什么要分开：如果为了"记住用户预算 200"就去调一次模型，成本与延迟都不划算；
而"记住用户说过什么"本来就有结构化来源，不该花模型的钱。
"""

import json
from datetime import datetime, timezone
from typing import Any

# 允许写入长期记忆的槽位：只存稳定、可复用的偏好与约束。
FACT_KEYS = ("city", "budget_per_person", "group_size", "tags", "indoor",
             "rain", "start_time", "end_time", "include_meal")

SUMMARY_SYSTEM = """把下面这段较早的行程规划对话压缩成简短要点，用中文，不超过 200 字。

只保留会影响后续决策的信息：
- 用户确认过的条件（预算、人数、时间、兴趣、室内外、是否用餐）
- 已经排除或失败过的方案及原因
- 用户明确表达的偏好或禁忌

不要保留寒暄、工具调用的原始返回、以及已经过时的中间尝试。"""


class MemoryStore:
    """在现有 SQLite 里新增两张表，记录事实与摘要。

    只建新表、不改动已有表结构，所以对既有数据库是纯增量且可回退的。
    """

    def __init__(self, store):
        self.store = store
        with store.connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS memory_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
                source TEXT NOT NULL, updated_at TEXT NOT NULL, superseded_by INTEGER)""")
            connection.execute("""CREATE TABLE IF NOT EXISTS memory_summaries (
                session_id TEXT PRIMARY KEY, summary TEXT NOT NULL,
                covered_until INTEGER NOT NULL, updated_at TEXT NOT NULL)""")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def remember(self, session_id: str, facts: dict[str, Any], source: str = "form") -> list[dict]:
        """写入事实；与当前值不同的键会覆盖旧值，旧记录标记 superseded_by。

        返回本次发生变化的键，便于上层展示"这次记住了什么"。
        """
        if not isinstance(facts, dict):
            raise ValueError("facts 必须是字典")
        changes: list[dict] = []
        current = self.recall(session_id)
        with self.store.connect() as connection:
            for key, value in facts.items():
                if key not in FACT_KEYS or value is None:
                    continue
                encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
                previous = current.get(key)
                if previous is not None and json.dumps(previous, ensure_ascii=False,
                                                       sort_keys=True) == encoded:
                    continue
                cursor = connection.execute(
                    "INSERT INTO memory_facts(session_id,key,value,source,updated_at) VALUES(?,?,?,?,?)",
                    (session_id, key, encoded, source, self._now()))
                new_id = cursor.lastrowid
                if previous is not None:
                    connection.execute(
                        "UPDATE memory_facts SET superseded_by=? WHERE session_id=? AND key=? "
                        "AND superseded_by IS NULL AND id<>?", (new_id, session_id, key, new_id))
                changes.append({"key": key, "value": value, "previous": previous})
        return changes

    def recall(self, session_id: str) -> dict[str, Any]:
        """返回每个键当前生效的值（未被取代的最新记录）。"""
        with self.store.connect() as connection:
            rows = connection.execute(
                "SELECT key,value FROM memory_facts WHERE session_id=? AND superseded_by IS NULL "
                "ORDER BY id", (session_id,)).fetchall()
        facts: dict[str, Any] = {}
        for key, value in rows:
            try:
                facts[key] = json.loads(value)
            except (TypeError, ValueError):
                continue
        return facts

    def history(self, session_id: str, key: str | None = None) -> list[dict]:
        """返回全部历史版本（含已被取代的），用于回溯"这个条件是什么时候改的"。"""
        sql = ("SELECT id,key,value,source,updated_at,superseded_by FROM memory_facts "
               "WHERE session_id=?")
        params: list[Any] = [session_id]
        if key is not None:
            sql += " AND key=?"
            params.append(key)
        with self.store.connect() as connection:
            rows = connection.execute(sql + " ORDER BY id", params).fetchall()
        return [{"id": row[0], "key": row[1], "value": json.loads(row[2]), "source": row[3],
                 "updated_at": row[4], "superseded": row[5] is not None} for row in rows]

    def save_summary(self, session_id: str, summary: str, covered_until: int) -> None:
        with self.store.connect() as connection:
            connection.execute(
                "INSERT INTO memory_summaries(session_id,summary,covered_until,updated_at) "
                "VALUES(?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET "
                "summary=excluded.summary, covered_until=excluded.covered_until, "
                "updated_at=excluded.updated_at",
                (session_id, summary, covered_until, self._now()))

    def load_summary(self, session_id: str) -> dict | None:
        with self.store.connect() as connection:
            row = connection.execute(
                "SELECT summary,covered_until,updated_at FROM memory_summaries WHERE session_id=?",
                (session_id,)).fetchone()
        if row is None:
            return None
        return {"summary": row[0], "covered_until": row[1], "updated_at": row[2]}


def summable_prefix(messages: list[dict], keep_turns: int = 3) -> tuple[list[dict], int]:
    """把「可以压缩的旧回合」与「必须原样保留的近期回合」分开。

    回合以 `STRUCTURED_REQUEST:` 开头的 user 消息为界；返回 (旧回合, 起点下标)。
    不拆分单个回合，避免破坏 assistant/tool 消息配对。
    """
    starts = [index for index, item in enumerate(messages)
              if item.get("role") == "user"
              and isinstance(item.get("content"), str)
              and item["content"].startswith("STRUCTURED_REQUEST:\n")]
    if len(starts) <= keep_turns:
        return [], 0
    cutoff = starts[-keep_turns]
    return messages[starts[0]:cutoff], cutoff


def summarize_history(messages: list[dict], provider, keep_turns: int = 3) -> tuple[str, int] | None:
    """把旧回合压缩成要点。返回 (摘要, 覆盖到的下标)；没有可压缩内容时返回 None。"""
    old, cutoff = summable_prefix(messages, keep_turns)
    if not old:
        return None
    transcript = []
    for item in old:
        role = item.get("role")
        content = item.get("content")
        if role == "tool" or not isinstance(content, str):
            # 工具返回往往是长文本，压缩时只保留"调过什么"，不复制内容。
            if item.get("tool_calls"):
                transcript.append("助手发起了工具调用")
            continue
        transcript.append(f"{'用户' if role == 'user' else '助手'}：{content[:500]}")
    if not transcript:
        return None
    message = provider.complete(
        [{"role": "system", "content": SUMMARY_SYSTEM},
         {"role": "user", "content": "\n".join(transcript[-40:])}], [])
    if not isinstance(message, dict) or message.get("tool_calls"):
        raise RuntimeError("摘要模型没有返回有效结果")
    summary = (message.get("content") or "").strip()
    if not summary:
        raise RuntimeError("摘要模型返回了空摘要")
    return summary, cutoff
