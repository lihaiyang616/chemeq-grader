"""Excel and printable HTML reports for one worksheet."""

from __future__ import annotations

import html
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from ..config import Config
from .grade import GRADEABLE_TYPES, normalize_qno, worksheet_summary

HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(bold=True, color="FFFFFF", name="微软雅黑", size=10)
BODY_FONT = Font(name="微软雅黑", size=10)
WRONG_FILL = PatternFill("solid", fgColor="FCE4E4")
REVIEW_FILL = PatternFill("solid", fgColor="FFF2CC")
THIN = Side(style="thin", color="D9D9D9")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _style_header(sheet, row: int, columns: int) -> None:
    for column in range(1, columns + 1):
        cell = sheet.cell(row=row, column=column)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER


def _autosize(sheet, widths: dict[int, int]) -> None:
    for index, width in widths.items():
        sheet.column_dimensions[get_column_letter(index)].width = width


def _verdict_label(verdict: str) -> str:
    return {
        "correct": "正确",
        "partial": "有错（0分）",
        "wrong": "错误",
        "uncertain": "待复核",
    }.get(verdict, verdict)


def _error_text(error_types: list[str]) -> str:
    return "、".join(error_types) if error_types else ""


def build_report(cfg: Config, worksheet_id: int) -> dict[str, Any]:
    data = worksheet_summary(cfg, worksheet_id)
    worksheet = data["worksheet"]
    questions = data["questions"]
    submissions = data["submissions"]
    answers = [a for a in data["answers"] if (a.get("question_type") or "equation") in GRADEABLE_TYPES]
    qnos = [normalize_qno(q["qno"]) for q in questions]
    student_by_id = {s["id"]: s for s in submissions}
    answer_by_submission: dict[int, list[dict[str, Any]]] = {}
    for answer in answers:
        answer_by_submission.setdefault(int(answer["submission_id"]), []).append(answer)

    student_rows = []
    for submission in submissions:
        student_answers = answer_by_submission.get(int(submission["id"]), [])
        wrong = [a for a in student_answers if a["verdict"] != "correct"]
        student_rows.append(
            {
                "submission_id": submission["id"],
                "no": submission.get("student_no") or submission.get("student_no_raw") or "",
                "name": submission.get("student_name") or submission.get("student_name_raw") or "未识别",
                "class_name": submission.get("student_class") or submission.get("student_class_raw") or "",
                "page_count": submission.get("page_count", 1),
                "score": submission.get("score"),
                "max_score": submission.get("max_score") or data["summary"]["max_score"],
                "wrong_count": len(wrong),
                "wrong_qnos": [normalize_qno(a["qno"]) for a in wrong],
                "needs_review": bool(submission.get("needs_review")),
                "status": submission.get("status", ""),
                "created_at": submission.get("created_at", ""),
            }
        )

    detail_rows = []
    for answer in answers:
        submission = student_by_id.get(int(answer["submission_id"]), {})
        detail_rows.append(
            {
                "no": submission.get("student_no") or submission.get("student_no_raw") or "",
                "name": submission.get("student_name") or submission.get("student_name_raw") or "未识别",
                "qno": normalize_qno(answer["qno"]),
                "student_raw": answer.get("student_raw", ""),
                "answer": answer.get("answer_eq", ""),
                "verdict": answer.get("verdict", ""),
                "error_types": answer.get("error_types", []),
                "detail": answer.get("detail", ""),
                "score": answer.get("score"),
                "max_score": answer.get("max_score"),
                "comment": answer.get("comment", ""),
            }
        )
    detail_rows.sort(key=lambda row: (row["no"], qnos.index(row["qno"]) if row["qno"] in qnos else 99))
    wrong_rows = [row for row in detail_rows if row["verdict"] != "correct"]

    matrix_rows = []
    for student in student_rows:
        by_qno = {
            row["qno"]: row for row in detail_rows if row["name"] == student["name"] and row["no"] == student["no"]
        }
        matrix_rows.append(
            {
                "no": student["no"],
                "name": student["name"],
                "cells": {
                    qno: (
                        "✓"
                        if qno in by_qno and by_qno[qno]["verdict"] == "correct"
                        else "待定"
                        if qno in by_qno and by_qno[qno]["verdict"] == "uncertain"
                        else "✗"
                        if qno in by_qno
                        else "-"
                    )
                    for qno in qnos
                },
            }
        )

    need_fix = data["summary"]["need_fix"]
    return {
        "worksheet": worksheet,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "summary": data["summary"],
        "questions": questions,
        "qnos": qnos,
        "student_rows": student_rows,
        "detail_rows": detail_rows,
        "wrong_rows": wrong_rows,
        "matrix_rows": matrix_rows,
        "need_fix": need_fix,
        "error_top": data["summary"]["top_errors"],
    }


