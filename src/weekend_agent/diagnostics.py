"""先检查本地配置，再用两轮小请求验证模型与工具协议。"""

import json

from .config import ModelConfig
from .providers import APIProvider
from .tools import ToolRegistry, TripTools


def doctor() -> dict:
    config = ModelConfig.from_env(require_key=False)
    return {"network_used": False, **config.public_info(),
            "ready": bool(config.api_key),
            "next_step": "运行 python3 main.py --check-api" if config.api_key else
                         "在项目根目录 .env 的 LLM_API_KEY= 后填写自己的密钥"}


def check_api(config: ModelConfig | None = None) -> dict:
    """最多两轮逻辑请求；每轮重试数由配置决定，测试天气仍为虚构。"""
    config = config or ModelConfig.from_env()
    provider = APIProvider(config)
    registry = ToolRegistry(TripTools())
    messages = [{"role": "system", "content": "你正在参加工具协议连通测试。只使用提供的工具。"},
                {"role": "user", "content": "调用一次 get_weather 查询杭州2026-11-21的教学天气。收到工具结果后用一句话说明它是虚构教学天气。"}]
    first = provider.complete(messages, [registry.schemas[0]])
    calls = first.get("tool_calls") or []
    if len(calls) != 1:
        raise RuntimeError("API已响应，但未按测试要求返回一次天气工具调用；请检查模型的工具调用支持。")
    call = calls[0]
    try:
        if call["type"] != "function" or not isinstance(call["id"], str) or not call["id"]:
            raise ValueError("调用ID或类型无效")
        if call["function"]["name"] != "get_weather":
            raise ValueError("工具名称不匹配")
        arguments = json.loads(call["function"]["arguments"])
        if arguments != {"city": "杭州", "travel_date": "2026-11-21"}:
            raise ValueError("测试参数不匹配")
        result = registry.execute("get_weather", arguments)
        if not result["ok"]:
            raise ValueError("本地工具执行失败")
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("API已响应，但工具参数或调用ID不符合测试协议。") from None
    messages.extend([first, {"role": "tool", "tool_call_id": call["id"],
                             "content": json.dumps(result, ensure_ascii=False)}])
    final = provider.complete(messages, [])
    if final.get("tool_calls") or not (final.get("content") or "").strip():
        raise RuntimeError("工具已执行，但模型没有返回测试结束文本。")
    return {"ok": True, "model": config.model, "model_calls": 2,
            "http_attempts": provider.http_attempts, "tool_calls": 1,
            "usage": provider.total_usage, "answer": final["content"],
            "note": "已验证API响应、天气工具调用和结果回传；不代表完整行程评测通过。"}
