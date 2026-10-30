from __future__ import annotations

import io
import json
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from chemeq import db
from chemeq.config import load_config
from chemeq.core.demo import ensure_demo
from chemeq.core.grade import (
    confirm_submission,
    grade_from_transcription,
    update_answer,
    worksheet_summary,
)
from chemeq.core.report import build_report, export_html, export_xlsx
from chemeq.core.roster import import_roster, match_student
from chemeq.models import TranscribedEquation, TranscribedStudent, Transcription
from chemeq.web import routes as web_routes
from chemeq.web.app import create_app


def make_home(tmp_path: Path):
    return load_config(tmp_path / "home")


def test_demo_pipeline_and_reports(tmp_path: Path) -> None:
    cfg = make_home(tmp_path)
    worksheet_id = ensure_demo(cfg)
    data = worksheet_summary(cfg, worksheet_id)
    assert len(data["submissions"]) == 3
    assert data["summary"]["student_count"] == 3
    assert data["summary"]["max_score"] == 10

    report = build_report(cfg, worksheet_id)
    assert report["qnos"] == ["1", "2", "3", "4", "5"]
    assert report["student_rows"]
    assert report["wrong_rows"]

    xlsx = export_xlsx(cfg, worksheet_id, tmp_path / "report.xlsx")
    assert xlsx.exists() and xlsx.stat().st_size > 1000
    html = export_html(cfg, worksheet_id, tmp_path / "report.html")
    text = html.read_text(encoding="utf-8")
    assert "需订正名单" in text
    assert "题目统计" in text


def test_edit_and_confirm(tmp_path: Path) -> None:
    cfg = make_home(tmp_path)
    worksheet_id = ensure_demo(cfg)
    submissions = db.list_submissions(cfg.db_path, worksheet_id)
    target = next(s for s in submissions if s["student_name"] == "示例学生乙")
    answers = db.get_answers(cfg.db_path, target["id"])
    qno = answers[0]["qno"]
    result = update_answer(cfg, target["id"], qno, student_raw="2H2 + O2 --点燃--> 2H2O")
    assert result["ok"]
    changed = db.get_answer(cfg.db_path, target["id"], qno)
    assert changed["verdict"] == "correct"
    confirm_submission(cfg, target["id"])
    updated = db.get_submission(cfg.db_path, target["id"])
    assert updated["status"] == "confirmed"


def test_multi_page_transcription_grading(tmp_path: Path) -> None:
    cfg = make_home(tmp_path)
    db.init_db(cfg.db_path)
    worksheet_id = db.create_worksheet(
        cfg.db_path,
        "多页测试",
        "测试班",
        [
            {"qno": "1", "answer": "2H2 + O2 --点燃--> 2H2O", "max_score": 2},
            {"qno": "2", "answer": "Fe + CuSO4 → FeSO4 + Cu", "max_score": 2},
        ],
    )
    image = tmp_path / "page.jpg"
    Image.new("RGB", (100, 100), "white").save(image)
    submission_id, _ = db.create_submission(cfg.db_path, worksheet_id, str(image), "hash-1")
    db.add_page(cfg.db_path, submission_id, 2, str(image), "hash-2")
    pages = db.get_pages(cfg.db_path, submission_id)
    assert len(pages) == 2
    transcription = Transcription(
        student=TranscribedStudent(name="测试学生", no="01", confidence=0.9),
        equations=[
            TranscribedEquation(qno="1", raw="2H2 + O2 --点燃--> 2H2O", confidence=0.9),
            TranscribedEquation(qno="2", raw="Fe + CuSO4 → FeSO4 + Cu", confidence=0.9),
        ],
    )
    result = grade_from_transcription(cfg, submission_id, transcription)
    assert result["ok"]
    assert result["score"] == 4
    assert db.get_submission(cfg.db_path, submission_id)["page_count"] == 2


def test_roster_import_and_match(tmp_path: Path) -> None:
    cfg = make_home(tmp_path)
    db.init_db(cfg.db_path)
    roster = tmp_path / "roster.csv"
    roster.write_text("姓名,学号,班级\n张三,01,高二1班\n李四,02,高二1班\n", encoding="utf-8")
    result = import_roster(cfg.db_path, roster)
    assert result["imported"] == 2
    student, method, score = match_student(cfg.db_path, "张三", "01", "高二1班")
    assert student and method == "no" and score == 1.0
    fuzzy, fuzzy_method, fuzzy_score = match_student(cfg.db_path, "张山", "99", "高二1班")
    assert fuzzy is None or fuzzy_method == "fuzzy"


def test_web_routes_and_mobile_upload(tmp_path: Path) -> None:
    cfg = make_home(tmp_path)
    ensure_demo(cfg)
    app = create_app(cfg, start_queue=False)
    with TestClient(app) as client:
        for path in ["/", "/worksheets/1", "/submissions/1", "/settings", "/students"]:
            response = client.get(path)
            assert response.status_code == 200, path
        report = client.get("/worksheets/1/report")
        assert report.status_code == 200 and "学情报告" in report.text
        xlsx = client.get("/worksheets/1/export.xlsx")
        assert xlsx.status_code == 200
        mobile = client.get(f"/m/{cfg.mobile_token}")
        assert mobile.status_code == 200

        buffer = io.BytesIO()
        Image.new("RGB", (120, 120), "white").save(buffer, format="JPEG")
        response = client.post(
            f"/m/{cfg.mobile_token}/upload",
            data={"worksheet_id": "1"},
            files={"files": ("page.jpg", buffer.getvalue(), "image/jpeg")},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["ok"] and payload["submission_ids"]


def test_batch_upload_groups_by_page_count(tmp_path: Path) -> None:
    cfg = make_home(tmp_path)
    ensure_demo(cfg)
    app = create_app(cfg, start_queue=False)
    with TestClient(app) as client:
        files = []
        for index in range(4):
            buffer = io.BytesIO()
            Image.new("RGB", (120, 120), "white").save(buffer, format="JPEG")
            files.append(("files", (f"page-{index}.jpg", buffer.getvalue(), "image/jpeg")))
        response = client.post(
            f"/m/{cfg.mobile_token}/upload",
            data={"worksheet_id": "1", "mode": "batch", "pages_per_student": "2"},
            files=files,
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["mode"] == "batch"
        assert len(payload["submission_ids"]) == 2
        for submission_id in payload["submission_ids"]:
            assert len(db.get_pages(cfg.db_path, submission_id)) == 2


def test_settings_save_and_test(tmp_path: Path, monkeypatch) -> None:
    cfg = make_home(tmp_path)
    app = create_app(cfg, start_queue=False)
    monkeypatch.setattr(
        web_routes,
        "test_connection",
        lambda _cfg: {"ok": True, "latency_ms": 12},
    )
    with TestClient(app) as client:
        response = client.post(
            "/settings/test",
            data={
                "model": "deepseek-flash",
                "base_url": "https://api.deepseek.com",
                "api_key": "sk-test-only",
                "strict_scoring": "1",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert cfg.api_key == "sk-test-only"
        assert cfg.model == "deepseek-flash"
        assert cfg.strict_scoring is True


def test_old_config_limits_are_raised(tmp_path: Path) -> None:
    home = tmp_path / "old-home"
    home.mkdir()
    (home / "config.json").write_text(
        json.dumps({"max_batch": 30, "max_tokens": 2000}), encoding="utf-8"
    )
    cfg = load_config(home)
    assert cfg.max_batch >= 120
    assert cfg.max_tokens >= 3000
