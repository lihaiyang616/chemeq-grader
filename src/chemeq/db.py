"""SQLite persistence for ChemEq Grader.

The app is single-teacher and single-machine, so a small hand-written DAO is
enough and keeps the Windows bundle lean.  Every public function takes the
database path explicitly; callers open short-lived connections, which sidesteps
SQLite's thread affinity rules for the background grading workers.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS worksheets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    class_name TEXT NOT NULL DEFAULT '',
    subject TEXT NOT NULL DEFAULT 'chemistry',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worksheet_id INTEGER NOT NULL REFERENCES worksheets(id) ON DELETE CASCADE,
    qno TEXT NOT NULL,
    answer_eq TEXT NOT NULL,
    alternatives TEXT NOT NULL DEFAULT '[]',
    max_score REAL NOT NULL DEFAULT 2,
    require_conditions INTEGER NOT NULL DEFAULT 1,
    require_states INTEGER NOT NULL DEFAULT 1,
    question_type TEXT NOT NULL DEFAULT 'equation',
    prompt_text TEXT NOT NULL DEFAULT '',
    UNIQUE(worksheet_id, qno)
);

CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    class_name TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    no TEXT NOT NULL DEFAULT '',
    aliases TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    UNIQUE(class_name, name, no)
);

CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worksheet_id INTEGER NOT NULL REFERENCES worksheets(id) ON DELETE CASCADE,
    student_id INTEGER REFERENCES students(id) ON DELETE SET NULL,
    image_path TEXT NOT NULL,
    image_sha256 TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    student_name_raw TEXT NOT NULL DEFAULT '',
    student_no_raw TEXT NOT NULL DEFAULT '',
    student_class_raw TEXT NOT NULL DEFAULT '',
    transcription_json TEXT NOT NULL DEFAULT '',
    score REAL,
    max_score REAL NOT NULL DEFAULT 0,
    needs_review INTEGER NOT NULL DEFAULT 1,
    error TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    cost_cny REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(worksheet_id, image_sha256)
);

CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    qno TEXT NOT NULL,
    student_raw TEXT NOT NULL DEFAULT '',
    student_canonical TEXT NOT NULL DEFAULT '',
    verdict TEXT NOT NULL DEFAULT 'uncertain',
    error_types TEXT NOT NULL DEFAULT '[]',
    detail TEXT NOT NULL DEFAULT '',
    score REAL,
    max_score REAL NOT NULL DEFAULT 2,
    comment TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0,
    needs_review INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    UNIQUE(submission_id, qno)
);

CREATE TABLE IF NOT EXISTS submission_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    page_no INTEGER NOT NULL DEFAULT 1,
    image_path TEXT NOT NULL,
    image_sha256 TEXT NOT NULL DEFAULT '',
    transcription_json TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(submission_id, page_no)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id INTEGER,
    level TEXT NOT NULL DEFAULT 'info',
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_submissions_worksheet ON submissions(worksheet_id);
CREATE INDEX IF NOT EXISTS idx_submissions_student ON submissions(student_id);
CREATE INDEX IF NOT EXISTS idx_answers_submission ON answers(submission_id);
CREATE INDEX IF NOT EXISTS idx_answers_qno ON answers(qno);
CREATE INDEX IF NOT EXISTS idx_pages_submission ON submission_pages(submission_id);
CREATE INDEX IF NOT EXISTS idx_events_submission ON events(submission_id);
"""


def init_db(db_path: Path | str) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        if row is None:
            conn.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
        conn.commit()
    finally:
        conn.close()


def _json_load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _decode_question(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["alternatives"] = _json_load(data.get("alternatives"), [])
    data["require_conditions"] = bool(data.get("require_conditions", 1))
    data["require_states"] = bool(data.get("require_states", 1))
    data.setdefault("question_type", "equation")
    data.setdefault("prompt_text", "")
    return data


def _decode_answer(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["error_types"] = _json_load(data.get("error_types"), [])
    data["needs_review"] = bool(data.get("needs_review", 1))
    return data


# ---------------------------------------------------------------------------
# Worksheets and questions
# ---------------------------------------------------------------------------


def create_worksheet(
    db_path: Path | str,
    title: str,
    class_name: str,
    questions: Iterable[dict[str, Any]],
    notes: str = "",
) -> int:
    conn = connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO worksheets(title, class_name, subject, notes, created_at) "
            "VALUES (?, ?, 'chemistry', ?, ?)",
            (title.strip(), class_name.strip(), notes.strip(), now_iso()),
        )
        worksheet_id = int(cur.lastrowid)
        for question in questions:
            alternatives = question.get("alternatives") or []
            if isinstance(alternatives, str):
                alternatives = [alternatives]
            conn.execute(
                "INSERT INTO questions(worksheet_id, qno, answer_eq, alternatives, max_score, "
                "require_conditions, require_states, question_type, prompt_text) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    worksheet_id,
                    str(question["qno"]).strip(),
                    str(question["answer"]).strip(),
                    json.dumps(list(alternatives), ensure_ascii=False),
                    float(question.get("max_score", 2)),
                    1 if question.get("require_conditions", True) else 0,
                    1 if question.get("require_states", True) else 0,
                    str(question.get("question_type", "equation")),
                    str(question.get("prompt_text", "")),
                ),
            )
        conn.commit()
        return worksheet_id
    finally:
        conn.close()


