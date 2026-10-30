"""HTTP routes for the local admin UI and the phone upload page."""

from __future__ import annotations

import io
import tempfile
import uuid
from hashlib import sha256
from pathlib import Path
from urllib.parse import quote

import qrcode
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)

from .. import db
from ..config import Config
from ..core.answer_key import extract_docx_candidates, parse_answer_key
from ..core.demo import ensure_demo
from ..core.grade import (
    confirm_submission,
    normalize_qno,
    regrade_from_stored,
    transcribe_submission,
    update_answer,
    worksheet_summary,
)
from ..core.report import export_html, export_xlsx
from ..core.roster import auto_register, import_roster
from ..models import Transcription
from ..net import lan_ip
from ..transcribe import ImageError, prepare_image, test_connection

router = APIRouter()


def _cfg(request: Request) -> Config:
    return request.app.state.cfg


def _templates(request: Request):
    return request.app.state.templates


def _render(request: Request, name: str, **context):
    context.setdefault("cfg", _cfg(request))
    context.setdefault("request", request)
    context.setdefault("msg", request.query_params.get("msg", ""))
    return _templates(request).TemplateResponse(request, name, context)


def _require_local(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="管理端只允许在本机访问")


def _redirect(url: str, msg: str = "") -> RedirectResponse:
    if msg:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}msg={quote(msg)}"
    return RedirectResponse(url, status_code=303)


def _worksheet_or_404(request: Request, worksheet_id: int) -> dict:
    worksheet = db.get_worksheet(_cfg(request).db_path, worksheet_id)
    if not worksheet:
        raise HTTPException(status_code=404, detail="作业不存在")
    return worksheet


def _mobile_url(request: Request, worksheet_id: int | None = None) -> str:
    cfg = _cfg(request)
    base = f"http://{lan_ip()}:{cfg.port}/m/{cfg.mobile_token}"
    if worksheet_id:
        base += f"?worksheet={worksheet_id}"
    return base


def _save_processed(cfg: Config, data: bytes) -> tuple[Path, str]:
    path = cfg.uploads_dir / f"{uuid.uuid4().hex}.jpg"
    path.write_bytes(data)
    return path, sha256(data).hexdigest()


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    _require_local(request)
    cfg = _cfg(request)
    worksheets = db.list_worksheets(cfg.db_path)
    counts = db.worksheet_counts(cfg.db_path)
    events = db.recent_events(cfg.db_path, limit=8)
    return _render(
        request,
        "dashboard.html",
        worksheets=worksheets,
        counts=counts,
        events=events,
        mobile_url=_mobile_url(request),
        lan=lan_ip(),
        has_key=bool(cfg.api_key),
    )


@router.post("/demo")
def make_demo(request: Request):
    _require_local(request)
    worksheet_id = ensure_demo(_cfg(request))
    return _redirect(f"/worksheets/{worksheet_id}", "示例数据已生成（合成数据，不是真实批改）")


@router.get("/worksheets/new", response_class=HTMLResponse)
def worksheet_new(request: Request):
    _require_local(request)
    return _render(request, "worksheet_new.html", answers_text="", warnings=[])


@router.post("/worksheets/new", response_class=HTMLResponse)
def worksheet_create(
    request: Request,
    title: str = Form(...),
    class_name: str = Form(""),
    answers: str = Form(...),
):
    _require_local(request)
    cfg = _cfg(request)
    items, warnings = parse_answer_key(answers)
    invalid = [item for item in items if not item.valid]
    if not items or invalid:
        for item in invalid:
            warnings.append(f"第 {item.qno} 题无法解析，请修正后再保存")
        return _render(
            request,
            "worksheet_new.html",
            answers_text=answers,
            warnings=warnings,
            title=title,
            class_name=class_name,
        )
    worksheet_id = db.create_worksheet(
        cfg.db_path,
        title,
        class_name,
        [item.as_question() for item in items],
    )
    return _redirect(
        f"/worksheets/{worksheet_id}",
        f"作业已创建：{len(items)} 道方程式题",
    )


