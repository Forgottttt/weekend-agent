"""把模型返回的文本解析成 JSON 对象。

真实模型的最终输出经常不干净，实测出现过三种形态：

    1. 裸 JSON                            {"status": "planned", ...}
    2. Markdown 代码围栏包裹              ```json\\n{...}\\n```
    3. 前面带一段解释文字，后面才是裸 JSON  Confirmed: ... 27/person > 20 budget.\\n\\n{...}

第 3 种最初被误判成围栏问题，只有记录下被拒原文才看清楚。
因此这里按"围栏内容 → 整段文本 → 文本中第一个配平的 JSON 对象"依次尝试，
并把定位失败转成可读中文，方便回灌给模型自我修正。
"""

import json
import re

# 匹配 ```json ... ``` 或 ``` ... ```，允许围栏前后还有别的内容。
_FENCED = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _reject_constant(value: str) -> float:
    # JSON 标准没有 NaN/Infinity；它们通常来自模型拼错数字。
    raise ValueError(f"不接受 {value}，请使用有限数字")


def _first_object(text: str) -> str | None:
    """扫描出文本中第一个花括号配平的 JSON 对象。

    需要正确跳过字符串字面量里的花括号和转义引号，否则
    {"title": "预算{100}"} 这类内容会被提前截断。
    """
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start:index + 1]
        # 这个左花括号后面没有配平的对象，从下一个继续找。
        start = text.find("{", start + 1)
    return None


def parse_json_object(content: str, what: str = "模型输出") -> dict:
    """解析出 JSON 对象；失败时抛出带中文说明的 ValueError。"""
    if not isinstance(content, str):
        raise ValueError(f"{what}必须是字符串")
    text = content.strip()
    if not text:
        raise ValueError(f"{what}为空")

    candidates = []
    fenced = _FENCED.search(text)
    if fenced:
        candidates.append(fenced.group(1).strip())
    candidates.append(text)
    scanned = _first_object(text)
    if scanned:
        candidates.append(scanned)

    failure = "没有找到 JSON 对象"
    for candidate in candidates:
        try:
            value = json.loads(candidate, parse_constant=_reject_constant)
        except (json.JSONDecodeError, ValueError) as error:
            failure = str(error) if isinstance(error, ValueError) else error.msg
            continue
        if isinstance(value, dict):
            return value
        failure = "解析结果不是 JSON 对象"
    raise ValueError(
        f"{what}不是合法 JSON（{failure}）。"
        "请只返回一个 JSON 对象，不要使用 Markdown 代码围栏，也不要在 JSON 前后添加解释文字。"
    )
