"""第八课：保存完整历史，恢复会话，只向模型提供近期上下文。"""
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from weekend_agent.memory import select_context
from weekend_agent.service import PlanningService

with TemporaryDirectory() as folder:
    database = Path(folder) / "session.sqlite3"
    first = PlanningService(database).plan({"group_size": 3})
    service = PlanningService(database)  # 新对象模拟服务重启。
    second = service.plan({"rain": True, "budget_per_person": 80}, session_id=first["session_id"])
    saved = service.store.load(first["session_id"])
    print("保留的人数：", second["request"]["group_size"])
    print("新的预算与雨天：", second["request"]["budget_per_person"], second["request"]["rain"])
    print("完整历史条数：", len(saved["messages"]))
    print("只取最近1回合：", len(select_context(saved["messages"], max_turns=1)))
    print("数据库版本：", saved["version"])