def export_xlsx(cfg: Config, worksheet_id: int, out_path: str | Path | None = None) -> Path:
    report = build_report(cfg, worksheet_id)
    title = report["worksheet"]["title"]
    if out_path is None:
        cfg.reports_dir.mkdir(parents=True, exist_ok=True)
        safe = "".join(ch for ch in title if ch not in '\\/:*?"<>|') or "report"
        out_path = cfg.reports_dir / f"{safe}-错题报告.xlsx"
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    workbook = Workbook()
    thin = BORDER

    # 1. 学生汇总
    sheet = workbook.active
    sheet.title = "学生汇总"
    headers = ["学号", "姓名", "班级", "页数", "得分", "满分", "得分率", "错题数", "待复核", "状态", "提交时间"]
    sheet.append(headers)
    _style_header(sheet, 1, len(headers))
    for row in report["student_rows"]:
        rate = f"{(row['score'] or 0) / row['max_score'] * 100:.0f}%" if row["max_score"] else "-"
        sheet.append(
            [
                row["no"],
                row["name"],
                row["class_name"],
                row["page_count"],
                row["score"],
                row["max_score"],
                rate,
                row["wrong_count"],
                "是" if row["needs_review"] else "",
                row["status"],
                row["created_at"],
            ]
        )
        for cell in sheet[sheet.max_row]:
            cell.font = BODY_FONT
            cell.border = thin
        if row["needs_review"]:
            for cell in sheet[sheet.max_row]:
                cell.fill = REVIEW_FILL
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:K{sheet.max_row}"
    _autosize(sheet, {1: 10, 2: 12, 3: 12, 4: 6, 5: 8, 6: 8, 7: 8, 8: 8, 9: 8, 10: 14, 11: 20})

    # 2. 错题明细
    sheet = workbook.create_sheet("错题明细")
    headers = ["学号", "姓名", "题号", "学生答案", "标准答案", "判定", "错因", "得分", "满分", "说明"]
    sheet.append(headers)
    _style_header(sheet, 1, len(headers))
    for row in report["wrong_rows"]:
        sheet.append(
            [
                row["no"],
                row["name"],
                row["qno"],
                row["student_raw"],
                row["answer"],
                _verdict_label(row["verdict"]),
                _error_text(row["error_types"]),
                row["score"],
                row["max_score"],
                row["detail"],
            ]
        )
        for cell in sheet[sheet.max_row]:
            cell.font = BODY_FONT
            cell.border = thin
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        for cell in sheet[sheet.max_row]:
            cell.fill = WRONG_FILL
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:J{sheet.max_row}"
    _autosize(sheet, {1: 10, 2: 12, 3: 8, 4: 32, 5: 32, 6: 10, 7: 18, 8: 8, 9: 8, 10: 34})

    # 3. 题目统计
    sheet = workbook.create_sheet("题目统计")
    headers = ["题号", "标准答案", "满分", "作答人数", "错误人数", "错误率", "主要错因"]
    sheet.append(headers)
    _style_header(sheet, 1, len(headers))
    for item in report["summary"]["per_question"]:
        top = "、".join(f"{name}×{count}" for name, count in item["top_errors"])
        sheet.append(
            [
                item["qno"],
                item["answer"],
                item["max_score"],
                item["answered"],
                item["wrong"],
                f"{item['wrong_rate']}%",
                top,
            ]
        )
        for cell in sheet[sheet.max_row]:
            cell.font = BODY_FONT
            cell.border = thin
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    sheet.freeze_panes = "A2"
    _autosize(sheet, {1: 8, 2: 40, 3: 8, 4: 10, 5: 10, 6: 10, 7: 36})

    # 4. 错题矩阵
    sheet = workbook.create_sheet("错题矩阵")
    headers = ["学号", "姓名"] + report["qnos"]
    sheet.append(headers)
    _style_header(sheet, 1, len(headers))
    for row in report["matrix_rows"]:
        values = [row["no"], row["name"]] + [row["cells"].get(qno, "-") for qno in report["qnos"]]
        sheet.append(values)
        for cell in sheet[sheet.max_row]:
            cell.font = BODY_FONT
            cell.border = thin
            cell.alignment = Alignment(horizontal="center")
            if cell.value == "✗":
                cell.fill = WRONG_FILL
            elif cell.value == "待定":
                cell.fill = REVIEW_FILL
    sheet.freeze_panes = "C2"
    _autosize(sheet, {1: 10, 2: 12})

    # 5. 订正名单
    sheet = workbook.create_sheet("订正名单")
    headers = ["学号", "姓名", "得分", "错题号", "主要错因", "订正情况"]
    sheet.append(headers)
    _style_header(sheet, 1, len(headers))
    for row in report["need_fix"]:
        errors = Counter()
        for detail in report["detail_rows"]:
            if detail["name"] == row["student"] and detail["no"] == row["no"]:
                errors.update(detail["error_types"])
        sheet.append(
            [
                row["no"],
                row["student"],
                row["score"],
                "、".join(row["wrong_qnos"]),
                "、".join(name for name, _ in errors.most_common(3)),
                "",
            ]
        )
        for cell in sheet[sheet.max_row]:
            cell.font = BODY_FONT
            cell.border = thin
    sheet.freeze_panes = "A2"
    _autosize(sheet, {1: 10, 2: 12, 3: 8, 4: 24, 5: 24, 6: 20})

    # 6. 逐题明细（全部）
    sheet = workbook.create_sheet("逐题明细")
    headers = ["学号", "姓名", "题号", "学生答案", "标准答案", "判定", "错因", "得分", "满分"]
    sheet.append(headers)
    _style_header(sheet, 1, len(headers))
    for row in report["detail_rows"]:
        sheet.append(
            [
                row["no"],
                row["name"],
                row["qno"],
                row["student_raw"],
                row["answer"],
                _verdict_label(row["verdict"]),
                _error_text(row["error_types"]),
                row["score"],
                row["max_score"],
            ]
        )
        for cell in sheet[sheet.max_row]:
            cell.font = BODY_FONT
            cell.border = thin
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:I{sheet.max_row}"
    _autosize(sheet, {1: 10, 2: 12, 3: 8, 4: 30, 5: 30, 6: 10, 7: 18, 8: 8, 9: 8})

    workbook.save(path)
    return path


