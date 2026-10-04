"""自由文本 → 结构化出行条件的槽位抽取。

这一层让模型承担真正不可替代的工作：理解口语化表达、把模糊需求整理成可校验的条件、
对缺失的关键条件主动追问。它同时保持了和表单一样的安全边界——

    模型只负责**提出候选值**；写入 TripRequest 之前，一律经过
    request.TripRequest.from_dict 的同一套校验（城市、日期、时间顺序、取值范围）。
    模型填 null 表示"用户没有说"，应用据此追问，而不是替用户猜。

因此"LLM 提议、应用校验"这一条在这里同样成立，与 finalize 的终审是同一个哲学。
"""

from datetime import date

from .jsonio import parse_json_object
from .request import TripRequest
from .tools import validate_arguments

# 允许从自由文本抽取的槽位。所有字段都可能为 null，表示"用户没有说"。
SLOT_SCHEMA = {
    "type": "object",
    "properties": {
        "city": {"type": ["string", "null"]},
        "travel_date": {"type": ["string", "null"]},
        "budget_per_person": {"type": ["number", "null"], "minimum": 0, "maximum": 10000},
        "group_size": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
        "tags": {"type": ["array", "null"], "maxItems": 6, "items": {"type": "string"}},
        "indoor": {"type": ["boolean", "null"]},
        "rain": {"type": ["boolean", "null"]},
        "start_time": {"type": ["string", "null"]},
        "end_time": {"type": ["string", "null"]},
        "include_meal": {"type": ["boolean", "null"]},
    },
    "additionalProperties": False,
}

SLOT_NAMES = tuple(SLOT_SCHEMA["properties"])

# 缺了这些条件就无法生成有意义的方案，应用必须追问而不是替用户假设。
REQUIRED_SLOTS = ("travel_date", "budget_per_person", "group_size")

SLOT_LABELS = {
    "city": "城市", "travel_date": "出行日期", "budget_per_person": "每人预算",
    "group_size": "同行人数", "tags": "兴趣", "indoor": "室内外要求",
    "rain": "是否雨天", "start_time": "开始时间", "end_time": "结束时间",
    "include_meal": "是否安排用餐",
}

# 与数据集中实际存在的标签保持一致，避免模型造出永远不会命中的标签。
KNOWN_TAGS = ("拍照", "美食", "自然", "文化", "艺术", "运动", "散步",
              "购物", "游戏", "社交", "手作", "亲子", "阅读")


def system_prompt(today: str) -> str:
    tags = "、".join(KNOWN_TAGS)
    return f"""你负责把用户的自然语言出行需求整理成结构化条件，用中文回答。

今天是 {today}。用户说"这周六""下周三"这类相对日期时，请换算成 ISO 日期（YYYY-MM-DD）。

最重要的规则：**只填写用户明确说到的条件**。没说到的字段一律填 null；
不确定的字段也填 null。宁可让应用去追问，也不要猜测或补一个默认值。
不要因为"通常如此"就填入任何数字。

可填字段：
- city：城市，目前只支持"杭州"
- travel_date：出行日期，YYYY-MM-DD
- budget_per_person：每人预算，数字，单位元
- group_size：同行人数，整数
- tags：兴趣标签数组，只能从这些词里选：{tags}
- indoor：true 表示明确要求室内，false 表示明确要求户外，没说填 null
- rain：用户提到下雨或雨天时填 true，否则 null
- start_time / end_time：HH:MM
- include_meal：只有明确要求安排吃饭才填 true

只输出一个 JSON 对象，不要 Markdown 代码围栏，不要任何解释文字。
所有字段都必须出现，没说的填 null。例如：
{{"city": null, "travel_date": "2026-10-10", "budget_per_person": 150, "group_size": null, "tags": ["美食"], "indoor": null, "rain": null, "start_time": null, "end_time": null, "include_meal": true}}
"""


def normalize_slots(slots: dict) -> dict:
    """补齐缺失键为 None，保证下游可以稳定访问每个槽位。"""
    return {name: slots.get(name) for name in SLOT_NAMES}


def provided_slots(slots: dict) -> dict:
    """只保留用户确实说了的槽位；空标签数组不算说过。"""
    result = {}
    for name, value in normalize_slots(slots).items():
        if value is None:
            continue
        if name == "tags" and not value:
            continue
        result[name] = value
    return result


def extract_slots(text: str, provider, today: str | None = None) -> dict:
    """调用模型抽取槽位。返回的字典包含全部槽位键，未说到的为 None。"""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("自然语言条件不能为空")
    if len(text) > 2000:
        raise ValueError("自然语言条件最多 2000 个字符")
    current = today or date.today().isoformat()
    date.fromisoformat(current)
    messages = [{"role": "system", "content": system_prompt(current)},
                {"role": "user", "content": text.strip()}]
    message = provider.complete(messages, [])
    if not isinstance(message, dict):
        raise RuntimeError("抽取模型没有返回有效消息")
    if message.get("tool_calls"):
        raise RuntimeError("抽取阶段不应该产生工具调用")
    slots = parse_json_object(message.get("content"), "条件抽取结果")
    validate_arguments(slots, SLOT_SCHEMA, "slots")
    return normalize_slots(slots)


def missing_slots(provided: dict) -> list[str]:
    return [name for name in REQUIRED_SLOTS if provided.get(name) is None]


def clarification(missing: list[str]) -> str | None:
    if not missing:
        return None
    labels = "、".join(SLOT_LABELS[name] for name in missing)
    return f"还需要你确认：{labels}。补充之后我再生成安排。"


def merge(base_values: dict, provided: dict) -> dict:
    """把抽取到的槽位合并进表单条件，并复用表单的同一套校验。"""
    merged = {**base_values, **provided}
    TripRequest.from_dict(merged)
    return merged
