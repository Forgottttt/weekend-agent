"""CLI 和网页复用的应用入口，管理会话和本轮权威约束。"""

from dataclasses import asdict
from pathlib import Path
from threading import BoundedSemaphore, Lock

from .agent import TripAgent
from .config import ModelConfig, PROJECT_ROOT
from .memory import SessionStore, select_context
from .planning import DayDemoProvider
from .providers import APIProvider
from .request import TripRequest
from .tools import ToolRegistry, TripTools


class BusyError(RuntimeError):
    pass


class PlanningError(RuntimeError):
    """保留失败任务的计数；否则评测会漏掉失败时已经发生的模型请求。"""

    def __init__(self, message: str, metrics: dict):
        super().__init__(message)
        self.metrics = metrics


class PlanningService:
    def __init__(self, database: Path | None = None):
        self.store = SessionStore(database or PROJECT_ROOT / "outputs" / "sessions.sqlite3")
        self.slots = BoundedSemaphore(2)
        self.lock_guard = Lock()
        self.session_locks: dict[str, Lock] = {}

    def plan(self, values: dict, question: str = "请根据表单规划行程。",
             mode: str = "demo", session_id: str | None = None) -> dict:
        if mode not in ("demo", "live"):
            raise ValueError("模式必须是 demo 或 live")
        if not isinstance(question, str) or not question.strip() or len(question) > 2000:
            raise ValueError("补充要求需要 1–2000 个字符")
        # 先检查请求格式；新建会话前不会把错误输入写入数据库。
        if session_id is None:
            TripRequest.from_dict(values)
        session_id = session_id or self.store.create(mode)
        with self.lock_guard:
            lock = self.session_locks.setdefault(session_id, Lock())
        if not lock.acquire(blocking=False):
            raise BusyError("这个会话正在生成，请等待当前请求完成")
        acquired_slot = False
        try:
            acquired_slot = self.slots.acquire(blocking=False)
            if not acquired_slot:
                raise BusyError("当前生成任务较多，请稍后再试")
            saved = self.store.load(session_id)
            if saved["mode"] != mode:
                raise ValueError("切换运行模式时请新建会话")
            request = TripRequest.from_dict({**saved["request"], **values})
            tools = TripTools(rain=request.rain)
            provider = APIProvider(ModelConfig.from_env()) if mode == "live" else DayDemoProvider(request, tools)
            agent = TripAgent(provider, ToolRegistry(tools), max_rounds=12, max_tool_calls=20)
            prior = saved["messages"]
            if prior:
                agent.messages = select_context(prior)
            retained = len(agent.messages)
            try:
                run = agent.run(question, request)
            except RuntimeError as error:
                usage = getattr(provider, "total_usage", {})
                raise PlanningError(str(error), {
                    "provider_calls": agent.provider_calls, "tool_calls": agent.tool_calls,
                    "model_calls": agent.provider_calls if mode == "live" else 0,
                    "http_attempts": getattr(provider, "http_attempts", 0),
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": usage.get("completion_tokens", 0),
                }) from None
            result = {**asdict(run), "mode": mode, "data_mode": "fictional_demo",
                      "model_calls": run.provider_calls if mode == "live" else 0,
                      "model": provider.config.model if mode == "live" else "offline-rule-v1",
                      "prompt_version": "v0.3.0",
                      "session_id": session_id, "request": request.to_dict(),
                      "context_messages": retained}
            # 完整旧记录加本轮新消息；不把截断后的上下文当成完整历史。
            history = prior + agent.messages[retained:] if prior else agent.messages
            self.store.save(session_id, history, request.to_dict(), result, saved["version"])
            return result
        finally:
            if acquired_slot:
                self.slots.release()
            lock.release()
