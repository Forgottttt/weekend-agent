"""Agent 循环：请求模型 → 执行工具 → 带回结果 → 再请求模型。

最终方案的交付通道是 `submit_plan` 工具调用，而不是"模型不再调用工具时的那段文字"。
工具调用把方案参数与解释文字分开，减少围栏和前置解释造成的解析问题。
接口返回的 arguments 仍需解析、Schema 和业务校验，不能假设永远是合法 JSON。
文本解析只作为兜底保留，是否被使用记录在
RunResult.submitted_via 上，可以直接度量。
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from time import perf_counter

from .prompts import SYSTEM_PROMPT
from .providers import ChatProvider
from .tools import CONTROL_TOOLS, SUBMIT_PLAN_NAME, ToolRegistry
from .finalize import render_plan, verify_final, verify_plan
from .request import TripRequest


@dataclass
class RunResult:
    answer: str
    events: list[dict]
    provider_calls: int
    tool_calls: int
    duration_seconds: float
    last_check: dict | None
    plan: dict | None = None
    final_checks: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    http_attempts: int = 0
    # "submit_plan" = 走了工具通道；"text" = 走了文本兜底；None = 本轮没有交付方案。
    submitted_via: str | None = None


def _reject_constant(value: str):
    raise ValueError("工具JSON不接受NaN或Infinity")


class _EventLog(list):
    """事件列表：每次 append 都同步推送给流式回调。

    用列表子类而不是在每个 append 处插入回调，是为了让"记录事件"和"推送事件"
    只有一个接触点，将来新增事件类型不会漏推。
    """

    def __init__(self, on_event=None):
        super().__init__()
        # dataclasses.asdict 会用 type(obj)(生成器) 重建列表子类，
        # 也就是把生成器传到 on_event 上，结果事件被静默丢光。
        # 这里把"非可调用参数"当作初始元素处理，让 asdict 往返安全。
        if on_event is not None and not callable(on_event):
            super().extend(on_event)
            on_event = None
        self.on_event = on_event

    def append(self, item) -> None:
        super().append(item)
        if self.on_event is not None:
            self.on_event(item)


class TripAgent:
    def __init__(self, provider: ChatProvider, registry: ToolRegistry,
                 max_rounds: int = 8, max_tool_calls: int = 12, parallel_tools: bool = False):
        self.provider = provider
        self.registry = registry
        self.max_rounds = max_rounds
        self.max_tool_calls = max_tool_calls
        # 同一轮里互不依赖的业务工具可以并发执行。**默认关闭**：
        # 本项目的工具都是本地内存计算（微秒级），实测并发收益可忽略，
        # 打开只增加线程调度与竞态风险。对外部慢工具（HTTP/RPC）才值得开。
        self.parallel_tools = parallel_tools
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.provider_calls = 0
        self.tool_calls = 0

    def run(self, question: str, request: TripRequest | None = None,
            on_event=None) -> RunResult:
        if not question.strip():
            raise ValueError("问题不能为空")
        self.provider_calls = self.tool_calls = 0
        content = question if request is None else ("STRUCTURED_REQUEST:\n" +
                  json.dumps(request.to_dict(), ensure_ascii=False) + "\nUSER_NOTE:\n" + question)
        self.messages.append({"role": "user", "content": content})
        started = perf_counter()
        events = _EventLog(on_event)
        tool_count = 0
        last_check = None
        place_ids: set[str] = set()
        guides: dict[str, dict] = {}
        final_checks = input_tokens = output_tokens = 0

        for round_index in range(1, self.max_rounds + 1):
            self.provider_calls += 1
            message = self.provider.complete(self.messages, self.registry.schemas)
            if not isinstance(message, dict) or message.get("role") != "assistant":
                raise RuntimeError("模型没有返回有效的 assistant 消息")
            usage = getattr(self.provider, "last_usage", {})
            input_tokens += usage.get("prompt_tokens", 0)
            output_tokens += usage.get("completion_tokens", 0)
            calls = message.get("tool_calls") or []
            if not isinstance(calls, list):
                raise RuntimeError("tool_calls 必须是列表")
            ids = set()
            for call in calls:
                if (not isinstance(call, dict) or not isinstance(call.get("id"), str) or not call["id"]
                        or call["id"] in ids or call.get("type") != "function"
                        or not isinstance(call.get("function"), dict)
                        or not isinstance(call["function"].get("name"), str)
                        or not isinstance(call["function"].get("arguments"), str)):
                    raise RuntimeError("工具调用协议异常：ID、类型或函数字段无效")
                ids.add(call["id"])
            self.messages.append(message)

            if not calls:
                if request is None:
                    answer = message.get("content") or "模型没有返回回答。"
                    events.append({"kind": "answer", "content": answer})
                    return self._result(answer, events, round_index, tool_count, started,
                                        last_check, None, final_checks, input_tokens,
                                        output_tokens, None)
                # 模型只说了话，没有调用 submit_plan。仍然尝试文本兜底，
                # 但记录通道，避免"兜底悄悄变成了主通道"却无人察觉。
                answer = message.get("content") or ""
                final_checks += 1
                try:
                    plan = verify_final(answer, request, self.registry, place_ids, guides)
                except (ValueError, TypeError, KeyError) as error:
                    events.append({"kind": "final_rejected", "via": "text",
                                   "error": str(error), "content_preview": answer[:200]})
                    if final_checks >= 3:
                        raise RuntimeError("最终方案连续三次未通过应用校验") from None
                    self.messages.append({"role": "user", "content":
                        "应用最终校验失败：" + str(error) +
                        "。请改用 submit_plan 工具提交方案，不要在 JSON 前后添加解释文字。"})
                    continue
                last_check = plan["checked"]
                events.append({"kind": "final_via_text_fallback"})
                events.append({"kind": "final_validation", "plan": plan, "via": "text"})
                events.append({"kind": "answer", "content": render_plan(plan)})
                return self._result(render_plan(plan), events, round_index, tool_count, started,
                                    last_check, plan, final_checks, input_tokens,
                                    output_tokens, "text")

            if tool_count + len(calls) > self.max_tool_calls:
                self._remove_pending_message()
                raise RuntimeError("达到工具调用上限；请缩小问题范围后重试。")

            # 可选并发：先把互不依赖的业务工具跑完，再按原顺序处理结果，
            # 这样事件顺序、白名单收集与计数口径都保持与串行一致。
            parallel_results = self._execute_parallel(calls) if self.parallel_tools else {}

            for index, call in enumerate(calls):
                name = call["function"]["name"]
                raw = call["function"]["arguments"]
                try:
                    arguments = json.loads(raw, parse_constant=_reject_constant)
                except (ValueError, TypeError):
                    result = {"ok": False, "error": "工具参数不是有效的 JSON"}
                    tool_count += 1
                    self.tool_calls = tool_count
                    events.append({"kind": "tool", "round": round_index, "name": name,
                                   "arguments": raw, "result": result})
                    self._answer_tool(call["id"], result)
                    continue

                if name == SUBMIT_PLAN_NAME:
                    if request is None:
                        result = {"ok": False, "error": "本轮没有结构化约束，不需要提交方案"}
                        tool_count += 1
                        self.tool_calls = tool_count
                        events.append({"kind": "tool", "round": round_index, "name": name,
                                       "arguments": arguments, "result": result})
                        self._answer_tool(call["id"], result)
                        continue
                    # final_checks 统计的是"终审尝试次数"，成功那次也要计入，
                    # 否则 final_checks>1 无法正确表示"发生过修复轮"。
                    final_checks += 1
                    try:
                        self.registry.validate_call(name, arguments)
                        plan = verify_plan(arguments, request, self.registry, place_ids, guides)
                    except (ValueError, TypeError, KeyError) as error:
                        events.append({"kind": "final_rejected", "via": SUBMIT_PLAN_NAME,
                                       "error": str(error)})
                        self._answer_tool(call["id"], {"ok": False, "error": str(error)})
                        if final_checks >= 3:
                            raise RuntimeError("最终方案连续三次未通过应用校验") from None
                        continue
                    # 提交成功。接口要求每个 tool_call 都必须有配对结果，
                    # 因此本次提交和同批次后续调用都要补上结果，
                    # 否则下一轮带着未配对的 tool_calls 会被接口直接拒绝。
                    self._answer_tool(call["id"], {"ok": True, "data": {
                        "accepted": True, "status": plan["status"]}})
                    for rest in calls[index + 1:]:
                        self._answer_tool(rest["id"], {"ok": False, "error": "本轮已提交方案，未执行该调用"})
                    last_check = plan["checked"]
                    events.append({"kind": "final_validation", "plan": plan, "via": SUBMIT_PLAN_NAME})
                    events.append({"kind": "answer", "content": render_plan(plan)})
                    return self._result(render_plan(plan), events, round_index, tool_count, started,
                                        last_check, plan, final_checks, input_tokens,
                                        output_tokens, SUBMIT_PLAN_NAME)

                result = parallel_results.get(index)
                if result is None:
                    result = self.registry.execute(name, arguments)
                tool_count += 1
                self.tool_calls = tool_count
                if name == "check_itinerary":
                    last_check = result.get("data") if result.get("ok") else None
                if result.get("ok") and name == "search_places":
                    place_ids.update(place["id"] for place in result["data"]["places"])
                if result.get("ok") and name == "search_guides":
                    guides.update((d["id"], d) for d in result["data"]["documents"])
                events.append({"kind": "tool", "round": round_index,
                               "name": name, "arguments": arguments, "result": result})
                self._answer_tool(call["id"], result)
        raise RuntimeError("达到模型调用轮数上限；本轮没有生成最终答案。")

    def _execute_parallel(self, calls: list[dict]) -> dict[int, dict]:
        """并发执行同一轮里互不依赖的业务工具，返回 {调用下标: 结果}。

        只处理参数能解析的调用；参数损坏的调用留给串行路径处理，
        以保持原有的错误语义与事件内容。`submit_plan` 是控制工具，必须串行。
        """
        tasks: dict[int, tuple[str, dict]] = {}
        for index, call in enumerate(calls):
            name = call["function"]["name"]
            if name in CONTROL_TOOLS:
                continue
            try:
                arguments = json.loads(call["function"]["arguments"],
                                       parse_constant=_reject_constant)
            except (ValueError, TypeError):
                continue
            tasks[index] = (name, arguments)
        if len(tasks) < 2:
            # 只有一个可并发的调用时，起线程池反而更慢。
            return {}
        results: dict[int, dict] = {}
        with ThreadPoolExecutor(max_workers=min(4, len(tasks))) as pool:
            futures = {pool.submit(self.registry.execute, name, args): index
                       for index, (name, args) in tasks.items()}
            for future in as_completed(futures):
                results[futures[future]] = future.result()
        return results

    def _answer_tool(self, call_id: str, result: dict) -> None:
        self.messages.append({"role": "tool", "tool_call_id": call_id,
                              "content": json.dumps(result, ensure_ascii=False, allow_nan=False)})

    def _result(self, answer, events, round_index, tool_count, started, last_check,
                plan, final_checks, input_tokens, output_tokens, submitted_via) -> RunResult:
        return RunResult(answer, events, round_index, tool_count,
                         round(perf_counter() - started, 3), last_check, plan, final_checks,
                         input_tokens, output_tokens,
                         getattr(self.provider, "http_attempts", 0), submitted_via)

    def _remove_pending_message(self) -> None:
        # 移除尚未执行的工具请求，避免下一轮带着不完整的请求／结果配对。
        self.messages.pop()
