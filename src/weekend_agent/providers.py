"""相同的调用接口可以接固定演示或真实模型，Agent 循环不用跟着改变。"""

import json
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from time import sleep
from urllib.parse import urlparse

from .config import ModelConfig


class ChatProvider(Protocol):
    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        """返回 Chat Completions 格式的 assistant 消息。"""
        ...


class APIProvider:
    """使用标准库调用兼容 Chat Completions 的模型，不需要安装 SDK。"""

    def __init__(self, config: ModelConfig):
        self.config = config
        self.last_usage: dict = {}
        self.total_usage = {"prompt_tokens": 0, "completion_tokens": 0}
        self.http_attempts = 0

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        self.last_usage = {}
        payload = {
            "model": self.config.model, "messages": messages,
            "stream": False,
        }
        if tools:
            payload.update(tools=tools, tool_choice="auto")
        if urlparse(self.config.base_url).hostname == "api.deepseek.com":
            payload["thinking"] = {"type": "disabled"}
        payload["max_tokens"] = self.config.max_tokens
        request = Request(
            self.config.base_url + "/chat/completions",
            data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.config.api_key}"},
            method="POST",
        )
        try:
            result = self._request(request)
            if not isinstance(result, dict):
                raise ValueError("响应不是对象")
            usage = result.get("usage", {})
            if not isinstance(usage, dict):
                usage = {}
            self.last_usage = {key: value for key, value in usage.items()
                               if key in ("prompt_tokens", "completion_tokens") and type(value) is int and value >= 0}
            for key, value in self.last_usage.items():
                self.total_usage[key] += value
            choice = result["choices"][0]
            finish = choice.get("finish_reason")
            if finish == "length":
                raise RuntimeError("模型输出被截断（finish_reason=length）。请增加 LLM_MAX_TOKENS 或缩小任务；本次不会执行不完整的工具参数。")
            if finish not in (None, "stop", "tool_calls"):
                raise RuntimeError("模型没有正常完成响应，请稍后重试或缩小任务。")
            message = choice["message"]
            if not isinstance(message, dict):
                raise ValueError("assistant消息不是对象")
            if message.get("role", "assistant") != "assistant":
                raise ValueError("响应角色不是assistant")
            if message.get("content") is not None and not isinstance(message["content"], str):
                raise ValueError("content必须是字符串或null")
            if message.get("tool_calls") is not None and not isinstance(message["tool_calls"], list):
                raise ValueError("tool_calls必须是列表")
            clean = {"role": "assistant", "content": message.get("content")}
            if message.get("tool_calls"):
                clean["tool_calls"] = message["tool_calls"]
            # 某些模型要求后续调用带回这个字段；它不会写入学习日志。
            if message.get("reasoning_content"):
                clean["reasoning_content"] = message["reasoning_content"]
            return clean
        except HTTPError as error:
            code = error.code
            error.close()
            hint = {400: "请求参数或消息协议不兼容，请检查模型名和工具消息配对。",
                    401: "密钥无效或已失效，请检查本地 LLM_API_KEY。",
                    402: "账户余额不足，请到 DeepSeek 平台检查额度。",
                    403: "当前账户或密钥没有访问权限，请检查服务权限。",
                    404: "接口或模型不存在，请检查 LLM_BASE_URL 和 LLM_MODEL。",
                    422: "请求参数不符合服务要求，请检查模型与参数配置。",
                    429: "请求过于频繁，请稍后重试。"}.get(code, "服务暂时不可用，请稍后重试。")
            raise RuntimeError(f"模型服务返回 HTTP {code}：{hint}") from None
        except (URLError, TimeoutError):
            raise RuntimeError("模型请求失败或超时，请检查网络和 LLM_BASE_URL。") from None
        except (KeyError, IndexError, ValueError, TypeError, AttributeError):
            raise RuntimeError("模型响应格式异常，没有取得有效的 assistant 消息。") from None

    def _request(self, request: Request) -> dict:
        # 有界指数退避；默认一次重试，最多两次，不重试权限或参数错误。
        for attempt in range(self.config.max_retries + 1):
            try:
                self.http_attempts += 1
                with urlopen(request, timeout=self.config.timeout_seconds) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as error:
                if attempt == self.config.max_retries or (error.code != 429 and not 500 <= error.code <= 599):
                    raise
                error.close()
            except (URLError, TimeoutError):
                if attempt == self.config.max_retries:
                    raise
            sleep(0.5 * (2 ** attempt))
        raise RuntimeError("模型请求没有完成")


def tool_call(call_id: str, name: str, arguments: dict) -> dict:
    return {"id": call_id, "type": "function", "function": {
        "name": name, "arguments": json.dumps(arguments, ensure_ascii=False),
    }}


class DemoProvider:
    """固定步骤的离线演示，不调用模型、不理解自由文本，不计为 AI 评测。"""

    def __init__(self, budget: float = 200, rain: bool = False):
        self.budget = budget
        self.rain = rain

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        results = [json.loads(item["content"]) for item in messages if item["role"] == "tool"]
        stage = len(results)
        activity_id = "p09" if self.rain else "p01"
        if stage == 0:
            name, args = "get_weather", {"city": "杭州", "travel_date": "2026-10-03"}
        elif stage == 1:
            name, args = "search_places", {
                "city": "杭州", "tags": ["拍照", "美食"],
                "indoor": True if self.rain else None, "max_price": self.budget,
            }
        elif stage == 2:
            name, args = "get_route", {"from_id": activity_id, "to_id": "f01"}
        elif stage == 3:
            name, args = "check_itinerary", {
                "stops": [{"place_id": activity_id, "start": "10:00"},
                          {"place_id": "f01", "start": "12:00"}],
                "budget_per_person": self.budget, "group_size": 2,
                "start_time": "10:00", "end_time": "18:00",
            }
        else:
            checked = results[-1]
            if not checked["ok"]:
                answer = f"离线工具执行失败：{checked['error']}"
            elif not checked["data"]["valid"]:
                answer = "演示方案未通过检查：" + "；".join(checked["data"]["issues"])
            else:
                plan = checked["data"]
                rows = [f"{stop['start']}–{stop['end']} {stop['name']}" for stop in plan["schedule"]]
                answer = "\n".join([
                    "周末去哪玩 · 固定离线示例（虚构教学数据）", *rows,
                    f"每人 {plan['cost_per_person']:g} 元，两人共 {plan['total_group_cost']:g} 元。",
                    "这是半天的最小示例，尚未填满整天。",
                    plan["cost_scope"],
                    "雨天示例选择室内展览馆。" if self.rain else "晴天示例选择免费公园和面馆。",
                ])
            return {"role": "assistant", "content": answer}
        return {"role": "assistant", "content": None,
                "tool_calls": [tool_call(f"demo_{stage}", name, args)]}
