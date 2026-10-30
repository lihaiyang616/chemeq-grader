"""Grading pipeline: pages -> VLM transcription -> deterministic answers -> DB."""

from __future__ import annotations

import hashlib
import re
import uuid
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .. import db
from ..config import Config
from ..models import TranscribedEquation, TranscribedStudent, Transcription
from ..transcribe import TranscriptionClient, prepare_image
from . import roster
from .compare import grade_equation
from .equation import Equation, try_parse

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp"}
GRADEABLE_TYPES = {"equation", "ionic", "thermochemical", "organic"}


def ensure_db(cfg: Config) -> None:
    db.init_db(cfg.db_path)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_qno(value: Any) -> str:
    text = str(value or "").strip()
    text = text.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    text = re.sub(r"^第\s*", "", text)
    text = re.sub(r"\s*题\s*$", "", text)
    text = text.replace("（", "(").replace("）", ")")
    text = text.strip(" .、:：")
    return text


def qno_variants(value: Any) -> set[str]:
    base = normalize_qno(value)
    variants = {base}
    if not base:
        return variants
    # (1) <-> 1, 1(1) <-> 1.1, 1-1
    if base.startswith("(") and base.endswith(")"):
        variants.add(base[1:-1])
    if base.endswith(")") and "(" in base:
        head, _, tail = base.partition("(")
        variants.add(head)
        variants.add(f"{head}.{tail.rstrip(')')}")
        variants.add(f"{head}-{tail.rstrip(')')}")
    variants.add(base.replace("(", "").replace(")", ""))
    return {v for v in variants if v}


def _copy_upload(cfg: Config, filename: str, data: bytes) -> Path:
    suffix = Path(filename).suffix.lower() or ".jpg"
    if suffix not in IMAGE_SUFFIXES:
        suffix = ".jpg"
    target = cfg.uploads_dir / f"{uuid.uuid4().hex}{suffix}"
    target.write_bytes(data)
    return target


def _combine_transcriptions(results: Iterable[Transcription]) -> Transcription:
    results = list(results)
    if not results:
        return Transcription()

    def first_value(attr: str) -> str:
        for item in results:
            value = getattr(item.student, attr)
            if value:
                return value
        return ""

    name = first_value("name")
    no = first_value("no")
    class_name = first_value("class_name")
    confidence = min(
        (item.student.confidence for item in results if item.student.name or item.student.no),
        default=0.8,
    )
    equations: list[TranscribedEquation] = []
    by_qno: dict[str, TranscribedEquation] = {}
    duplicates: list[str] = []
    for item in results:
        for equation in item.equations:
            qno = normalize_qno(equation.qno)
            if qno and qno in by_qno:
                duplicates.append(qno)
                if equation.confidence > by_qno[qno].confidence:
                    by_qno[qno] = equation
                continue
            if qno:
                by_qno[qno] = equation
            equations.append(equation)
    # Keep the page order for equations without a qno; keyed equations are in
    # insertion order as well.
    ordered = list(by_qno.values()) + [eq for eq in equations if not normalize_qno(eq.qno)]
    notes = "；".join(item.notes for item in results if item.notes)
    if duplicates:
        notes = (notes + "；" if notes else "") + f"跨页重复题号：{'、'.join(sorted(set(duplicates)))}"
    return Transcription(
        student=TranscribedStudent(
            name=name, no=no, class_name=class_name, confidence=confidence
        ),
        equations=ordered,
        notes=notes,
    )