@router.get("/worksheets/{worksheet_id}", response_class=HTMLResponse)
def worksheet_detail(request: Request, worksheet_id: int):
    _require_local(request)
    cfg = _cfg(request)
    worksheet = _worksheet_or_404(request, worksheet_id)
    questions = db.get_questions(cfg.db_path, worksheet_id)
    submissions = db.list_submissions(cfg.db_path, worksheet_id)
    try:
        summary = worksheet_summary(cfg, worksheet_id)
    except Exception:
        summary = {"summary": {"student_count": len(submissions), "average": 0, "max_score": 0,
                               "needs_review": 0, "pass_rate": 0, "per_question": [], "need_fix": [],
                               "top_errors": []}}
    return _render(
        request,
        "worksheet_detail.html",
        worksheet=worksheet,
        questions=questions,
        submissions=submissions,
        summary=summary["summary"],
        mobile_url=_mobile_url(request, worksheet_id),
    )


@router.get("/worksheets/{worksheet_id}/qr.png")
def worksheet_qr(request: Request, worksheet_id: int):
    _require_local(request)
    _worksheet_or_404(request, worksheet_id)
    image = qrcode.make(_mobile_url(request, worksheet_id))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return Response(buffer.getvalue(), media_type="image/png")


@router.get("/submissions/{submission_id}", response_class=HTMLResponse)
def submission_detail(request: Request, submission_id: int):
    _require_local(request)
    cfg = _cfg(request)
    submission = db.get_submission(cfg.db_path, submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="提交不存在")
    worksheet = _worksheet_or_404(request, int(submission["worksheet_id"]))
    questions = [
        q
        for q in db.get_questions(cfg.db_path, int(submission["worksheet_id"]))
        if q.get("question_type", "equation") in {"equation", "ionic", "thermochemical", "organic"}
    ]
    answers = {normalize_qno(a["qno"]): a for a in db.get_answers(cfg.db_path, submission_id)}
    rows = []
    for question in questions:
        qno = normalize_qno(question["qno"])
        answer = answers.get(qno, {})
        rows.append(
            {
                "qno": qno,
                "answer_eq": question["answer_eq"],
                "max_score": question["max_score"],
                "student_raw": answer.get("student_raw", ""),
                "verdict": answer.get("verdict", ""),
                "score": answer.get("score"),
                "error_types": answer.get("error_types", []),
                "detail": answer.get("detail", ""),
                "comment": answer.get("comment", ""),
                "confidence": answer.get("confidence", 0),
            }
        )
    pages = db.get_pages(cfg.db_path, submission_id)
    students = db.list_students(cfg.db_path)
    transcribed = []
    if submission.get("transcription_json"):
        try:
            transcribed = Transcription.model_validate_json(
                submission["transcription_json"]
            ).equations
        except Exception:
            transcribed = []
    return _render(
        request,
        "submission.html",
        submission=submission,
        worksheet=worksheet,
        rows=rows,
        pages=pages,
        students=students,
        transcribed=transcribed,
        back_url=f"/worksheets/{submission['worksheet_id']}",
    )