def export_html(cfg: Config, worksheet_id: int, out_path: str | Path | None = None) -> Path:
    report = build_report(cfg, worksheet_id)
    title = report["worksheet"]["title"]
    if out_path is None:
        cfg.reports_dir.mkdir(parents=True, exist_ok=True)
        safe = "".join(ch for ch in title if ch not in '\\/:*?"<>|') or "report"
        out_path = cfg.reports_dir / f"{safe}-学情报告.html"
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = report["summary"]
    rows = []
    for row in report["student_rows"]:
        wrong = "、".join(row["wrong_qnos"])
        rows.append(
            "<tr>"
            f"<td>{html.escape(row['no'])}</td>"
            f"<td>{html.escape(row['name'])}</td>"
            f"<td>{row['score'] if row['score'] is not None else '-'}</td>"
            f"<td>{html.escape(wrong)}</td>"
            f"<td>{'是' if row['needs_review'] else ''}</td>"
            "</tr>"
        )
    question_rows = []
    for item in summary["per_question"]:
        top = "、".join(f"{html.escape(name)}×{count}" for name, count in item["top_errors"])
        question_rows.append(
            "<tr>"
            f"<td>{html.escape(item['qno'])}</td>"
            f"<td class='eq'>{html.escape(item['answer'])}</td>"
            f"<td>{item['max_score']:g}</td>"
            f"<td>{item['wrong']}/{item['answered']}</td>"
            f"<td>{item['wrong_rate']}%</td>"
            f"<td>{top}</td>"
            "</tr>"
        )
    detail_rows = []
    for row in report["wrong_rows"]:
        detail_rows.append(
            "<tr>"
            f"<td>{html.escape(row['no'])}</td>"
            f"<td>{html.escape(row['name'])}</td>"
            f"<td>{html.escape(row['qno'])}</td>"
            f"<td class='eq'>{html.escape(row['student_raw'])}</td>"
            f"<td class='eq'>{html.escape(row['answer'])}</td>"
            f"<td>{html.escape(_verdict_label(row['verdict']))}</td>"
            f"<td>{html.escape(_error_text(row['error_types']))}</td>"
            f"<td>{html.escape(row['detail'])}</td>"
            "</tr>"
        )
    need_fix_rows = []
    for row in report["need_fix"]:
        need_fix_rows.append(
            "<tr>"
            f"<td>{html.escape(row['no'])}</td>"
            f"<td>{html.escape(row['student'])}</td>"
            f"<td>{row['score'] if row['score'] is not None else '-'}</td>"
            f"<td>{html.escape('、'.join(row['wrong_qnos']))}</td>"
            "<td></td>"
            "</tr>"
        )
    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{html.escape(title)} · 学情报告</title>
