"""Roster import and student matching.

The teacher has a full class roster, but the model may misread a hand-written
name.  Matching is therefore conservative: exact student number, exact name,
alias, then a fuzzy name match; anything below the threshold stays unmatched and
is shown in the review queue instead of being silently assigned to the wrong
student.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .. import db

_STRIP_RE = re.compile(r"[\s·.．,，、:：;；()（）\[\]【】]")


def normalize_name(value: str) -> str:
    return _STRIP_RE.sub("", (value or "").strip())


def normalize_no(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _header_map(headers: Iterable[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for index, header in enumerate(headers):
        text = (header or "").strip().lower()
        if not text:
            continue
        if "姓名" in text or text in {"name", "student", "student_name"}:
            mapping.setdefault("name", index)
        elif "学号" in text or "座号" in text or text in {"no", "number", "student_no", "id"}:
            mapping.setdefault("no", index)
        elif "班级" in text or text in {"class", "class_name"}:
            mapping.setdefault("class_name", index)
    return mapping


def _rows_from_csv(path: Path) -> list[list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(2048)
        handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        return [list(row) for row in csv.reader(handle, dialect)]


def _rows_from_xlsx(path: Path) -> list[list[str]]:
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    sheet = workbook.active
    rows = []
    for row in sheet.iter_rows(values_only=True):
        rows.append(["" if value is None else str(value) for value in row])
    workbook.close()
    return rows


def import_roster(db_path: Path | str, path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if source.suffix.lower() in {".xlsx", ".xlsm"}:
        rows = _rows_from_xlsx(source)
    else:
        rows = _rows_from_csv(source)
    if not rows:
        return {"ok": False, "error": "名单为空", "imported": 0, "skipped": 0}

    headers = rows[0]
    mapping = _header_map(headers)
    start = 1
    if not mapping:
        # No recognisable header: assume name, no, class columns.
        mapping = {"name": 0, "no": 1, "class_name": 2}
        start = 0

    imported = 0
    skipped = 0

    def cell(row: list[str], key: str) -> str:
        index = mapping.get(key)
        if index is None or index >= len(row):
            return ""
        return row[index].strip()

    for row in rows[start:]:
        name = cell(row, "name")
        no = cell(row, "no")
        class_name = cell(row, "class_name")
        if not name and not no:
            skipped += 1
            continue
        db.upsert_student(db_path, name=name, no=no, class_name=class_name)
        imported += 1
    return {"ok": True, "imported": imported, "skipped": skipped, "source": str(source)}


def match_student(
    db_path: Path | str,
    name: str = "",
    no: str = "",
    class_name: str = "",
    threshold: float = 0.84,
) -> tuple[dict[str, Any] | None, str, float]:
    """Return (student, method, score).  `method` is empty when unmatched."""

    students = db.list_students(db_path, class_name=class_name or None)
    if not students:
        students = db.list_students(db_path)
    if not students:
        return None, "", 0.0

    target_no = normalize_no(no)
    target_name = normalize_name(name)
    if target_no:
        for student in students:
            if normalize_no(student.get("no", "")) == target_no:
                return student, "no", 1.0
    if target_name:
        for student in students:
            if normalize_name(student.get("name", "")) == target_name:
                return student, "name", 1.0
        for student in students:
            if target_name in {normalize_name(alias) for alias in student.get("aliases", [])}:
                return student, "alias", 0.98

    best: tuple[dict[str, Any] | None, float] = (None, 0.0)
    if target_name:
        for student in students:
            candidate = normalize_name(student.get("name", ""))
            if not candidate:
                continue
            ratio = SequenceMatcher(None, target_name, candidate).ratio()
            if ratio > best[1]:
                best = (student, ratio)
    if best[0] is not None and best[1] >= threshold:
        return best[0], "fuzzy", round(best[1], 3)
    return None, "", round(best[1], 3)


def auto_register(
    db_path: Path | str, name: str, no: str = "", class_name: str = ""
) -> int | None:
    if not name and not no:
        return None
    return db.upsert_student(db_path, name=name, no=no, class_name=class_name)
