"""本机HTTP实验：输入错误与同源检查，不访问外部模型。"""
import json
import sys
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import Request, urlopen
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from weekend_agent.server import create_server
from weekend_agent.service import PlanningService

with TemporaryDirectory() as folder:
    server = create_server(0, PlanningService(Path(folder) / "lesson.sqlite3"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        cases = [("正确数字", {"request": {"budget_per_person": 80}}, {}),
                 ("数字写成字符串", {"request": {"budget_per_person": "80"}}, {}),
                 ("bool冒充人数", {"request": {"group_size": True}}, {}),
                 ("非本地Origin", {"request": {}}, {"Origin": "https://example.invalid"})]
        for label, body, headers in cases:
            request = Request(f"http://127.0.0.1:{server.server_port}/api/plan",
                              data=json.dumps(body).encode(),
                              headers={"Content-Type": "application/json", **headers})
            try:
                with urlopen(request, timeout=5) as response:
                    result = json.load(response)
                    print(label, response.status, result["plan"]["status"])
            except HTTPError as error:
                with error:
                    print(label, error.code, json.load(error)["error"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