def _resolve_student(
    cfg: Config, submission: dict[str, Any], transcription: Transcription
) -> tuple[int | None, str]:
    if submission.get("student_id"):
        return int(submission["student_id"]), "existing"
    student = transcription.student
    matched, method, _score = roster.match_student(
        cfg.db_path, student.name, student.no, student.class_name
    )
    if matched:
        db.update_submission(cfg.db_path, int(submission["id"]), student_id=int(matched["id"]))
        return int(matched["id"]), method
    if (student.name or student.no) and student.confidence >= 0.55:
        student_id = roster.auto_register(
            cfg.db_path, student.name, student.no, student.class_name
        )
        if student_id:
            db.update_submission(cfg.db_path, int(submission["id"]), student_id=student_id)
            return student_id, "auto"
    return None, "unmatched"


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _equation_similarity(student: Equation, key: Equation) -> float:
    """Content similarity used when printed question numbers do not line up."""

    if student.parse_error or key.parse_error:
        return 0.0
    if not student.left or not key.left:
        return 0.0
    left = _jaccard({sp.formula for sp in student.left}, {sp.formula for sp in key.left})
    right = _jaccard({sp.formula for sp in student.right}, {sp.formula for sp in key.right})
    return 0.65 * left + 0.35 * right


def _assign_answers(
    questions: list[dict[str, Any]], equations: list[TranscribedEquation]
) -> tuple[dict[int, TranscribedEquation], dict[str, int]]:
    """Map transcribed answers to answer-key questions.

    Pass 1 matches the printed question number exactly.  Pass 2 falls back to
    species overlap (a student's wrong product still usually shares reactants
    with the key).  Pass 3 is positional only when nothing matched and the
    counts line up.  The teacher can still re-map manually in the review page.
    """

    assigned: dict[int, TranscribedEquation] = {}
    used: set[int] = set()
    stats = {"exact": 0, "content": 0, "positional": 0, "unmatched": 0}

    # Exact printed question number: highest priority.
    for q_index, question in enumerate(questions):
        qno = normalize_qno(question["qno"])
        for eq_index, equation in enumerate(equations):
            if eq_index in used:
                continue
            if normalize_qno(equation.qno) == qno:
                assigned[q_index] = equation
                used.add(eq_index)
                stats["exact"] += 1
                break

    # Global greedy content matching.  Sorting by score (instead of walking
    # questions in order) prevents a weak early match from stealing an answer
    # that clearly belongs to a later question.
    pairs: list[tuple[float, int, int]] = []
    for q_index, question in enumerate(questions):
        if q_index in assigned:
            continue
        keys = [try_parse(question["answer_eq"])]
        keys.extend(try_parse(item) for item in question.get("alternatives", []))
        keys = [key for key in keys if not key.parse_error]
        if not keys:
            continue
        for eq_index, equation in enumerate(equations):
            if eq_index in used:
                continue
            student = try_parse(equation.raw)
            if student.parse_error:
                continue
            score = max(_equation_similarity(student, key) for key in keys)
            if score > 0:
                pairs.append((score, q_index, eq_index))
    pairs.sort(reverse=True)
    for score, q_index, eq_index in pairs:
        if q_index in assigned or eq_index in used:
            continue
        if score < 0.45:
            continue
        assigned[q_index] = equations[eq_index]
        used.add(eq_index)
        stats["content"] += 1

    if not assigned and len(equations) == len(questions):
        for q_index, equation in enumerate(equations):
            assigned[q_index] = equation
            stats["positional"] += 1

    stats["unmatched"] = len(questions) - len(assigned)
    return assigned, stats


