"""Command line entry point.

Examples::

    chemeq demo
    chemeq serve --open
    chemeq grade --folder "D:/作业/周三" --worksheet 1
    chemeq report --worksheet 1
    chemeq doctor --net
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import webbrowser
from pathlib import Path

from . import db
from .config import Config, load_config, mask_secret
from .core.answer_key import extract_docx_candidates, parse_answer_key
from .core.grade import ensure_db, grade_folder
from .core.report import export_html, export_xlsx
from .net import lan_ip, port_available
from .transcribe import test_connection


def _print_table(rows: list[dict], columns: list[tuple[str, str]]) -> None:
    if not rows:
        print("（空）")
        return
    widths = []
    for key, label in columns:
        width = max(len(label), *(len(str(row.get(key, ""))) for row in rows))
        widths.append(min(width, 40))
    header = "  ".join(label.ljust(width) for (_, label), width in zip(columns, widths, strict=True))
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            "  ".join(
                str(row.get(key, ""))[:width].ljust(width)
                for (key, _), width in zip(columns, widths, strict=True)
            )
        )


def _resolve_worksheet(cfg: Config, value: str) -> int:
    ensure_db(cfg)
    if value.isdigit():
        worksheet = db.get_worksheet(cfg.db_path, int(value))
        if worksheet:
            return int(value)
    for worksheet in db.list_worksheets(cfg.db_path):
        if worksheet["title"] == value:
            return int(worksheet["id"])
    raise SystemExit(f"找不到作业：{value}")


def cmd_serve(args: argparse.Namespace) -> int:
    cfg = load_config()
    if args.host:
        cfg.host = args.host
    requested = args.port or cfg.port
    port = int(requested)
    if not port_available(port):
        for candidate in range(port + 1, port + 30):
            if port_available(candidate):
                port = candidate
                break
        else:
            raise SystemExit(f"端口 {requested} 及后续 29 个端口都被占用，请用 --port 指定空闲端口")
    cfg.port = port
    cfg.save()
    ensure_db(cfg)
    from .web.app import create_app

    app = create_app(cfg)
    if args.open:
        def _open() -> None:
            time.sleep(1.2)
            webbrowser.open(f"http://127.0.0.1:{cfg.port}")
        threading.Thread(target=_open, daemon=True).start()
    print(f"智批已启动：http://127.0.0.1:{cfg.port}")
    print(f"手机端：http://{lan_ip()}:{cfg.port}/m/{cfg.mobile_token}")
    import uvicorn

    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    cfg = load_config()
    ensure_db(cfg)
    from .core.demo import ensure_demo

    worksheet_id = ensure_demo(cfg)
    print(f"演示作业已生成：#{worksheet_id}")
    print(f"打开：http://127.0.0.1:{cfg.port}/worksheets/{worksheet_id}")
    print(f"手机端：http://{lan_ip()}:{cfg.port}/m/{cfg.mobile_token}")
    return 0


def cmd_grade(args: argparse.Namespace) -> int:
    cfg = load_config()
    worksheet_id = _resolve_worksheet(cfg, args.worksheet)
    result = grade_folder(cfg, args.folder, worksheet_id, limit=args.limit)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    ok = [item for item in result["results"] if item.get("ok")]
    failed = [item for item in result["results"] if not item.get("ok") and not item.get("skipped")]
    print(f"文件夹：{args.folder}")
    print(f"共 {result['count']} 个文件；成功 {len(ok)}，失败 {len(failed)}")
    for item in ok:
        print(
            f"  ✓ {Path(item.get('file', '')).name}: {item.get('student_match')} "
            f"{item.get('score')}/{item.get('max_score')}"
        )
    for item in failed:
        print(f"  ✗ {Path(item.get('file', '')).name}: {item.get('error')}")
    return 0 if not failed else 1


def cmd_report(args: argparse.Namespace) -> int:
    cfg = load_config()
    worksheet_id = _resolve_worksheet(cfg, args.worksheet)
    if args.html:
        path = export_html(cfg, worksheet_id, args.out)
    else:
        path = export_xlsx(cfg, worksheet_id, args.out)
    print(path)
    return 0


def cmd_worksheet(args: argparse.Namespace) -> int:
    cfg = load_config()
    ensure_db(cfg)
    if args.action == "list":
        rows = db.list_worksheets(cfg.db_path)
        _print_table(
            rows,
            [("id", "ID"), ("title", "作业"), ("class_name", "班级"), ("question_count", "题数"), ("submission_count", "提交")],
        )
        return 0
    if args.action == "create":
        text = Path(args.answers).read_text(encoding="utf-8-sig")
        items, warnings = parse_answer_key(text)
        valid = [item for item in items if item.valid]
        for warning in warnings:
            print(f"警告：{warning}")
        if not valid:
            print("没有可用的标准答案。每行格式：1. 2H2 + O2 --点燃--> 2H2O", file=sys.stderr)
            return 1
        worksheet_id = db.create_worksheet(
            cfg.db_path,
            args.title,
            args.class_name,
            [item.as_question() for item in valid],
        )
        print(f"已创建作业 #{worksheet_id}：{args.title}，{len(valid)} 道题")
        return 0
    return 1


def cmd_roster(args: argparse.Namespace) -> int:
    cfg = load_config()
    ensure_db(cfg)
    from .core.roster import import_roster

    result = import_roster(cfg.db_path, args.file)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = load_config()
    ensure_db(cfg)
    print("== 智批诊断 ==")
    print(f"数据目录：{cfg.data_dir}")
    print(f"数据库：{cfg.db_path}")
    print(f"模型：{cfg.model}  base_url={cfg.base_url}")
    print(f"API Key：{mask_secret(cfg.api_key) or '未填写'}")
    print(f"监听：{cfg.host}:{cfg.port}  端口可用={port_available(cfg.port)}")
    print(f"局域网 IP：{lan_ip()}")
    print(f"管理端：http://127.0.0.1:{cfg.port}")
    print(f"手机端：http://{lan_ip()}:{cfg.port}/m/{cfg.mobile_token}")
    counts = db.worksheet_counts(cfg.db_path)
    print(f"数据：作业 {counts['worksheets']}，提交 {counts['submissions']}，待处理 {counts['pending']}")
    print(f"严格评分（错一题不给分）：{cfg.strict_scoring}")
    if args.net:
        result = test_connection(cfg)
        print(f"模型连通性：{'OK' if result.get('ok') else '失败'}")
        if not result.get("ok"):
            print(f"  原因：{result.get('error')}")
        else:
            print(f"  延迟：{result.get('latency_ms')} ms")
    return 0


def cmd_answer(args: argparse.Namespace) -> int:
    if args.action == "extract-docx":
        candidates, warnings = extract_docx_candidates(args.file)
        for line in candidates:
            print(line)
        for warning in warnings:
            print(f"# 警告：{warning}", file=sys.stderr)
        return 0
    return 1


def cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp_server import main as mcp_main

    mcp_main()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chemeq", description="ChemEq Grader · 化学方程式拍照批改")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="启动本地管理端和手机上传页")
    serve.add_argument("--host", default="")
    serve.add_argument("--port", type=int, default=0)
    serve.add_argument("--open", action="store_true", help="启动后打开浏览器")
    serve.set_defaults(func=cmd_serve)

    demo = sub.add_parser("demo", help="生成合成演示数据")
    demo.set_defaults(func=cmd_demo)

    grade = sub.add_parser("grade", help="批改一个文件夹里的作业照片")
    grade.add_argument("--folder", required=True)
    grade.add_argument("--worksheet", required=True, help="作业 ID 或标题")
    grade.add_argument("--limit", type=int, default=0)
    grade.add_argument("--json", action="store_true")
    grade.set_defaults(func=cmd_grade)

    report = sub.add_parser("report", help="导出 Excel/HTML 报告")
    report.add_argument("--worksheet", required=True)
    report.add_argument("--out", default="")
    report.add_argument("--html", action="store_true")
    report.set_defaults(func=cmd_report)

    worksheet = sub.add_parser("worksheet", help="作业管理")
    worksheet.add_argument("action", choices=["list", "create"])
    worksheet.add_argument("--title", default="")
    worksheet.add_argument("--class-name", default="")
    worksheet.add_argument("--answers", default="")
    worksheet.set_defaults(func=cmd_worksheet)

    roster = sub.add_parser("roster", help="导入学生名单")
    roster.add_argument("action", choices=["import"])
    roster.add_argument("--file", required=True)
    roster.set_defaults(func=cmd_roster)

    doctor = sub.add_parser("doctor", help="自检")
    doctor.add_argument("--net", action="store_true", help="测试模型连通性")
    doctor.set_defaults(func=cmd_doctor)

    answer = sub.add_parser("answer", help="答案导入辅助")
    answer.add_argument("action", choices=["extract-docx"])
    answer.add_argument("--file", required=True)
    answer.set_defaults(func=cmd_answer)

    mcp = sub.add_parser("mcp", help="启动 WorkBuddy/MCP stdio 服务")
    mcp.set_defaults(func=cmd_mcp)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
