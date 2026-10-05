#!/usr/bin/env python3
"""把本项目的 5 个业务工具暴露成一个最小 MCP stdio 服务（纯标准库）。

运行方式::

    PYTHONPATH=src python3 scripts/mcp_server.py

协议与实现范围（请诚实阅读）：

* 传输层是 stdio，每行一个 JSON-RPC 2.0 消息（newline-delimited JSON）。
* 这是**最小实现，只覆盖 MCP 的一个子集**：仅实现 ``initialize``、
  ``notifications/initialized``、``tools/list``、``tools/call``、``ping`` 五个方法。
* **没有实现** resources、prompts、logging、sampling、roots、completion、
  通知订阅（``*/list_changed``）、请求取消（``notifications/cancelled``）、
  进度通知、批量请求（JSON-RPC batch）、协议版本协商、HTTP/SSE 传输等能力。
* 本文件**没有用真实 MCP 客户端（例如 Claude Desktop 或官方 mcp SDK）验证过**，
  只在 tests/test_mcp.py 里用子进程手工拼 JSON-RPC 消息做过验证。
* 因此请把它当作教学用的协议示例，而不是可直接投产的 MCP 服务器。
* ``submit_plan`` 是 Agent 内部控制工具，不属于业务工具，这里显式按名字排除。

日志纪律：stdout 只允许出现 JSON-RPC 行，其他一切（日志、异常栈）都写 stderr。
"""

import json
import sys
from pathlib import Path
from typing import Any, Callable

# 与根目录 main.py 同理：直接把 src/ 加入 sys.path，免去先安装包。
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from weekend_agent.tools import TOOL_SCHEMAS, ToolRegistry, TripTools  # noqa: E402

try:  # tools.py 若导出了规范的控制工具集合就复用它，保持单一事实来源
    from weekend_agent.tools import CONTROL_TOOLS as _CONTROL_TOOLS  # noqa: E402
except ImportError:  # 老版本 tools.py 没有这个常量时退回本地定义
    _CONTROL_TOOLS = frozenset()

SERVER_NAME = "weekend-agent-tools"
SERVER_VERSION = "0.1.0"
DEFAULT_PROTOCOL_VERSION = "2024-11-05"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

# Agent 内部控制工具，不是业务工具：即使 TOOL_SCHEMAS 以后加了它也不暴露。
# 这里按名字排除，不依赖列表长度或下标；同时也并上 tools.py 的 CONTROL_TOOLS。
INTERNAL_TOOL_NAMES = frozenset({"submit_plan"}) | frozenset(_CONTROL_TOOLS)


def log(message: str) -> None:
    """把日志写到 stderr；stdout 必须留给 JSON-RPC。"""
    print(f"[mcp_server] {message}", file=sys.stderr, flush=True)


def load_business_schemas() -> dict[str, dict]:
    """把 TOOL_SCHEMAS 转成 {名字: function schema}，并排除内部控制工具。"""
    schemas: dict[str, dict] = {}
    for item in TOOL_SCHEMAS:
        function = item.get("function", {})
        name = function.get("name")
        if name in INTERNAL_TOOL_NAMES:  # 按名字排除 submit_plan 等控制工具
            log(f"跳过内部控制工具：{name}")
            continue
        schemas[name] = function
    return schemas


