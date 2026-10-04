"""五轮完整历史与近期上下文；临时数据库不覆盖正式会话。"""
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from weekend_agent.memory import select_context
from weekend_agent.service import PlanningService

with TemporaryDirectory() as folder:
    service = PlanningService(Path(folder) / "lesson.sqlite3")
    session_id = None
    for turn in range(1, 6):
        result = service.plan({"group_size": turn}, session_id=session_id)
        session_id = result["session_id"]
        saved = service.store.load(session_id)
        print("回合", turn, "版本", saved["version"], "完整消息数", len(saved["messages"]),
              "输入给本轮来源的旧上下文数", result["context_messages"])
    context = select_context(saved["messages"], max_turns=2)
    starts = [m for m in context if m["role"] == "user" and m["content"].startswith("STRUCTURED_REQUEST:\n")]
    calls = [c["id"] for m in context for c in m.get("tool_calls", [])]
    replies = [m["tool_call_id"] for m in context if m["role"] == "tool"]
    print("最近回合数：", len(starts), "；请求/结果仍按顺序配对：", calls == replies)
    print("错误示范：直接取最后两条的角色：", [m["role"] for m in saved["messages"][-2:]])
    try:
        select_context(saved["messages"], max_characters=10)
    except ValueError as error:
        print("上限过小时：", error)
