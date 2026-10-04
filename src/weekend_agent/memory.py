"""完整记录留在 SQLite；模型上下文只取最近若干个完整回合。"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


def select_context(messages: list[dict], max_turns: int = 3, max_characters: int = 40000) -> list[dict]:
    if not messages:
        return []
    system = messages[:1]
    starts = [i for i, item in enumerate(messages) if item["role"] == "user"
              and item["content"].startswith("STRUCTURED_REQUEST:\n")]
    if not starts:
        return messages
    selected = starts[-max_turns:]
    while selected:
        context = system + messages[selected[0]:]
        if len(json.dumps(context, ensure_ascii=False)) <= max_characters:
            return context
        selected.pop(0)
    # 不拆开单个回合中的 assistant/tool 消息，不假装字符数是 token 数。
    raise ValueError("最近一个完整回合过长，请新建会话；当前未实现摘要压缩")


def public_messages(messages: list[dict]) -> list[dict]:
    return [{key: value for key, value in item.items() if key != "reasoning_content"} for item in messages]


class SessionStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, mode TEXT NOT NULL, messages TEXT NOT NULL,
                request TEXT NOT NULL, result TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create(self, mode: str) -> str:
        session_id = uuid4().hex
        with self.connect() as connection:
            connection.execute("INSERT INTO sessions(id, mode, messages, request, result) VALUES(?,?,?,?,?)",
                               (session_id, mode, "[]", "{}", "{}"))
        return session_id

    def load(self, session_id: str) -> dict:
        with self.connect() as connection:
            row = connection.execute("SELECT mode,messages,request,result,version FROM sessions WHERE id=?",
                                     (session_id,)).fetchone()
        if row is None:
            raise ValueError("会话不存在，请新建会话")
        return {"id": session_id, "mode": row[0], "messages": json.loads(row[1]),
                "request": json.loads(row[2]), "result": json.loads(row[3]), "version": row[4]}

    def save(self, session_id: str, messages: list[dict], request: dict, result: dict, version: int) -> None:
        values = [json.dumps(value, ensure_ascii=False, allow_nan=False)
                  for value in (public_messages(messages), request, result)]
        with self.connect() as connection:
            cursor = connection.execute("""UPDATE sessions SET messages=?,request=?,result=?,version=version+1,
                updated_at=CURRENT_TIMESTAMP WHERE id=? AND version=?""", (*values, session_id, version))
            if cursor.rowcount != 1:
                raise RuntimeError("会话已被其他请求更新，请重新加载后再试")
