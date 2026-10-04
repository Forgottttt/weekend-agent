"""完整两轮API工具协议实验；mock拦截HTTP，不使用本地密钥。"""
import json
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from weekend_agent.config import ModelConfig
from weekend_agent.diagnostics import check_api
from weekend_agent.providers import tool_call

class Response:
    def __init__(self, message): self.message = message
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self):
        return json.dumps({"choices": [{"message": self.message}],
                           "usage": {"prompt_tokens": 10, "completion_tokens": 5}}).encode()

count = 0
def fake_request(request, timeout):
    global count
    count += 1
    body = json.loads(request.data)
    print("第", count, "次HTTP（已拦截）：", request.full_url)
    print("消息角色：", [message["role"] for message in body["messages"]])
    print("包含工具定义：", "tools" in body, "思考设置：", body.get("thinking"))
    if count == 1:
        return Response({"role": "assistant", "tool_calls": [tool_call("weather-one", "get_weather",
                         {"city": "杭州", "travel_date": "2026-11-21"})]})
    return Response({"role": "assistant", "content": "这是虚构教学天气，不是实际预报。"})

with patch("weekend_agent.providers.urlopen", fake_request):
    report = check_api(ModelConfig("fake-test-key", "https://api.deepseek.com", "deepseek-flash"))
print("以下全部是模拟报告：", json.dumps(report, ensure_ascii=False))
