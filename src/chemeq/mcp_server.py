"""MCP stdio server for WorkBuddy and other agents.

Tools operate directly on the local database; the HTTP admin UI does not need to
be running.  Start it with::

    chemeq mcp

WorkBuddy's mcp.json entry is::

    {"mcpServers": {"chemeq": {"command": "chemeq.exe", "args": ["mcp"]}}}
"""

from __future__ import annotations

from pathlib import Path

from mcp.server.mcpserver import MCPServer

from . import db
from .config import load_config
from .core.answer_key import parse_answer_key
from .core.grade import (
    ensure_db,
    grade_folder,
    regrade_from_stored,
    worksheet_summary,
)
from .core.report import export_html, export_xlsx
from .core.roster import import_roster

server = MCPServer(
    "chemeq",
    version="0.1.1",
    instructions=(
        "ChemEq Grader：本地化学方程式批改。先 list_worksheets 找到作业；"
        "grade_folder 批改一个文件夹里的学生作业照片；worksheet_report 导出 Excel/HTML。"
        "老师必须复核；不要把“已批改”当成“已确认”。"
    ),
)


def _resolve_worksheet(cfg, value: str | int) -> int:
    if str(value).isdigit():
        worksheet = db.get_worksheet(cfg.db_path, int(value))
        if worksheet:
            return int(value)
    for worksheet in db.list_worksheets(cfg.db_path):
        if worksheet["title"] == str(value):
            return int(worksheet["id"])
    raise ValueError(f"找不到作业：{value}")


@server.tool()
def list_worksheets() -> list[dict]:
    """列出本地所有作业，含题数、提交数和待处理数。"""

    cfg = load_config()
    ensure_db(cfg)
    return db.list_worksheets(cfg.db_path)


@server.tool()
def create_worksheet(title: str, class_name: str, answers_text: str) -> dict:
    """新建作业。answers_text 每行一题，格式：题号 | 标准答案 | 分值。"""

    cfg = load_config()
    ensure_db(cfg)
    items, warnings = parse_answer_key(answers_text)
    invalid = [item for item in items if not item.valid]
    if not items or invalid:
        raise ValueError("；".join(warnings) or "没有可用的标准答案")
    worksheet_id = db.create_worksheet(
        cfg.db_path, title, class_name, [item.as_question() for item in items]
    )
    return {
        "ok": True,
        "worksheet_id": worksheet_id,
        "question_count": len(items),
        "warnings": warnings,
    }


@server.tool()
def grade_folder_tool(folder: str, worksheet: str, limit: int = 0) -> dict:
    """批改一个文件夹里的学生作业照片；worksheet 可以是 ID 或标题。"""

    cfg = load_config()
    ensure_db(cfg)
    worksheet_id = _resolve_worksheet(cfg, worksheet)
    result = grade_folder(cfg, Path(folder), worksheet_id, limit=limit or None)
    compact = []
    for item in result["results"]:
        compact.append(
            {
                "file": Path(item.get("file", "")).name,
                "ok": item.get("ok", False),
                "submission_id": item.get("submission_id"),
                "student": (item.get("student") or {}).get("name", ""),
                "student_match": item.get("student_match", ""),
                "score": item.get("score"),
                "max_score": item.get("max_score"),
                "needs_review": item.get("needs_review"),
                "error": item.get("error", ""),
            }
        )
    return {
        "ok": True,
        "worksheet_id": worksheet_id,
        "count": result["count"],
        "results": compact,
    }


@server.tool()
def get_submission(submission_id: int) -> dict:
    """读取一份提交的转写、逐题判定与得分。"""

    cfg = load_config()
    ensure_db(cfg)
    submission = db.get_submission(cfg.db_path, submission_id)
    if not submission:
        raise ValueError("提交不存在")
    answers = db.get_answers(cfg.db_path, submission_id)
    pages = db.get_pages(cfg.db_path, submission_id)
    return {
        "submission": submission,
        "pages": [{k: v for k, v in page.items() if k != "transcription_json"} for page in pages],
        "answers": answers,
    }


@server.tool()
def regrade_submission(submission_id: int) -> dict:
    """按已保存的转写重新判定，不调用视觉模型。"""

    cfg = load_config()
    ensure_db(cfg)
    return regrade_from_stored(cfg, submission_id)


@server.tool()
def worksheet_report(worksheet: str, export: str = "xlsx") -> dict:
    """导出 Excel（export=xlsx）或可打印 HTML（export=html），返回文件路径。"""

    cfg = load_config()
    ensure_db(cfg)
    worksheet_id = _resolve_worksheet(cfg, worksheet)
    path = export_html(cfg, worksheet_id) if export == "html" else export_xlsx(cfg, worksheet_id)
    summary = worksheet_summary(cfg, worksheet_id)["summary"]
    return {
        "ok": True,
        "path": str(path),
        "summary": {
            "student_count": summary["student_count"],
            "average": summary["average"],
            "max_score": summary["max_score"],
            "pass_rate": summary["pass_rate"],
            "needs_review": summary["needs_review"],
            "need_fix": summary["need_fix"],
            "top_errors": summary["top_errors"],
        },
    }


@server.tool()
def list_students() -> list[dict]:
    """列出本地学生名单。"""

    cfg = load_config()
    ensure_db(cfg)
    return db.list_students(cfg.db_path)


@server.tool()
def import_students(file_path: str) -> dict:
    """导入 CSV/Excel 名单（列名：姓名、学号、班级）。"""

    cfg = load_config()
    ensure_db(cfg)
    return import_roster(cfg.db_path, file_path)


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