<style>
:root {{ color-scheme: light; }}
body {{ font-family: "Microsoft YaHei", "PingFang SC", system-ui, sans-serif; margin: 0; color: #1f2937; background: #f5f7fb; }}
.page {{ max-width: 1100px; margin: 0 auto; padding: 32px; background: #fff; }}
h1 {{ font-size: 24px; margin: 0 0 4px; }}
.meta {{ color: #64748b; font-size: 13px; margin-bottom: 24px; }}
.cards {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-bottom: 24px; }}
.card {{ border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px; }}
.card .num {{ font-size: 26px; font-weight: 700; color: #0f766e; }}
.card .label {{ font-size: 12px; color: #64748b; margin-top: 4px; }}
h2 {{ font-size: 17px; margin: 28px 0 10px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th, td {{ border: 1px solid #e2e8f0; padding: 7px 8px; vertical-align: top; }}
th {{ background: #f1f5f9; text-align: left; }}
.eq {{ font-family: "Cambria Math", "Microsoft YaHei", monospace; }}
.bad {{ color: #b91c1c; font-weight: 600; }}
.muted {{ color: #64748b; }}
@media print {{
  body {{ background: #fff; }}
  .page {{ max-width: none; padding: 0; }}
  .no-print {{ display: none; }}
  h2 {{ page-break-after: avoid; }}
  tr {{ page-break-inside: avoid; }}
}}
</style>
</head>
<body>
<div class="page">
  <h1>{html.escape(title)} · 学情报告</h1>
  <div class="meta">{html.escape(report['worksheet'].get('class_name') or '')} · 生成于 {report['generated_at']} · 只批改方程式题</div>
  <div class="cards">
    <div class="card"><div class="num">{summary['student_count']}</div><div class="label">学生提交</div></div>
    <div class="card"><div class="num">{summary['graded_count']}</div><div class="label">已完成批改</div></div>
    <div class="card"><div class="num">{summary['average']}</div><div class="label">平均分 / {summary['max_score']:g}</div></div>
    <div class="card"><div class="num">{summary['pass_rate']}%</div><div class="label">及格率</div></div>
    <div class="card"><div class="num">{summary['needs_review']}</div><div class="label">待复核份数</div></div>
  </div>
  <h2>需订正名单</h2>
  <table><thead><tr><th>学号</th><th>姓名</th><th>得分</th><th>错题号</th><th>订正情况</th></tr></thead><tbody>
  {''.join(need_fix_rows) or '<tr><td colspan="5" class="muted">没有需要订正的学生</td></tr>'}
  </tbody></table>
  <h2>题目统计</h2>
  <table><thead><tr><th>题号</th><th>标准答案</th><th>满分</th><th>错误/作答</th><th>错误率</th><th>主要错因</th></tr></thead><tbody>
  {''.join(question_rows)}
  </tbody></table>
  <h2>学生汇总</h2>
  <table><thead><tr><th>学号</th><th>姓名</th><th>得分</th><th>错题号</th><th>待复核</th></tr></thead><tbody>
  {''.join(rows)}
  </tbody></table>
  <h2>错题明细</h2>
  <table><thead><tr><th>学号</th><th>姓名</th><th>题号</th><th>学生答案</th><th>标准答案</th><th>判定</th><th>错因</th><th>说明</th></tr></thead><tbody>
  {''.join(detail_rows) or '<tr><td colspan="8" class="muted">没有错题</td></tr>'}
  </tbody></table>
  <p class="muted">说明：AI 只负责转写，配平/电荷/条件/状态由程序校验；老师复核后再作为最终成绩。</p>
  <p class="no-print"><button onclick="window.print()">打印 / 导出 PDF</button></p>
</div>
</body>
</html>
"""
    path.write_text(html_text, encoding="utf-8")
    return path
