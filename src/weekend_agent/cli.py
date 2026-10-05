"""项目入口：网页、命令行规划、评测和面试练习。"""

import argparse
import json
import sys
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
    action.add_argument("--legacy-demo", action="store_true", help="第一版半天固定示例，供早期课程对照")
    action.add_argument("--doctor", action="store_true", help="离线检查模型配置，不联网、不显示密钥")
    action.add_argument("--check-api", action="store_true", help="两轮真实API请求，验证一次天气工具调用及结果回传，会消耗API额度")
    action.add_argument("--ask", metavar="文本", help="用一句自然语言描述条件，由模型抽取槽位后规划（需要 --live）")
    result.add_argument("--answer", action="append", metavar="补充",
                        help="对澄清追问的补充回答，可重复；不提供时在终端交互追问")
    result.add_argument("--suite", choices=["agent", "extraction", "retrieval", "citations", "all"],
                        default="agent", help="--evaluate 运行的评测套件，默认 agent")
    result.add_argument("--port", type=int, default=8765)
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


def request_values(args) -> dict:
    """把命令行参数整理成表单条件，供规划和抽取合并共用。"""
    return {"budget_per_person": args.budget, "group_size": args.group_size,
            "travel_date": args.date, "start_time": args.start, "end_time": args.end,
            "tags": [tag.strip() for tag in args.tags.replace("，", ",").split(",") if tag.strip()],
            "rain": args.rain, "include_meal": not args.no_meal,
            "indoor": {"any": None, "inside": True, "outside": False}[args.indoor]}


def run_evaluate(args, mode: str) -> int:
    """按套件运行评测。抽取套件必须用真实模型，否则没有可评测的对象。"""
    outcomes: list[bool] = []
    if args.suite in ("agent", "all"):
        from .evaluation import evaluate
        report = evaluate(mode, args.output_dir)
        print(f"{report['mode']} 回归：{report['passed']}/{report['case_count']}；模型请求 {report['model_calls']} 次。")
        print(report["limitations"])
        print("报告：", report["report_path"])
        outcomes.append(report["passed"] == report["case_count"])
    if args.suite in ("extraction", "all"):
        if mode != "live":
            # --suite all 在离线模式下应当把不需要模型的套件跑完，而不是中途退出。
            print("跳过槽位抽取评测：需要真实模型（加 --live）。")
            if args.suite == "extraction":
                return 1
        else:
            from .extraction_eval import evaluate_extraction
            report = evaluate_extraction(output_dir=args.output_dir)
            print(f"抽取评测：{report['case_count']} 例，模型请求 {report['model_calls']} 次。")
            print(f"  槽位准确率     {report['slot_accuracy']:.1%}（{report['correct_slots']}/{report['stated_slots']}）")
            print(f"  幻觉误填率     {report['hallucination_rate']:.1%}（{report['hallucinated_slots']}/{report['unstated_slots']} 个未声明槽位）")
            print(f"  追问触发正确率 {report['clarification_accuracy']:.1%}（{report['clarification_correct_cases']}/{report['case_count']}）")
            print(report["limitations"])
            print("报告：", report["report_path"])
            outcomes.append(report["errors"] == 0)
    if args.suite in ("retrieval", "all"):
        from .retrieval_eval import evaluate_retrieval
        report = evaluate_retrieval(output_dir=args.output_dir)
        bm25, tfidf = report["bm25"], report["tfidf"]
        print(f"检索评测：{report['corpus_size']} 篇语料 / {report['case_count']} 条标注查询，top_k={report['top_k']}。")
        print(f"  BM25   recall@k {bm25['recall_at_k']:.1%}  MRR {bm25['mrr']:.3f}")
        print(f"  TF-IDF recall@k {tfidf['recall_at_k']:.1%}  MRR {tfidf['mrr']:.3f}")
        print(report["limitations"])
        print("报告：", report["report_path"])
    if args.suite in ("citations", "all"):
        if mode != "live":
            print("跳过引用评审：需要真实模型（加 --live）。")
            if args.suite == "citations":
                return 1
        else:
            from .citation_eval import evaluate_citations
            report = evaluate_citations(output_dir=args.output_dir)
            print(f"引用评审：{report['case_count']} 例，其中 {report['judged_count']} 例有可评审的引用，"
                  f"{report['skipped_count']} 例跳过，{report['error_count']} 例出错。")
            print(f"  引用命中率 {report['citation_precision']:.1%}（{report['hit_total']}/{report['cited_total']}）")
            print(f"  无关引用率 {report['unrelated_citation_rate']:.1%}")
            if report["citation_recall"] is not None:
                print(f"  引用召回率 {report['citation_recall']:.1%}")
            print(report["limitations"])
            print("报告：", report["report_path"])
            outcomes.append(report["error_count"] == 0)
    return 0 if all(outcomes) else 1


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
            return run_evaluate(args, mode)
        if args.legacy_demo:
            from .agent import TripAgent
            from .providers import DemoProvider
            from .tools import ToolRegistry, TripTools
            run = TripAgent(DemoProvider(args.budget, args.rain), ToolRegistry(TripTools(rain=args.rain))).run("旧版固定示例")
            show_result(run, args.output_dir, "demo")
            return 0
        values = request_values(args)
        service = PlanningService(args.output_dir / "sessions.sqlite3")
        session_id = args.session
        if session_id:
            values = service.store.load(session_id)["request"]
        question = args.question
        if args.ask is not None:
            if mode != "live":
                print("自然语言条件抽取需要真实模型，请加 --live。")
                return 1
            from .config import ModelConfig
            from .extraction import extract_until_complete, merge
            from .providers import APIProvider
            supplied = list(args.answer or [])

            def ask(prompt: str):
                # 优先用 --answer 提供的补充（便于脚本化与自动化测试）；
                # 其次是终端交互；两者都没有就只报出待确认的问题。
                if supplied:
                    print(prompt)
                    print("你的补充：", supplied[0])
                    return supplied.pop(0)
                if not sys.stdin.isatty():
                    return None
                return input(prompt + "\n你的补充：")

            result = extract_until_complete(args.ask, APIProvider(ModelConfig.from_env()), ask=ask)
            print("从这句话抽取到的条件：", json.dumps(result.provided, ensure_ascii=False))
            if result.asked:
                print(f"经过 {result.rounds} 轮补充后条件已齐全。")
            if not result.complete:
                print(result.pending)
                if not supplied and not sys.stdin.isatty():
                    print("（可用 --answer 提供补充，或在终端里直接运行以交互追问。）")
                return 2
            values = merge(values, result.provided)
            question = result.text
            print("已合并进表单条件，开始规划。")
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