class JsonRpcError(Exception):
    """携带 JSON-RPC 错误码的内部异常。"""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class McpStdioServer:
    """一个最小的 JSON-RPC 2.0 over stdio 服务，只实现 MCP 的工具子集。"""

    def __init__(self, registry: ToolRegistry | None = None):
        # 教学天气与用餐约束由构造参数注入，和 CLI 的口径一致。
        self.registry = registry if registry is not None else ToolRegistry(TripTools())
        self.schemas = load_business_schemas()
        self.handlers: dict[str, Callable[[Any], Any]] = {
            "initialize": self.handle_initialize,
            "tools/list": self.handle_tools_list,
            "tools/call": self.handle_tools_call,
            "ping": self.handle_ping,
        }

    def handle_initialize(self, params: Any) -> dict:
        """握手：回显客户端的 protocolVersion（缺失时用默认版本）。"""
        requested = params.get("protocolVersion") if isinstance(params, dict) else None
        version = requested if isinstance(requested, str) and requested else DEFAULT_PROTOCOL_VERSION
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }

    def handle_tools_list(self, params: Any) -> dict:
        """返回 5 个业务工具的 MCP 描述，inputSchema 就是 schema 里的 parameters。"""
        return {"tools": [
            {"name": name,
             "description": function.get("description", ""),
             "inputSchema": function.get("parameters", {"type": "object"})}
            for name, function in self.schemas.items()
        ]}

    def handle_tools_call(self, params: Any) -> dict:
        """执行一个业务工具；业务失败用 isError=true 表达，而不是 JSON-RPC error。"""
        if not isinstance(params, dict):
            raise JsonRpcError(INVALID_PARAMS, "tools/call 的 params 必须是对象")
        name = params.get("name")
        arguments = params.get("arguments", {})
        if name not in self.schemas:
            # 未知工具名属于参数错误，按约定返回 -32602。
            raise JsonRpcError(INVALID_PARAMS, f"未知工具：{name}")
        if arguments is None:
            arguments = {}
        result = self.registry.execute(name, arguments)
        if result.get("ok"):
            text = json.dumps(result.get("data"), ensure_ascii=False, sort_keys=True, default=str)
            return {"content": [{"type": "text", "text": text}], "isError": False}
        # 参数不合法、找不到地点等业务失败：正常返回，让调用方（模型）读得到错误文字。
        text = json.dumps({"error": result.get("error", "工具执行失败")},
                          ensure_ascii=False, sort_keys=True)
        return {"content": [{"type": "text", "text": text}], "isError": True}

    def handle_ping(self, params: Any) -> dict:
        return {}

    def dispatch(self, method: str, params: Any) -> Any:
        handler = self.handlers.get(method)
        if handler is None:
            raise JsonRpcError(METHOD_NOT_FOUND, f"不支持的方法：{method}")
        return handler(params)

    def handle_message(self, message: Any) -> dict | None:
        """处理一条已解析的消息；返回要写出的回复，None 表示这是通知、不回复。"""
        # 只有对象才可能带 id；非对象（数组/标量）按 JSON-RPC 惯例以 id=null 报错。
        identifier = message.get("id") if isinstance(message, dict) else None
        is_notification = isinstance(message, dict) and "id" not in message
        try:
            if not isinstance(message, dict):
                # JSON-RPC 批量和标量都不是本实现支持的请求形态。
                raise JsonRpcError(INVALID_REQUEST,
                                   "请求必须是单个 JSON-RPC 对象（本实现不支持批量请求）")
            if message.get("jsonrpc") != "2.0":
                raise JsonRpcError(INVALID_REQUEST, "jsonrpc 字段必须是 '2.0'")
            if not isinstance(message.get("method"), str):
                raise JsonRpcError(INVALID_REQUEST, "method 必须是字符串")
            method = message["method"]
            if method == "notifications/initialized" or method.startswith("notifications/"):
                # MCP 通知（含 notifications/initialized）不需要回复。
                log(f"收到通知，不回复：{method}")
                return None
            result = self.dispatch(method, message.get("params"))
            if is_notification:
                # 无 id 的请求按 JSON-RPC 语义就是通知，不能回复。
                log(f"无 id 的请求按通知处理，不回复：{method}")
                return None
            return {"jsonrpc": "2.0", "id": identifier, "result": result}
        except JsonRpcError as error:
            if is_notification:
                log(f"通知/无 id 消息出错（不回复）：{error.message}")
                return None
            return {"jsonrpc": "2.0", "id": identifier,
                    "error": {"code": error.code, "message": error.message}}
        except Exception as error:  # 兜底：任何意外都不能污染 stdout 或打断循环
            method = message.get("method") if isinstance(message, dict) else None
            log(f"处理 {method!r} 时出现未预期错误：{error!r}")
            if is_notification:
                return None
            return {"jsonrpc": "2.0", "id": identifier,
                    "error": {"code": INVALID_REQUEST, "message": f"服务器内部错误：{error}"}}

    def handle_line(self, line: str) -> dict | None:
        """处理一行文本；不是合法 JSON 时按 -32700 处理（无法得知 id，只能给 null）。"""
        try:
            message = json.loads(line)
        except json.JSONDecodeError as error:
            log(f"无法解析的 JSON：{error}")
            return {"jsonrpc": "2.0", "id": None,
                    "error": {"code": PARSE_ERROR, "message": f"JSON 解析失败：{error}"}}
        return self.handle_message(message)

    def serve_line(self, line: str, out) -> None:
        """处理一行并写出回复（如果有）。"""
        reply = self.handle_line(line)
        if reply is not None:
            out.write(json.dumps(reply, ensure_ascii=False) + "\n")
            out.flush()

    def serve(self, stdin, stdout) -> None:
        """逐行读 stdin、逐行写 stdout，直到 EOF。

        自己按字节累积到换行符，而不依赖 ``readline()``：管道上的 readline
        在某些 Python 版本/缓冲组合下可能只返回半行（例如一行 JSON 被拆开），
        那样就会把本来合法的消息误判成 JSON 解析错误。
        """
        buffer = bytearray()
        while True:
            chunk = stdin.read(1)
            if not chunk:  # EOF：客户端关闭了管道，处理完残余内容后退出
                tail = bytes(buffer).strip()
                if tail:
                    self.serve_line(tail.decode("utf-8", "replace"), stdout)
                break
            if chunk == b"\n":
                line = bytes(buffer).rstrip(b"\r")
                buffer.clear()
                if line.strip():
                    self.serve_line(line.decode("utf-8", "replace"), stdout)
                continue
            buffer.extend(chunk)
        log("stdin 已关闭，服务退出")


def main() -> int:
    """启动 stdio 服务；stdout 只写 JSON-RPC 行。"""
    # 用二进制流 + 逐行读写，避免任何缓冲或编码带来的多余输出。
    stdin = open(sys.stdin.fileno(), "rb", buffering=0)
    stdout = open(sys.stdout.fileno(), "w", encoding="utf-8", newline="\n")
    log(f"{SERVER_NAME} {SERVER_VERSION} 启动：stdin/stdout 使用逐行 JSON-RPC")
    try:
        McpStdioServer().serve(stdin, stdout)
    except KeyboardInterrupt:
        log("收到中断信号，退出")
    except BrokenPipeError:
        log("stdout 管道已关闭，退出")
    finally:
        stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