def grade_from_transcription(
    cfg: Config,
    submission_id: int,
    transcription: Transcription,
    *,
    student_confidence: float | None = None,
) -> dict[str, Any]:
    ensure_db(cfg)
    submission = db.get_submission(cfg.db_path, submission_id)
    if not submission:
        raise ValueError(f"提交不存在：{submission_id}")
    questions = db.get_questions(cfg.db_path, int(submission["worksheet_id"]))
    gradeable = [q for q in questions if q.get("question_type", "equation") in GRADEABLE_TYPES]
    if not gradeable:
        raise ValueError("这份作业还没有可批改的方程式题，请先在作业设置里填标准答案")

    student_id, match_method = _resolve_student(cfg, submission, transcription)

    # Map answers by printed question number, then by chemical content, then
    # (only if nothing matched) by order.  The teacher can re-map manually.
    assignments, mapping_stats = _assign_answers(gradeable, transcription.equations)
    answers: list[dict[str, Any]] = []
    for index, question in enumerate(gradeable):
        qno = normalize_qno(question["qno"])
        equation = assignments.get(index)
        raw = equation.raw if equation else ""
        confidence = equation.confidence if equation else 0.0
        outcome = grade_equation(
            raw,
            [question["answer_eq"], *question.get("alternatives", [])],
            max_score=float(question["max_score"]),
            transcription_confidence=confidence,
            require_conditions=bool(question.get("require_conditions", True)),
            require_states=bool(question.get("require_states", True)),
            strict=cfg.strict_scoring,
        )
        db.upsert_answer(
            cfg.db_path,
            submission_id,
            qno,
            student_raw=raw,
            student_canonical=outcome.student_canonical,
            verdict=outcome.verdict,
            error_types=outcome.error_types,
            detail=outcome.detail,
            score=outcome.score,
            max_score=float(question["max_score"]),
            comment=outcome.detail if outcome.verdict == "wrong" else "",
            confidence=confidence,
            needs_review=outcome.needs_review,
        )
        answers.append(
            {
                "qno": qno,
                "raw": raw,
                "verdict": outcome.verdict,
                "score": outcome.score,
                "max_score": float(question["max_score"]),
                "error_types": outcome.error_types,
                "detail": outcome.detail,
                "confidence": confidence,
            }
        )

    extra = len(transcription.equations) - len(gradeable)
    if extra > 0:
        db.add_event(
            cfg.db_path,
            "warning",
            f"转写结果比答案库多 {extra} 道题，未匹配的作答请老师手动对应",
            submission_id,
        )
    db.add_event(
        cfg.db_path,
        "info",
        "题号匹配："
        f"精确 {mapping_stats['exact']}，内容 {mapping_stats['content']}，"
        f"顺序 {mapping_stats['positional']}，未匹配 {mapping_stats['unmatched']}",
        submission_id,
    )
    result = db.recalc_submission(cfg.db_path, submission_id)
    if student_id is None:
        db.update_submission(
            cfg.db_path,
            submission_id,
            needs_review=1,
            status="needs_review",
            error="学生姓名/学号未能匹配，请手动指定",
        )
    db.update_submission(
        cfg.db_path,
        submission_id,
        student_name_raw=transcription.student.name,
        student_no_raw=transcription.student.no,
        student_class_raw=transcription.student.class_name,
        transcription_json=transcription.model_dump_json(),
        needs_review=1
        if (student_id is None or result["needs_review"])
        else 0,
    )
    db.add_event(
        cfg.db_path,
        "info",
        f"批改完成：{len(answers)} 题，得分 {result['score']}/{result['max_score']}，"
        f"学生匹配={match_method}",
        submission_id,
    )
    return {
        "ok": True,
        "submission_id": submission_id,
        "student_id": student_id,
        "student_match": match_method,
        "student": transcription.student.model_dump(),
        "answers": answers,
        **result,
    }