def update_worksheet(db_path: Path | str, worksheet_id: int, **fields: Any) -> None:
    allowed = {"title", "class_name", "notes"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    conn = connect(db_path)
    try:
        assignments = ", ".join(f"{key} = ?" for key in updates)
        conn.execute(
            f"UPDATE worksheets SET {assignments} WHERE id = ?",
            [*updates.values(), worksheet_id],
        )
        conn.commit()
    finally:
        conn.close()


def replace_questions(
    db_path: Path | str, worksheet_id: int, questions: Iterable[dict[str, Any]]
) -> None:
    conn = connect(db_path)
    try:
        conn.execute("DELETE FROM questions WHERE worksheet_id = ?", (worksheet_id,))
        for question in questions:
            alternatives = question.get("alternatives") or []
            if isinstance(alternatives, str):
                alternatives = [alternatives]
            conn.execute(
                "INSERT INTO questions(worksheet_id, qno, answer_eq, alternatives, max_score, "
                "require_conditions, require_states, question_type, prompt_text) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    worksheet_id,
                    str(question["qno"]).strip(),
                    str(question["answer"]).strip(),
                    json.dumps(list(alternatives), ensure_ascii=False),
                    float(question.get("max_score", 2)),
                    1 if question.get("require_conditions", True) else 0,
                    1 if question.get("require_states", True) else 0,
                    str(question.get("question_type", "equation")),
                    str(question.get("prompt_text", "")),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def get_worksheet(db_path: Path | str, worksheet_id: int) -> dict[str, Any] | None:
    conn = connect(db_path)
    try:
        row = conn.execute("SELECT * FROM worksheets WHERE id = ?", (worksheet_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_questions(db_path: Path | str, worksheet_id: int) -> list[dict[str, Any]]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM questions WHERE worksheet_id = ? ORDER BY id", (worksheet_id,)
        ).fetchall()
        return [_decode_question(row) for row in rows]
    finally:
        conn.close()


def list_worksheets(db_path: Path | str) -> list[dict[str, Any]]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT w.*,
                   (SELECT COUNT(*) FROM questions q WHERE q.worksheet_id = w.id) AS question_count,
                   (SELECT COUNT(*) FROM submissions s WHERE s.worksheet_id = w.id) AS submission_count,
                   (SELECT COUNT(*) FROM submissions s WHERE s.worksheet_id = w.id
                      AND s.status IN ('queued','processing','needs_review')) AS pending_count
            FROM worksheets w ORDER BY w.id DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def delete_worksheet(db_path: Path | str, worksheet_id: int) -> None:
    conn = connect(db_path)
    try:
        conn.execute("DELETE FROM worksheets WHERE id = ?", (worksheet_id,))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------


def upsert_student(
    db_path: Path | str,
    name: str,
    no: str = "",
    class_name: str = "",
    aliases: Iterable[str] | None = None,
) -> int:
    name = (name or "").strip()
    no = (no or "").strip()
    class_name = (class_name or "").strip()
    if not name and not no:
        raise ValueError("学生姓名和学号不能同时为空")
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT id FROM students WHERE class_name = ? AND name = ? AND no = ?",
            (class_name, name, no),
        ).fetchone()
        if row:
            return int(row["id"])
        cur = conn.execute(
            "INSERT INTO students(class_name, name, no, aliases, created_at) VALUES (?, ?, ?, ?, ?)",
            (class_name, name, no, json.dumps(list(aliases or []), ensure_ascii=False), now_iso()),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_students(db_path: Path | str, class_name: str | None = None) -> list[dict[str, Any]]:
    conn = connect(db_path)
    try:
        if class_name:
            rows = conn.execute(
                "SELECT * FROM students WHERE class_name = ? ORDER BY no, name", (class_name,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM students ORDER BY class_name, no, name").fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["aliases"] = _json_load(data.get("aliases"), [])
            result.append(data)
        return result
    finally:
        conn.close()


def find_student(
    db_path: Path | str, name: str = "", no: str = "", class_name: str = ""
) -> dict[str, Any] | None:
    conn = connect(db_path)
    try:
        if no:
            row = conn.execute(
                "SELECT * FROM students WHERE no = ? AND (? = '' OR class_name = ?) LIMIT 1",
                (no.strip(), class_name.strip(), class_name.strip()),
            ).fetchone()
            if row:
                return dict(row)
        if name:
            row = conn.execute(
                "SELECT * FROM students WHERE name = ? AND (? = '' OR class_name = ?) LIMIT 1",
                (name.strip(), class_name.strip(), class_name.strip()),
            ).fetchone()
            if row:
                return dict(row)
        return None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Submissions
# ---------------------------------------------------------------------------


def create_submission(
    db_path: Path | str,
    worksheet_id: int,
    image_path: str,
    image_sha256: str,
    student_id: int | None = None,
) -> tuple[int, bool]:
    conn = connect(db_path)
    try:
        existing = conn.execute(
            "SELECT id FROM submissions WHERE worksheet_id = ? AND image_sha256 = ?",
            (worksheet_id, image_sha256),
        ).fetchone()
        if existing:
            return int(existing["id"]), False
        timestamp = now_iso()
        cur = conn.execute(
            "INSERT INTO submissions(worksheet_id, student_id, image_path, image_sha256, status, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, 'queued', ?, ?)",
            (worksheet_id, student_id, image_path, image_sha256, timestamp, timestamp),
        )
        submission_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO submission_pages(submission_id, page_no, image_path, image_sha256, created_at) "
            "VALUES (?, 1, ?, ?, ?)",
            (submission_id, image_path, image_sha256, timestamp),
        )
        conn.commit()
        return submission_id, True
    finally:
        conn.close()


def add_page(
    db_path: Path | str,
    submission_id: int,
    page_no: int,
    image_path: str,
    image_sha256: str = "",
) -> int:
    conn = connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO submission_pages(submission_id, page_no, image_path, image_sha256, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (submission_id, page_no, image_path, image_sha256, now_iso()),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def get_pages(db_path: Path | str, submission_id: int) -> list[dict[str, Any]]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM submission_pages WHERE submission_id = ? ORDER BY page_no",
            (submission_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def update_page_transcription(
    db_path: Path | str, page_id: int, transcription_json: str
) -> None:
    conn = connect(db_path)
    try:
        conn.execute(
            "UPDATE submission_pages SET transcription_json = ? WHERE id = ?",
            (transcription_json, page_id),
        )
        conn.commit()
    finally:
        conn.close()


def update_submission(db_path: Path | str, submission_id: int, **fields: Any) -> None:
    allowed = {
        "student_id",
        "status",
        "student_name_raw",
        "student_no_raw",
        "student_class_raw",
        "transcription_json",
        "score",
        "max_score",
        "needs_review",
        "error",
        "model",
        "tokens_in",
        "tokens_out",
        "cost_cny",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    updates["updated_at"] = now_iso()
    conn = connect(db_path)
    try:
        assignments = ", ".join(f"{key} = ?" for key in updates)
        conn.execute(
            f"UPDATE submissions SET {assignments} WHERE id = ?",
            [*updates.values(), submission_id],
        )
        conn.commit()
    finally:
        conn.close()


def get_submission(db_path: Path | str, submission_id: int) -> dict[str, Any] | None:
    conn = connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT s.*, st.name AS student_name, st.no AS student_no, st.class_name AS student_class,
                   (SELECT COUNT(*) FROM submission_pages p WHERE p.submission_id = s.id) AS page_count
            FROM submissions s LEFT JOIN students st ON st.id = s.student_id
            WHERE s.id = ?
            """,
            (submission_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_submissions(db_path: Path | str, worksheet_id: int) -> list[dict[str, Any]]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT s.*, st.name AS student_name, st.no AS student_no, st.class_name AS student_class,
                   (SELECT COUNT(*) FROM answers a WHERE a.submission_id = s.id
                      AND a.verdict != 'correct') AS wrong_count,
                   (SELECT COUNT(*) FROM submission_pages p WHERE p.submission_id = s.id) AS page_count
            FROM submissions s LEFT JOIN students st ON st.id = s.student_id
            WHERE s.worksheet_id = ?
            ORDER BY s.id
            """,
            (worksheet_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def pending_submissions(db_path: Path | str) -> list[dict[str, Any]]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id FROM submissions WHERE status IN ('queued','processing','interrupted') "
            "ORDER BY id"
        ).fetchall()
        return [int(row["id"]) for row in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------


def upsert_answer(
    db_path: Path | str,
    submission_id: int,
    qno: str,
    *,
    student_raw: str = "",
    student_canonical: str = "",
    verdict: str = "uncertain",
    error_types: Iterable[str] | None = None,
    detail: str = "",
    score: float | None = None,
    max_score: float = 2,
    comment: str = "",
    confidence: float = 0,
    needs_review: bool = True,
) -> None:
    conn = connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO answers(submission_id, qno, student_raw, student_canonical, verdict,
                error_types, detail, score, max_score, comment, confidence, needs_review, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(submission_id, qno) DO UPDATE SET
                student_raw = excluded.student_raw,
                student_canonical = excluded.student_canonical,
                verdict = excluded.verdict,
                error_types = excluded.error_types,
                detail = excluded.detail,
                score = excluded.score,
                max_score = excluded.max_score,
                comment = excluded.comment,
                confidence = excluded.confidence,
                needs_review = excluded.needs_review,
                updated_at = excluded.updated_at
            """,
            (
                submission_id,
                str(qno),
                student_raw,
                student_canonical,
                verdict,
                json.dumps(list(error_types or []), ensure_ascii=False),
                detail,
                score,
                float(max_score),
                comment,
                float(confidence),
                1 if needs_review else 0,
                now_iso(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_answers(db_path: Path | str, submission_id: int) -> list[dict[str, Any]]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM answers WHERE submission_id = ? ORDER BY id", (submission_id,)
        ).fetchall()
        return [_decode_answer(row) for row in rows]
    finally:
        conn.close()


def get_answer(db_path: Path | str, submission_id: int, qno: str) -> dict[str, Any] | None:
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM answers WHERE submission_id = ? AND qno = ?", (submission_id, qno)
        ).fetchone()
        return _decode_answer(row) if row else None
    finally:
        conn.close()


def recalc_submission(db_path: Path | str, submission_id: int) -> dict[str, Any]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT score, max_score, needs_review, verdict FROM answers WHERE submission_id = ?",
            (submission_id,),
        ).fetchall()
        total = sum(float(row["score"]) for row in rows if row["score"] is not None)
        max_total = sum(float(row["max_score"]) for row in rows)
        needs_review = any(
            bool(row["needs_review"]) or row["verdict"] == "uncertain" or row["score"] is None
            for row in rows
        )
        status = "needs_review" if needs_review else "graded"
        conn.execute(
            "UPDATE submissions SET score = ?, max_score = ?, needs_review = ?, status = ?, "
            "updated_at = ? WHERE id = ?",
            (round(total, 2), round(max_total, 2), 1 if needs_review else 0, status, now_iso(), submission_id),
        )
        conn.commit()
        return {
            "score": round(total, 2),
            "max_score": round(max_total, 2),
            "needs_review": needs_review,
            "status": status,
        }
    finally:
        conn.close()


def confirm_submission(db_path: Path | str, submission_id: int) -> None:
    conn = connect(db_path)
    try:
        conn.execute(
            "UPDATE submissions SET status = 'confirmed', needs_review = 0, updated_at = ? "
            "WHERE id = ?",
            (now_iso(), submission_id),
        )
        conn.execute(
            "UPDATE answers SET needs_review = 0 WHERE submission_id = ?", (submission_id,)
        )
        conn.commit()
    finally:
        conn.close()


def list_answers_for_worksheet(db_path: Path | str, worksheet_id: int) -> list[dict[str, Any]]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT a.*, s.student_id, st.name AS student_name, st.no AS student_no,
                   st.class_name AS student_class, q.answer_eq, q.max_score AS question_max,
                   q.id AS question_id, q.question_type
            FROM answers a
            JOIN submissions s ON s.id = a.submission_id
            LEFT JOIN students st ON st.id = s.student_id
            LEFT JOIN questions q ON q.worksheet_id = s.worksheet_id AND q.qno = a.qno
            WHERE s.worksheet_id = ?
            ORDER BY COALESCE(st.no, ''), s.id, a.id
            """,
            (worksheet_id,),
        ).fetchall()
        result = []
        for row in rows:
            data = _decode_answer(row)
            result.append(data)
        return result
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


def add_event(
    db_path: Path | str, level: str, message: str, submission_id: int | None = None
) -> None:
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT INTO events(submission_id, level, message, created_at) VALUES (?, ?, ?, ?)",
            (submission_id, level, message, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def recent_events(db_path: Path | str, limit: int = 50) -> list[dict[str, Any]]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def worksheet_counts(db_path: Path | str) -> dict[str, int]:
    conn = connect(db_path)
    try:
        worksheets = conn.execute("SELECT COUNT(*) AS n FROM worksheets").fetchone()["n"]
        submissions = conn.execute("SELECT COUNT(*) AS n FROM submissions").fetchone()["n"]
        pending = conn.execute(
            "SELECT COUNT(*) AS n FROM submissions WHERE status IN ('queued','processing','needs_review')"
        ).fetchone()["n"]
        return {"worksheets": int(worksheets), "submissions": int(submissions), "pending": int(pending)}
    finally:
        conn.close()
