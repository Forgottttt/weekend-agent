"""CLI 和网页复用的应用入口，管理会话和本轮权威约束。"""

from dataclasses import asdict
from pathlib import Path
from threading import BoundedSemaphore, Lock

from .agent import TripAgent
from .config import ModelConfig, PROJECT_ROOT
from .longterm import MemoryStore, summarize_history
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
        # 长期记忆：结构化事实 + 旧回合摘要（见 longterm.py）。
        self.memory = MemoryStore(self.store)
        self.slots = BoundedSemaphore(2)
        self.lock_guard = Lock()
        self.session_locks: dict[str, Lock] = {}

    def plan(self, values: dict, question: str = "请根据表单规划行程。",
             mode: str = "demo", session_id: str | None = None,
             on_event=None, summarize: bool = False) -> dict:
        """生成一份方案。on_event 用于流式推送进度，不影响任何判定逻辑。

        summarize=True 时，把超出上下文窗口的旧回合压缩成摘要存起来（需要一次额外模型调用）；
        默认关闭，因为事实类记忆已经由结构化的 request 免费提供。
        """
        def notify(payload: dict) -> None:
            if on_event is not None:
                on_event(payload)

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
            tools = TripTools(rain=request.rain, include_meal=request.include_meal)
            provider = APIProvider(ModelConfig.from_env()) if mode == "live" else DayDemoProvider(request, tools)
            # max_rounds 是主要的成本闸门；工具上限按实测的探索深度校准（12 轮内
            # 正常探索约 20–28 次调用），设得过紧会让正常规划被误判成失败。
            agent = TripAgent(provider, ToolRegistry(tools), max_rounds=12, max_tool_calls=28)
            notify({"kind": "phase", "phase": "session", "session_id": session_id, "mode": mode,
                    "model": provider.config.model if mode == "live" else "offline-rule-v1"})
            prior = saved["messages"]
            if prior:
                agent.messages = select_context(prior)
                # 长期记忆里的旧回合摘要插在系统提示之后，让模型在不膨胀上下文的前提下
                # 仍然知道更早的偏好与已排除方案。
                remembered = self.memory.load_summary(session_id)
                if remembered:
                    agent.messages.insert(1, {
                        "role": "system",
                        "content": "本会话较早内容的摘要（供参考，不得据此放宽当前表单约束）：\n"
                                   + remembered["summary"]})
            retained = len(agent.messages)
            try:
                run = agent.run(question, request, on_event=on_event)
            except RuntimeError as error:
                usage = getattr(provider, "total_usage", {})
                raise PlanningError(str(error), {
                    "provider_calls": agent.provider_calls, "tool_calls": agent.tool_calls,
                    "model_calls": agent.provider_calls if mode == "live" else 0,
                    "http_attempts": getattr(provider, "http_attempts", 0),
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": usage.get("completion_tokens", 0),
                }) from None
            payload = asdict(run)
            # 显式还原成普通列表：不依赖 asdict 对列表子类的重建行为。
            payload["events"] = list(run.events)
            result = {**payload, "mode": mode, "data_mode": "fictional_demo",
                      "model_calls": run.provider_calls if mode == "live" else 0,
                      "model": provider.config.model if mode == "live" else "offline-rule-v1",
                      "prompt_version": "v0.3.0",
                      "session_id": session_id, "request": request.to_dict(),
                      "context_messages": retained}
            # 完整旧记录加本轮新消息；不把截断后的上下文当成完整历史。
            history = prior + agent.messages[retained:] if prior else agent.messages
            # 先补齐 result 的全部字段再落盘：返回给调用方的字典必须与保存的快照完全一致，
            # 否则网页实时显示与事后恢复会不一致。
            # 事实直接取自已经通过校验的 TripRequest，不需要额外模型调用；
            # 与旧值不同时自动覆盖并保留历史版本。
            result["memory_changes"] = self.memory.remember(
                session_id, request.to_dict(), source="form")
            if summarize and mode == "live":
                try:
                    created = summarize_history(history, provider, keep_turns=3)
                except (RuntimeError, ValueError) as error:
                    # 摘要失败不应让整轮规划白做，记录下来即可。
                    result["summary_error"] = str(error)
                else:
                    if created:
                        summary_text, cutoff = created
                        self.memory.save_summary(session_id, summary_text, cutoff)
                        result["summary_updated"] = True
            self.store.save(session_id, history, request.to_dict(), result, saved["version"])
            return result
        finally:
            if acquired_slot:
                self.slots.release()
            lock.release()
