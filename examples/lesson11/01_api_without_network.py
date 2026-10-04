"""第十一课：用模拟响应观察 API 请求格式；不联网，不消耗额度。"""
import json
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from weekend_agent.config import ModelConfig
from weekend_agent.providers import APIProvider

class Response:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self):
        return json.dumps({"choices": [{"message": {"content": "模拟回答"}}],
                           "usage": {"prompt_tokens": 10, "completion_tokens": 5}}).encode()

def fake_request(request, timeout):
    print("请求地址：", request.full_url)
    print("JSON 请求字段：", list(json.loads(request.data)))
    return Response()

provider = APIProvider(ModelConfig("placeholder", "https://example.invalid/v1", "example-model"))
with patch("weekend_agent.providers.urlopen", fake_request):
    message = provider.complete([{"role": "user", "content": "你好"}], [])
print("响应：", message)
print("模拟 usage，不是真实用量：", provider.last_usage)