def transcribe_submission(cfg: Config, submission_id: int) -> dict[str, Any]:
    ensure_db(cfg)
    submission = db.get_submission(cfg.db_path, submission_id)
    if not submission:
        raise ValueError(f"提交不存在：{submission_id}")
    pages = db.get_pages(cfg.db_path, submission_id)
    if not pages:
        raise ValueError("这份提交没有图片")
    if len(pages) > cfg.max_pages:
        raise ValueError(f"一份作业最多 {cfg.max_pages} 页")
    db.update_submission(cfg.db_path, submission_id, status="processing", error="")
    client = TranscriptionClient(cfg)
    results: list[Transcription] = []
    tokens_in = tokens_out = 0
    cost = 0.0
    model = cfg.model
    try:
        for page in pages:
            image = prepare_image(page["image_path"])
            result = client.transcribe(
                image, page_no=int(page["page_no"]), page_count=len(pages)
            )
            results.append(result.transcription)
            tokens_in += result.usage.prompt_tokens
            tokens_out += result.usage.completion_tokens
            cost += result.cost_cny
            model = result.model or model
            db.update_page_transcription(
                cfg.db_path, int(page["id"]), result.transcription.model_dump_json()
            )
        combined = _combine_transcriptions(results)
        db.update_submission(
            cfg.db_path,
            submission_id,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_cny=round(cost, 6),
            student_name_raw=combined.student.name,
            student_no_raw=combined.student.no,
            student_class_raw=combined.student.class_name,
            transcription_json=combined.model_dump_json(),
            status="processing",
            error="",
        )
        return grade_from_transcription(
            cfg,
            submission_id,
            combined,
            student_confidence=combined.student.confidence,
        )
    except Exception as exc:
        db.update_submission(
            cfg.db_path,
            submission_id,
            status="failed",
            error=str(exc),
            needs_review=1,
        )
        db.add_event(cfg.db_path, "error", f"批改失败：{exc}", submission_id)
        return {"ok": False, "submission_id": submission_id, "error": str(exc)}


def regrade_from_stored(cfg: Config, submission_id: int) -> dict[str, Any]:
    submission = db.get_submission(cfg.db_path, submission_id)
    if not submission or not submission.get("transcription_json"):
        return {"ok": False, "error": "没有已保存的转写结果，请先重新识别"}
    transcription = Transcription.model_validate_json(submission["transcription_json"])
    return grade_from_transcription(cfg, submission_id, transcription)


def update_answer(
    cfg: Config,
    submission_id: int,
    qno: str,
    *,
    student_raw: str | None = None,
    score: float | None = None,
    comment: str | None = None,
    verdict: str | None = None,
) -> dict[str, Any]:
    submission = db.get_submission(cfg.db_path, submission_id)
    if not submission:
        raise ValueError("提交不存在")
    questions = {normalize_qno(q["qno"]): q for q in db.get_questions(cfg.db_path, int(submission["worksheet_id"]))}
    question = questions.get(normalize_qno(qno))
    if not question:
        raise ValueError("题目不存在")
    current = db.get_answer(cfg.db_path, submission_id, qno)
    if not current:
        raise ValueError("这道题还没有批改结果")

    fields: dict[str, Any] = {
        "student_raw": current.get("student_raw", ""),
        "student_canonical": current.get("student_canonical", ""),
        "verdict": current.get("verdict", "uncertain"),
        "error_types": current.get("error_types", []),
        "detail": current.get("detail", ""),
        "score": current.get("score"),
        "max_score": current.get("max_score", question["max_score"]),
        "comment": current.get("comment", ""),
        "confidence": current.get("confidence", 0.0),
        "needs_review": False,
    }
    if student_raw is not None and student_raw != current.get("student_raw", ""):
        outcome = grade_equation(
            student_raw,
            [question["answer_eq"], *question.get("alternatives", [])],
            max_score=float(question["max_score"]),
            transcription_confidence=1.0,
            require_conditions=bool(question.get("require_conditions", True)),
            require_states=bool(question.get("require_states", True)),
            strict=cfg.strict_scoring,
        )
        fields.update(
            {
                "student_raw": student_raw,
                "student_canonical": outcome.student_canonical,
                "verdict": outcome.verdict,
                "error_types": outcome.error_types,
                "detail": outcome.detail,
                "score": outcome.score,
            }
        )
    if score is not None:
        fields["score"] = float(score)
    if verdict is not None:
        fields["verdict"] = verdict
    if comment is not None:
        fields["comment"] = comment
    db.upsert_answer(cfg.db_path, submission_id, qno, **fields)
    result = db.recalc_submission(cfg.db_path, submission_id)
    return {"ok": True, "submission_id": submission_id, "qno": qno, **result}


