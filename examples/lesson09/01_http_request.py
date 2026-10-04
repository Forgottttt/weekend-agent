"""第九课：临时启动仅本机服务，发一次真实 HTTP 请求，无外部模型请求。"""
import json
import sys
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from weekend_agent.server import create_server
from weekend_agent.service import PlanningService

with TemporaryDirectory() as folder:
    server = create_server(0, PlanningService(Path(folder) / "session.sqlite3"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = {"mode": "demo", "request": {"rain": True, "budget_per_person": 80}}
        request = Request(f"http://127.0.0.1:{server.server_port}/api/plan",
                          data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        with urlopen(request) as response:
            result = json.load(response)
        print("HTTP 请求已完成：", result["plan"]["status"])
        print(result["answer"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