@router.get("/submissions/{submission_id}/pages/{page_no}")
def submission_page(request: Request, submission_id: int, page_no: int):
    _require_local(request)
    cfg = _cfg(request)
    pages = db.get_pages(cfg.db_path, submission_id)
    page = next((p for p in pages if int(p["page_no"]) == page_no), None)
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")
    path = Path(page["image_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="图片文件已丢失")
    return FileResponse(path, media_type="image/jpeg")


@router.post("/submissions/{submission_id}/answers/{qno}")
def answer_update(
    request: Request,
    submission_id: int,
    qno: str,
    student_raw: str = Form(""),
    score: str = Form(""),
    comment: str = Form(""),
):
    _require_local(request)
    cfg = _cfg(request)
    try:
        parsed_score = float(score) if score.strip() else None
    except ValueError:
        parsed_score = None
    try:
        update_answer(
            cfg,
            submission_id,
            qno,
            student_raw=student_raw,
            score=parsed_score,
            comment=comment,
        )
    except ValueError as exc:
        return _redirect(f"/submissions/{submission_id}", str(exc))
    return _redirect(f"/submissions/{submission_id}", f"第 {qno} 题已保存")


@router.post("/submissions/{submission_id}/confirm")
def submission_confirm(request: Request, submission_id: int):
    _require_local(request)
    confirm_submission(_cfg(request), submission_id)
    return _redirect(f"/submissions/{submission_id}", "已确认；如需修改可再次编辑")


@router.post("/submissions/{submission_id}/regrade")
def submission_regrade(request: Request, submission_id: int):
    _require_local(request)
    result = regrade_from_stored(_cfg(request), submission_id)
    msg = "已按保存的转写重新判定" if result.get("ok") else result.get("error", "重判失败")
    return _redirect(f"/submissions/{submission_id}", msg)


@router.post("/submissions/{submission_id}/retranscribe")
def submission_retranscribe(request: Request, submission_id: int):
    _require_local(request)
    cfg = _cfg(request)
    queue = request.app.state.queue
    if queue is not None:
        db.update_submission(cfg.db_path, submission_id, status="queued", error="")
        queue.submit(submission_id)
        return _redirect(f"/submissions/{submission_id}", "已重新提交识别；请稍后刷新")
    result = transcribe_submission(cfg, submission_id)
    return _redirect(
        f"/submissions/{submission_id}",
        "重新识别完成" if result.get("ok") else result.get("error", "识别失败"),
    )


@router.post("/submissions/{submission_id}/map")
def submission_map(
    request: Request,
    submission_id: int,
    source_qno: str = Form(...),
    target_qno: str = Form(...),
):
    _require_local(request)
    cfg = _cfg(request)
    submission = db.get_submission(cfg.db_path, submission_id)
    if not submission or not submission.get("transcription_json"):
        return _redirect(f"/submissions/{submission_id}", "没有可用的识别结果")
    try:
        transcription = Transcription.model_validate_json(submission["transcription_json"])
    except Exception:
        return _redirect(f"/submissions/{submission_id}", "识别结果无法读取")
    equation = next(
        (item for item in transcription.equations if normalize_qno(item.qno) == normalize_qno(source_qno)),
        None,
    )
    if equation is None:
        return _redirect(f"/submissions/{submission_id}", "找不到这条识别结果")
    try:
        update_answer(cfg, submission_id, target_qno, student_raw=equation.raw)
    except ValueError as exc:
        return _redirect(f"/submissions/{submission_id}", str(exc))
    return _redirect(
        f"/submissions/{submission_id}",
        f"已把识别结果填入第 {target_qno} 题，并重新判定",
    )


@router.post("/submissions/{submission_id}/student")
def submission_student(
    request: Request,
    submission_id: int,
    student_id: str = Form(""),
    name: str = Form(""),
    no: str = Form(""),
):
    _require_local(request)
    cfg = _cfg(request)
    submission = db.get_submission(cfg.db_path, submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="提交不存在")
    target: int | None = None
    if student_id.strip().isdigit():
        target = int(student_id)
    elif name.strip() or no.strip():
        target = auto_register(
            cfg.db_path,
            name.strip(),
            no.strip(),
            submission.get("student_class_raw", ""),
        )
    if target is None:
        return _redirect(f"/submissions/{submission_id}", "请选择学生或填写姓名/学号")
    db.update_submission(cfg.db_path, submission_id, student_id=target, needs_review=1)
    db.recalc_submission(cfg.db_path, submission_id)
    return _redirect(f"/submissions/{submission_id}", "学生已指定")


@router.get("/worksheets/{worksheet_id}/export.xlsx")
def worksheet_export(request: Request, worksheet_id: int):
    _require_local(request)
    cfg = _cfg(request)
    _worksheet_or_404(request, worksheet_id)
    path = export_xlsx(cfg, worksheet_id)
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=path.name,
    )


@router.get("/worksheets/{worksheet_id}/report", response_class=HTMLResponse)
def worksheet_report(request: Request, worksheet_id: int):
    _require_local(request)
    cfg = _cfg(request)
    _worksheet_or_404(request, worksheet_id)
    path = export_html(cfg, worksheet_id)
    return HTMLResponse(path.read_text(encoding="utf-8"))


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    _require_local(request)
    cfg = _cfg(request)
    return _render(
        request,
        "settings.html",
        public=cfg.public_dict(),
        mobile_url=_mobile_url(request),
        lan=lan_ip(),
    )


@router.post("/settings")
def settings_save(
    request: Request,
    model: str = Form(""),
    base_url: str = Form(""),
    api_key: str = Form(""),
    strict_scoring: str = Form(""),
):
    _require_local(request)
    cfg = _cfg(request)
    if model.strip():
        cfg.model = model.strip()
    if base_url.strip():
        cfg.base_url = base_url.strip().rstrip("/")
    if api_key.strip():
        cfg.api_key = api_key.strip()
    cfg.strict_scoring = bool(strict_scoring)
    cfg.save()
    return _redirect("/settings", "设置已保存（下一份批改生效）")


@router.post("/settings/test")
def settings_test(request: Request):
    _require_local(request)
    cfg = _cfg(request)
    result = test_connection(cfg)
    if result.get("ok"):
        return _redirect("/settings", f"连接成功（{result.get('latency_ms')} ms）")
    return _redirect("/settings", f"连接失败：{result.get('error')}")


@router.get("/students", response_class=HTMLResponse)
def students_page(request: Request):
    _require_local(request)
    cfg = _cfg(request)
    return _render(request, "students.html", students=db.list_students(cfg.db_path))


@router.post("/students/import")
async def students_import(request: Request, file: UploadFile = File(...)):
    _require_local(request)
    cfg = _cfg(request)
    suffix = Path(file.filename or "roster.csv").suffix.lower() or ".csv"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        handle.write(await file.read())
        temp_path = Path(handle.name)
    try:
        result = import_roster(cfg.db_path, temp_path)
    finally:
        temp_path.unlink(missing_ok=True)
    message = (
        f"名单导入完成：{result['imported']} 人，跳过 {result['skipped']} 行"
        if result.get("ok")
        else f"名单导入失败：{result.get('error')}"
    )
    return _redirect("/students", message)


@router.post("/api/answer-key/extract")
async def answer_key_extract(request: Request, file: UploadFile = File(...)):
    _require_local(request)
    suffix = Path(file.filename or "answer.docx").suffix.lower() or ".docx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        handle.write(await file.read())
        temp_path = Path(handle.name)
    try:
        candidates, warnings = extract_docx_candidates(temp_path)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    finally:
        temp_path.unlink(missing_ok=True)
    return JSONResponse(
        {"ok": True, "text": "\n".join(candidates), "warnings": warnings, "count": len(candidates)}
    )


@router.get("/api/health")
def health(request: Request):
    cfg = _cfg(request)
    counts = db.worksheet_counts(cfg.db_path)
    return {
        "ok": True,
        "version": "0.1.0",
        "model": cfg.model,
        "has_key": bool(cfg.api_key),
        "counts": counts,
    }


# ---------------------------------------------------------------------------
# Phone upload page
# ---------------------------------------------------------------------------


def _check_mobile_token(request: Request, token: str) -> Config:
    cfg = _cfg(request)
    if token != cfg.mobile_token:
        raise HTTPException(status_code=403, detail="二维码已失效，请在电脑上刷新二维码")
    return cfg


@router.get("/m/{token}", response_class=HTMLResponse)
def mobile_page(request: Request, token: str, worksheet: int | None = None):
    cfg = _check_mobile_token(request, token)
    worksheets = db.list_worksheets(cfg.db_path)
    selected = worksheet
    if selected is None and worksheets:
        selected = int(worksheets[0]["id"])
    return _render(
        request,
        "mobile.html",
        token=token,
        worksheets=worksheets,
        selected=selected,
        lan=lan_ip(),
    )


@router.get("/m/{token}/worksheets")
def mobile_worksheets(request: Request, token: str):
    cfg = _check_mobile_token(request, token)
    items = [
        {"id": worksheet["id"], "title": worksheet["title"], "class_name": worksheet["class_name"]}
        for worksheet in db.list_worksheets(cfg.db_path)
    ]
    return {"ok": True, "items": items}


@router.post("/m/{token}/upload")
async def mobile_upload(
    request: Request,
    token: str,
    worksheet_id: int = Form(...),
    same_student: bool = Form(False),
    files: list[UploadFile] = File(...),
):
    cfg = _check_mobile_token(request, token)
    worksheet = db.get_worksheet(cfg.db_path, worksheet_id)
    if not worksheet:
        return JSONResponse({"ok": False, "error": "作业不存在"}, status_code=404)
    if not files:
        return JSONResponse({"ok": False, "error": "没有收到照片"}, status_code=400)
    if len(files) > cfg.max_batch:
        return JSONResponse({"ok": False, "error": f"一次最多 {cfg.max_batch} 张"}, status_code=400)

    processed: list[bytes] = []
    for upload in files:
        raw = await upload.read()
        if len(raw) > cfg.max_upload_mb * 1024 * 1024:
            return JSONResponse(
                {"ok": False, "error": f"{upload.filename} 超过 {cfg.max_upload_mb}MB"},
                status_code=400,
            )
        try:
            processed.append(prepare_image(raw))
        except ImageError as exc:
            return JSONResponse(
                {"ok": False, "error": f"{upload.filename}：{exc}"}, status_code=400
            )
    if not processed:
        return JSONResponse({"ok": False, "error": "照片处理失败"}, status_code=400)

    queue = request.app.state.queue
    submission_ids: list[int] = []
    if same_student:
        hashes = [sha256(data).hexdigest() for data in processed]
        bundle = sha256("".join(hashes).encode("ascii")).hexdigest()
        first_path, _ = _save_processed(cfg, processed[0])
        submission_id, created = db.create_submission(
            cfg.db_path, worksheet_id, str(first_path), bundle
        )
        if created:
            for index, data in enumerate(processed[1:], start=2):
                page_path, page_hash = _save_processed(cfg, data)
                db.add_page(cfg.db_path, submission_id, index, str(page_path), page_hash)
            if queue is not None:
                queue.submit(submission_id)
        submission_ids.append(submission_id)
    else:
        for data in processed:
            page_path, page_hash = _save_processed(cfg, data)
            submission_id, created = db.create_submission(
                cfg.db_path, worksheet_id, str(page_path), page_hash
            )
            if created and queue is not None:
                queue.submit(submission_id)
            submission_ids.append(submission_id)
    return {
        "ok": True,
        "submission_ids": submission_ids,
        "created": len(submission_ids),
    }


@router.get("/m/{token}/status")
def mobile_status(request: Request, token: str, ids: str = ""):
    cfg = _check_mobile_token(request, token)
    items = []
    for raw in (ids or "").split(","):
        raw = raw.strip()
        if not raw.isdigit():
            continue
        submission = db.get_submission(cfg.db_path, int(raw))
        if not submission:
            continue
        items.append(
            {
                "id": submission["id"],
                "status": submission["status"],
                "score": submission.get("score"),
                "max_score": submission.get("max_score"),
                "needs_review": bool(submission.get("needs_review")),
                "student": submission.get("student_name") or submission.get("student_name_raw") or "",
                "error": submission.get("error", ""),
            }
        )
    return {"ok": True, "items": items}
