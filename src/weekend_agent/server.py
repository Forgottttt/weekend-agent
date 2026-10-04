"""本地演示 HTTP 服务，默认仅绑定 127.0.0.1。"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from .service import BusyError, PlanningService
from .diagnostics import doctor


def create_server(port: int = 8765, service: PlanningService | None = None):
    service = service or PlanningService()
    web_root = Path(__file__).parent / "web"

    class Handler(BaseHTTPRequestHandler):
        def send(self, status, value, content_type="application/json; charset=utf-8"):
            raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode() if isinstance(value, dict) else value
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(raw)

        def valid_host(self):
            return self.headers.get("Host") in (f"127.0.0.1:{self.server.server_port}",
                                                f"localhost:{self.server.server_port}")

        def do_GET(self):
            if not self.valid_host():
                return self.send(403, {"error": "只允许本地访问"})
            parsed = urlparse(self.path)
            if parsed.path == "/api/health":
                try:
                    model = doctor()
                except (ValueError, OSError):
                    model = {"ready": False, "error": "模型配置有误，请在终端运行 python3 main.py --doctor 检查。"}
                return self.send(200, {"ok": True, "data_mode": "fictional_demo", "model": model})
            if parsed.path == "/api/session":
                try:
                    session_id = parse_qs(parsed.query).get("id", [""])[0]
                    saved = service.store.load(session_id)
                    return self.send(200, {"session_id": session_id, "request": saved["request"],
                                           "result": saved["result"], "version": saved["version"]})
                except ValueError as error:
                    return self.send(404, {"error": str(error)})
            filename = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}.get(parsed.path)
            if filename is None:
                return self.send(404, {"error": "页面不存在"})
            mime = {"index.html": "text/html", "app.js": "text/javascript", "style.css": "text/css"}[filename]
            self.send(200, (web_root / filename).read_bytes(), mime + "; charset=utf-8")

        def extract(self, body):
            """把一句自然语言解析成表单条件。模型只提出候选值，前端填入后仍需用户确认。"""
            from .config import ModelConfig
            from .extraction import (clarification, extract_slots, missing_slots,
                                     provided_slots)
            from .providers import APIProvider
            if body.get("mode", "live") != "live":
                raise ValueError("自然语言解析需要真实模型模式")
            slots = extract_slots(body.get("text", ""), APIProvider(ModelConfig.from_env()))
            provided = provided_slots(slots)
            absent = missing_slots(provided)
            return {"slots": slots, "provided": provided, "missing": absent,
                    "question": clarification(absent)}

        def do_POST(self):
            origin = self.headers.get("Origin")
            allowed = {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}
            if not self.valid_host() or (origin and origin not in allowed):
                return self.send(403, {"error": "只允许本地同源请求"})
            if self.path not in ("/api/plan", "/api/extract"):
                return self.send(404, {"error": "接口不存在"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536:
                    raise ValueError("请求体必须在 1–65536 字节之间")
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise ValueError("需要 application/json 请求")
                def reject_constant(value):
                    raise ValueError("JSON 不接受 NaN 或 Infinity")
                body = json.loads(self.rfile.read(length), parse_constant=reject_constant)
                if not isinstance(body, dict):
                    raise ValueError("请求体必须是 JSON 对象")
                if self.path == "/api/extract":
                    if set(body) - {"text", "mode"}:
                        raise ValueError("请求字段不正确")
                    return self.send(200, self.extract(body))
                if set(body) - {"request", "question", "mode", "session_id"}:
                    raise ValueError("请求字段不正确")
                session_id = body.get("session_id")
                if session_id is not None and (not isinstance(session_id, str) or len(session_id) != 32):
                    raise ValueError("会话 ID 格式不正确")
                result = service.plan(body.get("request", {}), body.get("question", "请根据表单规划行程。"),
                                      body.get("mode", "demo"), session_id)
                self.send(200, result)
            except BusyError as error:
                self.send(409, {"error": str(error)})
            except (ValueError, TypeError) as error:
                self.send(400, {"error": str(error)})
            except RuntimeError as error:
                self.send(502, {"error": str(error)})
            except Exception:
                self.send(500, {"error": "服务内部错误，请查看本地测试并重试"})

        def log_message(self, format, *args):
            # 不记录请求正文、密钥或用户补充要求。
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(port=8765):
    server = create_server(port)
    print(f"打开 http://127.0.0.1:{server.server_port} · Ctrl+C 停止。全部地点均为虚构教学数据。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
