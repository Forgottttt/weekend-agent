"""Agent 循环：请求模型 → 执行工具 → 带回结果 → 再请求模型。"""

import json
from dataclasses import dataclass
from time import perf_counter

from .prompts import SYSTEM_PROMPT
from .providers import ChatProvider
from .tools import ToolRegistry
from .finalize import render_plan, verify_final
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


class TripAgent:
    def __init__(self, provider: ChatProvider, registry: ToolRegistry,
                 max_rounds: int = 8, max_tool_calls: int = 12):
        self.provider = provider
        self.registry = registry
        self.max_rounds = max_rounds
        self.max_tool_calls = max_tool_calls
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.provider_calls = 0
        self.tool_calls = 0

    def run(self, question: str, request: TripRequest | None = None) -> RunResult:
        if not question.strip():
            raise ValueError("问题不能为空")
        self.provider_calls = self.tool_calls = 0
        content = question if request is None else ("STRUCTURED_REQUEST:\n" +
                  json.dumps(request.to_dict(), ensure_ascii=False) + "\nUSER_NOTE:\n" + question)
        self.messages.append({"role": "user", "content": content})
        started = perf_counter()
        events: list[dict] = []
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
                answer = message.get("content") or "模型没有返回回答。"
                plan = None
                if request is not None:
                    final_checks += 1
                    try:
                        plan = verify_final(answer, request, self.registry, place_ids, guides)
                    except (ValueError, TypeError, KeyError) as error:
                        # 记录被拒原文的开头，否则事后无法判断是格式问题还是业务冲突。
                        events.append({"kind": "final_rejected", "error": str(error),
                                       "content_preview": answer[:200]})
                        if final_checks >= 3:
                            raise RuntimeError("最终方案连续三次未通过应用校验") from None
                        self.messages.append({"role": "user", "content":
                            "应用最终校验失败：" + str(error) + "。请修正，按要求返回 JSON，不要修改权威约束。"})
                        continue
                    answer = render_plan(plan)
                    last_check = plan["checked"]
                    events.append({"kind": "final_validation", "plan": plan})
                events.append({"kind": "answer", "content": answer})
                return RunResult(answer, events, round_index, tool_count,
                                 round(perf_counter() - started, 3), last_check, plan, final_checks,
                                 input_tokens, output_tokens, getattr(self.provider, "http_attempts", 0))
            if tool_count + len(calls) > self.max_tool_calls:
                self._remove_pending_message()
                raise RuntimeError("达到工具调用上限；请缩小问题范围后重试。")
            for call in calls:
                name = call["function"]["name"]
                raw = call["function"]["arguments"]
                try:
                    def reject_constant(value):
                        raise ValueError("工具JSON不接受NaN或Infinity")
                    arguments = json.loads(raw, parse_constant=reject_constant)
                    result = self.registry.execute(name, arguments)
                except (ValueError, TypeError):
                    arguments = raw
                    result = {"ok": False, "error": "工具参数不是有效的 JSON"}
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
                self.messages.append({"role": "tool", "tool_call_id": call["id"],
                                      "content": json.dumps(result, ensure_ascii=False, allow_nan=False)})
        raise RuntimeError("达到模型调用轮数上限；本轮没有生成最终答案。")

    def _remove_pending_message(self) -> None:
        # 移除尚未执行的工具请求，避免下一轮带着不完整的请求／结果配对。
        self.messages.pop()