def confirm_submission(cfg: Config, submission_id: int) -> dict[str, Any]:
    db.confirm_submission(cfg.db_path, submission_id)
    return {"ok": True, "submission_id": submission_id}


def grade_folder(
    cfg: Config,
    folder: str | Path,
    worksheet_id: int,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    ensure_db(cfg)
    root = Path(folder)
    if not root.exists():
        raise ValueError(f"文件夹不存在：{root}")
    files = sorted(
        path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )
    if limit:
        files = files[: int(limit)]
    results = []
    for path in files:
        data = path.read_bytes()
        digest = sha256_bytes(data)
        stored = _copy_upload(cfg, path.name, data)
        submission_id, created = db.create_submission(
            cfg.db_path, worksheet_id, str(stored), digest
        )
        if not created:
            results.append({"file": str(path), "skipped": True, "submission_id": submission_id})
            continue
        results.append({"file": str(path), **transcribe_submission(cfg, submission_id)})
    return {"ok": True, "worksheet_id": worksheet_id, "count": len(results), "results": results}


def worksheet_summary(cfg: Config, worksheet_id: int) -> dict[str, Any]:
    worksheet = db.get_worksheet(cfg.db_path, worksheet_id)
    if not worksheet:
        raise ValueError("作业不存在")
    questions = [
        q
        for q in db.get_questions(cfg.db_path, worksheet_id)
        if q.get("question_type", "equation") in GRADEABLE_TYPES
    ]
    submissions = db.list_submissions(cfg.db_path, worksheet_id)
    answers = db.list_answers_for_worksheet(cfg.db_path, worksheet_id)

    scored = [float(s["score"]) for s in submissions if s.get("score") is not None]
    average = round(sum(scored) / len(scored), 2) if scored else 0.0
    total_max = sum(float(q["max_score"]) for q in questions)
    pass_count = sum(1 for value in scored if total_max and value / total_max >= 0.6)
    pass_rate = round(pass_count / len(scored) * 100, 1) if scored else 0.0

    per_question = []
    for question in questions:
        qno = normalize_qno(question["qno"])
        q_answers = [a for a in answers if normalize_qno(a["qno"]) == qno]
        wrong = [a for a in q_answers if a["verdict"] != "correct"]
        error_counter: Counter[str] = Counter()
        for answer in wrong:
            error_counter.update(answer.get("error_types", []))
        per_question.append(
            {
                "qno": qno,
                "answer": question["answer_eq"],
                "max_score": question["max_score"],
                "answered": len(q_answers),
                "wrong": len(wrong),
                "wrong_rate": round(len(wrong) / len(q_answers) * 100, 1) if q_answers else 0.0,
                "top_errors": error_counter.most_common(3),
            }
        )

    error_counter = Counter()
    for answer in answers:
        error_counter.update(answer.get("error_types", []))

    need_fix = []
    for submission in submissions:
        wrong_qnos = [
            normalize_qno(a["qno"])
            for a in answers
            if a["submission_id"] == submission["id"] and a["verdict"] != "correct"
        ]
        if wrong_qnos:
            need_fix.append(
                {
                    "submission_id": submission["id"],
                    "student": submission.get("student_name") or submission.get("student_name_raw") or "未识别",
                    "no": submission.get("student_no") or submission.get("student_no_raw") or "",
                    "score": submission.get("score"),
                    "wrong_qnos": wrong_qnos,
                }
            )

    return {
        "worksheet": worksheet,
        "questions": questions,
        "submissions": submissions,
        "answers": answers,
        "summary": {
            "student_count": len(submissions),
            "graded_count": len(scored),
            "average": average,
            "max_score": total_max,
            "pass_rate": pass_rate,
            "needs_review": sum(1 for s in submissions if s.get("needs_review")),
            "top_errors": error_counter.most_common(8),
            "per_question": per_question,
            "need_fix": need_fix,
        },
    }
