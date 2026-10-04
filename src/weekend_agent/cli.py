"""项目入口：网页、命令行规划、评测和面试练习。"""

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .config import PROJECT_ROOT
from .service import PlanningService


def parser():
    result = argparse.ArgumentParser(description="周末去哪玩 · 完整学习项目")
    mode = result.add_mutually_exclusive_group()
    mode.add_argument("--demo", action="store_true", help="规则离线演示，不调用大模型")
    mode.add_argument("--live", action="store_true", help="真实模型模式，需要配置环境变量")
    action = result.add_mutually_exclusive_group()
    action.add_argument("--serve", action="store_true", help="启动本地网页")
    action.add_argument("--evaluate", action="store_true", help="运行12个固定回归用例")
    action.add_argument("--practice", action="store_true", help="运行面试问答练习")
    action.add_argument("--legacy-demo", action="store_true", help="第一版半天固定示例，供早期课程对照")
    action.add_argument("--doctor", action="store_true", help="离线检查模型配置，不联网、不显示密钥")
    action.add_argument("--check-api", action="store_true", help="两轮真实API请求，验证一次天气工具调用及结果回传，会消耗API额度")
    result.add_argument("--port", type=int, default=8765)
    result.add_argument("--topic", default="tools")
    result.add_argument("--count", type=int, default=3)
    result.add_argument("--budget", type=float, default=200)
    result.add_argument("--group-size", type=int, default=2)
    result.add_argument("--date", default="2026-11-21")
    result.add_argument("--start", default="10:00")
    result.add_argument("--end", default="18:00")
    result.add_argument("--tags", default="拍照,美食")
    result.add_argument("--rain", action="store_true")
    result.add_argument("--indoor", choices=["any", "inside", "outside"], default="any")
    result.add_argument("--no-meal", action="store_true")
    result.add_argument("--question", default="请根据表单规划行程。")
    result.add_argument("--chat", action="store_true", help="保存会话；/budget 数字可改预算，/rain 可切换雨天")
    result.add_argument("--session", help="恢复已有会话 ID")
    result.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "outputs")
    return result


def show_result(run, output_dir: Path, mode: str):
    record = {**asdict(run), "mode": mode, "model_calls": run.provider_calls if mode == "live" else 0}
    print_result(record, output_dir)


def print_result(result, output_dir):
    print("\n" + result["answer"])
    print(f"\n模型调用 {result['model_calls']} 次；工具请求 {result['tool_calls']} 次；最终校验 {result.get('final_checks', 0)} 次。")
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / datetime.now().strftime("trace_%Y%m%d_%H%M%S_%f.json")
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print("调用记录：", target)
    if result.get("session_id"):
        print("会话 ID：", result["session_id"])


def main(argv=None):
    args = parser().parse_args(argv)
    mode = "live" if args.live else "demo"
    try:
        if args.doctor or args.check_api:
            from .diagnostics import doctor, check_api
            report = doctor() if args.doctor else check_api()
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report.get("ready", report.get("ok", False)) else 1
        if args.serve:
            from .server import serve
            serve(args.port)
            return 0
        if args.evaluate:
            from .evaluation import evaluate
            report = evaluate(mode, args.output_dir)
            print(f"{report['mode']} 回归：{report['passed']}/{report['case_count']}；模型请求 {report['model_calls']} 次。")
            print(report["limitations"])
            print("报告：", report["report_path"])
            return 0 if report["passed"] == report["case_count"] else 1
        if args.practice:
            from .interview import practice
            if not 1 <= args.count <= 20:
                raise ValueError("练习题数必须在 1–20 之间")
            practice(args.topic, args.count)
            return 0
        if args.legacy_demo:
            from .agent import TripAgent
            from .providers import DemoProvider
            from .tools import ToolRegistry, TripTools
            run = TripAgent(DemoProvider(args.budget, args.rain), ToolRegistry(TripTools(rain=args.rain))).run("旧版固定示例")
            show_result(run, args.output_dir, "demo")
            return 0
        values = {"budget_per_person": args.budget, "group_size": args.group_size,
                  "travel_date": args.date, "start_time": args.start, "end_time": args.end,
                  "tags": [tag.strip() for tag in args.tags.replace("，", ",").split(",") if tag.strip()],
                  "rain": args.rain, "include_meal": not args.no_meal,
                  "indoor": {"any": None, "inside": True, "outside": False}[args.indoor]}
        service = PlanningService(args.output_dir / "sessions.sqlite3")
        session_id = args.session
        if session_id:
            values = service.store.load(session_id)["request"]
        question = args.question
        while True:
            result = service.plan(values, question, mode, session_id)
            session_id = result["session_id"]
            print_result(result, args.output_dir)
            if not args.chat:
                return 0
            text = input("\n输入补充要求，或 /budget 80、/rain、exit：").strip()
            if text.lower() in ("exit", "quit"):
                return 0
            if text.startswith("/budget "):
                values["budget_per_person"] = float(text.split(maxsplit=1)[1])
                question = "按新的预算重新规划。"
            elif text == "/rain":
                values["rain"] = not values["rain"]
                question = "按新的教学天气重新规划。"
            else:
                question = text or "请再次规划。"
                if mode == "demo":
                    print("离线演示不理解自由文本，仍按表单条件运行。")
    except (ValueError, RuntimeError, OSError) as error:
        print("运行未完成：", error)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\n已结束。")
        return 0
