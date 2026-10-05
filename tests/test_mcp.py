"""用子进程真实驱动 scripts/mcp_server.py，检查最小 MCP stdio 服务的行为。

这里刻意不使用任何 MCP SDK：手工拼 JSON-RPC 行写进子进程 stdin，
再从子进程 stdout 读回 JSON-RPC 行。所有读取都带超时，避免测试挂住。
"""

import json
import os
import select
import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = PROJECT_ROOT / "scripts" / "mcp_server.py"
SRC_DIR = PROJECT_ROOT / "src"

# 5 个业务工具；submit_plan 是 Agent 内部控制工具，不属于业务工具。
BUSINESS_TOOL_NAMES = {
    "get_weather", "search_places", "get_route", "check_itinerary", "search_guides",
}

READ_TIMEOUT_SECONDS = 10.0


class McpServerProcess:
    """管理一个真实的 MCP stdio 子进程：写一行、读一行。"""

    def __init__(self):
        self.process: subprocess.Popen | None = None
        self.stderr_lines: list[str] = []

    def start(self) -> None:
        if not SERVER_PATH.exists():
            raise AssertionError(f"找不到服务脚本：{SERVER_PATH}")
        environment = dict(os.environ)
        environment["PYTHONPATH"] = os.pathsep.join(
            [str(SRC_DIR), environment.get("PYTHONPATH", "")]).rstrip(os.pathsep)
        self.process = subprocess.Popen(
            [sys.executable, str(SERVER_PATH)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=str(PROJECT_ROOT), env=environment,
            # 二进制模式：自己按字节读行，避开子进程缓冲带来的干扰。
            bufsize=0,
        )

    def send(self, message: dict) -> None:
        """写入一行 JSON-RPC 消息。"""
        assert self.process is not None and self.process.stdin is not None
        payload = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        self.process.stdin.write(payload)
        self.process.stdin.flush()

    def send_raw(self, raw: str) -> None:
        """写入一行原始文本，用来测试非法 JSON。"""
        assert self.process is not None and self.process.stdin is not None
        self.process.stdin.write((raw + "\n").encode("utf-8"))
        self.process.stdin.flush()

    def fail(self, message: str):
        """带子进程诊断信息的失败（unittest 的 self.fail 在辅助类上不可用）。"""
        raise AssertionError(f"{message}\n--- 子进程 stderr ---\n{self.stderr_text()}")

    def read_line(self, timeout: float = READ_TIMEOUT_SECONDS) -> str:
        """在超时内读一行输出；超时或 EOF 都给出可诊断的失败信息。"""
        assert self.process is not None and self.process.stdout is not None
        ready, _, _ = select.select([self.process.stdout], [], [], timeout)
        if not ready:
            return_code = self.process.poll()
            self._drain_stderr()
            self.fail(f"等待服务输出超过 {timeout} 秒。"
                      f"子进程退出码={return_code!r}；stderr={self.stderr_text()!r}")
        line = self.process.stdout.readline()
        if not line:
            return_code = self.process.poll()
            self._drain_stderr()
            self.fail(f"服务在返回回复前关闭了 stdout（退出码={return_code!r}）；"
                      f"stderr={self.stderr_text()!r}")
        return line.decode("utf-8")

    def read_json(self, timeout: float = READ_TIMEOUT_SECONDS) -> dict:
        """读一行并解析成 JSON-RPC 对象。"""
        line = self.read_line(timeout)
        try:
            message = json.loads(line)
        except json.JSONDecodeError as error:
            self.fail(f"stdout 出现了非 JSON 内容：{line!r}（{error}）")
        if not isinstance(message, dict):
            self.fail(f"回复不是 JSON-RPC 对象：{message!r}")
        return message

    def assert_no_pending_output(self, timeout: float = 1.0) -> None:
        """断言在 timeout 内没有更多输出（用来验证通知不产生回复）。"""
        assert self.process is not None and self.process.stdout is not None
        ready, _, _ = select.select([self.process.stdout], [], [], timeout)
        if ready:
            line = self.process.stdout.readline()
            self.fail(f"本不该收到回复，却读到了：{line!r}")

    def _drain_stderr(self) -> None:
        """把当前可读的 stderr 收进缓冲，用于失败诊断。"""
        assert self.process is not None and self.process.stderr is not None
        while True:
            ready, _, _ = select.select([self.process.stderr], [], [], 0)
            if not ready:
                return
            line = self.process.stderr.readline()
            if not line:
                return
            self.stderr_lines.append(line.decode("utf-8", "replace").rstrip())

    def stderr_text(self) -> str:
        return "\n".join(self.stderr_lines)

    def stop(self) -> None:
        """收尾：关 stdin、terminate 并 wait，必要时 kill；绝不挂住测试。"""
        if self.process is None:
            return
        try:
            if self.process.stdin is not None and not self.process.stdin.closed:
                try:
                    self.process.stdin.close()  # 关掉 stdin 让服务自然退出
                except (BrokenPipeError, OSError):
                    pass
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            self._drain_stderr()
        finally:
            for stream in (self.process.stdout, self.process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()
            self.process = None


class McpServerTestCase(unittest.TestCase):
    """公共基类：每个测试启动一个独立子进程，结束时干净关闭。"""

    def setUp(self):
        self.server = McpServerProcess()
        self.server.start()
        self.addCleanup(self.server.stop)

    def request(self, method: str, params: dict | None = None, identifier: int = 1,
                expect_reply: bool = True) -> dict:
        """发一个请求并读回回复。"""
        message = {"jsonrpc": "2.0", "id": identifier, "method": method}
        if params is not None:
            message["params"] = params
        self.server.send(message)
        if not expect_reply:
            return {}
        return self.server.read_json()

    def call_tool(self, name: str, arguments: dict, identifier: int = 10) -> dict:
        """调用 tools/call 并返回 JSON-RPC 回复对象。"""
        return self.request("tools/call", {"name": name, "arguments": arguments}, identifier)

    def assert_tool_text(self, reply: dict) -> dict:
        """从 tools/call 回复的 content 里取出并解析 JSON 文本。"""
        result = reply.get("result")
        self.assertIsNotNone(
            result, f"tools/call 应当正常返回，而不是 JSON-RPC error：{reply!r}")
        content = result.get("content")
        self.assertIsInstance(content, list)
        self.assertTrue(content, "content 不能为空")
        self.assertEqual(content[0].get("type"), "text")
        return json.loads(content[0]["text"])

    def test_initialize_echoes_protocol_version_and_reports_server_info(self):
        reply = self.request("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {}, "clientInfo": {"name": "unittest", "version": "0"},
        })
        result = reply["result"]
        self.assertEqual(reply["jsonrpc"], "2.0")
        self.assertEqual(reply["id"], 1)
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertEqual(result["serverInfo"]["name"], "weekend-agent-tools")
        self.assertEqual(result["serverInfo"]["version"], "0.1.0")
        self.assertEqual(result["capabilities"], {"tools": {}})

    def test_initialize_defaults_protocol_version_when_missing(self):
        reply = self.request("initialize", {}, identifier=2)
        self.assertEqual(reply["result"]["protocolVersion"], "2024-11-05")

    def test_tools_list_returns_exactly_the_five_business_tools(self):
        reply = self.request("tools/list", {}, identifier=3)
        tools = reply["result"]["tools"]
        names = {tool["name"] for tool in tools}
        self.assertEqual(len(tools), 5)
        self.assertEqual(names, BUSINESS_TOOL_NAMES)
        self.assertNotIn("submit_plan", names)
        for tool in tools:
            self.assertEqual(tool["inputSchema"]["type"], "object")
            self.assertIn("description", tool)

    def test_get_weather_succeeds_and_reports_fictional_data_mode(self):
        reply = self.call_tool("get_weather", {"city": "杭州", "travel_date": "2026-11-21"})
        self.assertIs(reply["result"]["isError"], False)
        data = self.assert_tool_text(reply)
        self.assertEqual(data["data_mode"], "fictional_demo")
        self.assertEqual(data["city"], "杭州")
        self.assertEqual(data["date"], "2026-11-21")

    def test_each_business_tool_is_callable(self):
        """确认 5 个工具真的都能通过 MCP 调用，而不只是出现在列表里。"""
        cases = {
            "search_places": {"city": "杭州", "tags": ["拍照"], "indoor": None, "max_price": 30},
            "get_route": {"from_id": "p01", "to_id": "p02"},
            "search_guides": {"query": "拍照 户外", "top_k": 2},
            "check_itinerary": {
                "stops": [{"place_id": "p01", "start": "10:00"}],
                "budget_per_person": 200, "group_size": 2,
                "start_time": "10:00", "end_time": "18:00",
            },
        }
        for index, (name, arguments) in enumerate(cases.items(), start=20):
            with self.subTest(tool=name):
                reply = self.call_tool(name, arguments, identifier=index)
                self.assertIs(reply["result"]["isError"], False)
                data = self.assert_tool_text(reply)
                self.assertEqual(data["data_mode"], "fictional_demo")

    def test_missing_required_argument_is_business_error_and_connection_survives(self):
        """参数不合法要返回 isError=true，且不能中断连接。"""
        reply = self.call_tool("search_places", {"city": "杭州"}, identifier=30)
        self.assertNotIn("error", reply, "参数不合法不应当是 JSON-RPC error")
        self.assertIs(reply["result"]["isError"], True)
        text = reply["result"]["content"][0]["text"]
        self.assertIn("缺少必填字段", text)

        follow_up = self.request("ping", identifier=31)
        self.assertEqual(follow_up["id"], 31)
        self.assertEqual(follow_up["result"], {})

    def test_unknown_place_id_is_business_error_and_connection_survives(self):
        reply = self.call_tool("get_route", {"from_id": "p01", "to_id": "p99"}, identifier=32)
        self.assertIs(reply["result"]["isError"], True)
        self.assertIn("找不到地点 ID", reply["result"]["content"][0]["text"])

        follow_up = self.request("tools/list", identifier=33)
        self.assertEqual(follow_up["id"], 33)
        self.assertEqual(len(follow_up["result"]["tools"]), 5)

    def test_unknown_method_returns_method_not_found(self):
        reply = self.request("resources/list", {}, identifier=40)
        self.assertEqual(reply["error"]["code"], -32601)
        self.assertNotIn("result", reply)

    def test_unknown_tool_name_returns_invalid_params(self):
        reply = self.call_tool("submit_plan", {"anything": 1}, identifier=41)
        self.assertEqual(reply["error"]["code"], -32602)
        self.assertNotIn("result", reply)

    def test_invalid_json_returns_parse_error(self):
        self.server.send_raw("{ this is not json")
        reply = self.server.read_json()
        self.assertEqual(reply["error"]["code"], -32700)

    def test_non_object_request_returns_invalid_request(self):
        self.server.send_raw(json.dumps([{"jsonrpc": "2.0", "id": 1, "method": "ping"}]))
        reply = self.server.read_json()
        self.assertEqual(reply["error"]["code"], -32600)

    def test_notification_produces_no_reply(self):
        """notifications/initialized（无 id）不能产生回复。

        先发通知再发 ping：若通知被误当成请求回复，那么先读到的就会是
        通知的回复（id 为 null）而不是 ping 的回复。
        """
        self.server.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.server.send({"jsonrpc": "2.0", "id": 50, "method": "ping"})
        reply = self.server.read_json()
        self.assertEqual(reply["id"], 50, f"通知不应答；却先收到：{reply!r}")
        self.assertEqual(reply["result"], {})

    def test_ping_returns_empty_result(self):
        reply = self.request("ping", identifier=60)
        self.assertEqual(reply["result"], {})
        self.assertEqual(reply["id"], 60)

    def test_stdout_only_contains_json_rpc(self):
        """stdout 全程只能是 JSON-RPC 行，不能混入日志或警告。

        read_json 遇到无法解析的内容就会失败，所以走完这条流程即说明
        三行 stdout 都是合法 JSON-RPC；最后再确认没有多余输出。
        """
        self.request("initialize", {"protocolVersion": "2024-11-05"}, identifier=70)
        self.request("tools/list", {}, identifier=71)
        self.call_tool("get_weather", {"city": "杭州", "travel_date": "2026-11-21"}, identifier=72)
        self.server.assert_no_pending_output(timeout=0.5)


if __name__ == "__main__":
    unittest.main()
