"""全部使用内存响应，不访问真实API，也不读取用户的真实密钥。"""
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

from weekend_agent.config import ModelConfig, read_env_file
from weekend_agent.diagnostics import check_api
from weekend_agent.evaluation import evaluate
from weekend_agent.providers import APIProvider, tool_call
from weekend_agent.service import PlanningError, PlanningService


class Response:
    def __init__(self, message, finish="stop", usage=None):
        self.data = {"choices": [{"finish_reason": finish, "message": message}],
                     "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5}}
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return json.dumps(self.data).encode()


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / ".env"
    def tearDown(self): self.folder.cleanup()

    def test_env_file_and_process_precedence_across_key_aliases(self):
        self.path.write_text('LLM_API_KEY="file-key"\nLLM_MAX_TOKENS=8192\n')
        config = ModelConfig.from_env(self.path, {"DEEPSEEK_API_KEY": "process-key"})
        self.assertEqual(config.api_key, "process-key")
        self.assertEqual(config.max_tokens, 8192)
        self.assertNotIn("process-key", repr(config))
        self.assertNotIn("process-key", json.dumps(config.public_info()))

    def test_placeholder_is_not_a_working_key(self):
        self.path.write_text('LLM_API_KEY=replace_with_your_key\n')
        self.assertFalse(ModelConfig.from_env(self.path, {}, require_key=False).api_key)
        with self.assertRaisesRegex(ValueError, "尚未设置"):
            ModelConfig.from_env(self.path, {})

    def test_empty_environment_key_does_not_silently_use_file_key(self):
        self.path.write_text('LLM_API_KEY=file-key\n')
        with self.assertRaisesRegex(ValueError, "尚未设置"):
            ModelConfig.from_env(self.path, {"LLM_API_KEY": ""})

    def test_error_does_not_echo_secret_line(self):
        self.path.write_text('WRONG_KEY=private-content\n')
        with self.assertRaises(ValueError) as caught:
            read_env_file(self.path)
        self.assertNotIn("private-content", str(caught.exception))

    def test_shell_expressions_are_literal_not_executed(self):
        self.path.write_text('LLM_API_KEY="$(echo do-not-execute)"\n')
        self.assertEqual(read_env_file(self.path)["LLM_API_KEY"], '$(echo do-not-execute)')

    def test_rejects_unsafe_or_double_endpoint(self):
        for address in ('http://api.deepseek.com', 'https://user:secret@example.com',
                        'https://api.deepseek.com/chat/completions', 'https://api.deepseek.com?key=secret'):
            with self.subTest(address=address), self.assertRaises(ValueError):
                ModelConfig('fake', address, 'deepseek-flash')

    def test_invalid_limits_are_actionable(self):
        for contents in ('LLM_MAX_TOKENS=zero', 'LLM_TIMEOUT_SECONDS=0', 'LLM_MAX_RETRIES=30'):
            self.path.write_text('LLM_API_KEY=fake\n' + contents)
            with self.assertRaisesRegex(ValueError, 'LLM_'):
                ModelConfig.from_env(self.path, {})


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.config = ModelConfig('fake-test-key', 'https://api.deepseek.com', 'deepseek-flash')

    def test_tool_round_trip_and_empty_tools_omitted(self):
        call = tool_call('weather-one', 'get_weather', {'city': '杭州', 'travel_date': '2026-11-21'})
        responses = [Response({'role': 'assistant', 'content': None, 'tool_calls': [call]}, 'tool_calls'),
                     Response({'role': 'assistant', 'content': '这是虚构教学天气。'})]
        with patch('weekend_agent.providers.urlopen', side_effect=responses) as mocked:
            report = check_api(self.config)
        self.assertEqual(report['model_calls'], 2)
        self.assertEqual(report['http_attempts'], 2)
        self.assertEqual(report['usage']['prompt_tokens'], 20)
        first, second = [json.loads(call.args[0].data) for call in mocked.call_args_list]
        self.assertEqual(first['thinking'], {'type': 'disabled'})
        self.assertEqual(first['model'], 'deepseek-flash')
        self.assertNotIn('tools', second)
        self.assertEqual(second['messages'][-1]['tool_call_id'], 'weather-one')
        self.assertNotIn('fake-test-key', json.dumps(report))

    def test_text_only_reply_does_not_pass_tool_check(self):
        with patch('weekend_agent.providers.urlopen', return_value=Response({'content': '晴天'})):
            with self.assertRaisesRegex(RuntimeError, '未按测试要求'):
                check_api(self.config)

    def test_truncation_is_not_executed_as_a_tool(self):
        provider = APIProvider(self.config)
        with patch('weekend_agent.providers.urlopen', return_value=Response({'content': '{"status":'}, 'length')):
            with self.assertRaisesRegex(RuntimeError, 'LLM_MAX_TOKENS'):
                provider.complete([], [])
        self.assertEqual(provider.total_usage['completion_tokens'], 5)

    def test_auth_error_is_not_retried_or_echoed(self):
        provider = APIProvider(self.config)
        with patch('weekend_agent.providers.urlopen', side_effect=HTTPError('https://api.deepseek.com', 401,
                    'fake-test-key', None, None)) as mocked:
            with self.assertRaisesRegex(RuntimeError, '401') as caught:
                provider.complete([], [])
        self.assertEqual(mocked.call_count, 1)
        self.assertNotIn('fake-test-key', str(caught.exception))

    def test_retry_cap_and_http_attempts_are_separate(self):
        provider = APIProvider(ModelConfig('fake', 'https://api.deepseek.com', 'deepseek-flash', max_retries=2))
        responses = [HTTPError('https://api.deepseek.com', 503, 'down', None, None),
                     HTTPError('https://api.deepseek.com', 429, 'slow', None, None), Response({'content': 'ok'})]
        with patch('weekend_agent.providers.urlopen', side_effect=responses), patch('weekend_agent.providers.sleep') as pause:
            self.assertEqual(provider.complete([], [])['content'], 'ok')
        self.assertEqual(provider.http_attempts, 3)
        self.assertEqual([call.args[0] for call in pause.call_args_list], [0.5, 1.0])

    def test_failed_call_clears_previous_usage(self):
        provider = APIProvider(self.config)
        with patch('weekend_agent.providers.urlopen', return_value=Response({'content': 'ok'})):
            provider.complete([], [])
        with patch('weekend_agent.providers.urlopen', side_effect=HTTPError('https://api.deepseek.com', 402, 'no', None, None)):
            with self.assertRaises(RuntimeError): provider.complete([], [])
        self.assertEqual(provider.last_usage, {})
        self.assertEqual(provider.total_usage['prompt_tokens'], 10)

    def test_malformed_content_is_controlled_error(self):
        with patch('weekend_agent.providers.urlopen', return_value=Response({'content': {'unexpected': True}})):
            with self.assertRaisesRegex(RuntimeError, '响应格式'):
                APIProvider(self.config).complete([], [])

    def test_service_keeps_failed_request_metrics(self):
        with tempfile.TemporaryDirectory() as folder:
            service = PlanningService(Path(folder) / 'state.sqlite3')
            with patch('weekend_agent.service.ModelConfig.from_env', return_value=self.config), patch(
                'weekend_agent.providers.urlopen', side_effect=HTTPError('https://api.deepseek.com', 401, 'no', None, None)):
                with self.assertRaises(PlanningError) as caught:
                    service.plan({}, mode='live')
            self.assertEqual(caught.exception.metrics['model_calls'], 1)
            self.assertEqual(caught.exception.metrics['http_attempts'], 1)

    def test_evaluation_counts_failed_model_requests(self):
        failure = PlanningError('test failure', {'model_calls': 2, 'http_attempts': 3, 'input_tokens': 10, 'output_tokens': 5})
        with tempfile.TemporaryDirectory() as folder, patch('weekend_agent.evaluation.PlanningService.plan', side_effect=failure):
            report = evaluate('live', Path(folder))
        self.assertEqual(report['passed'], 0)
        self.assertEqual(report['model_calls'], 24)
        self.assertEqual(report['http_attempts'], 36)


if __name__ == '__main__':
    unittest.main()
