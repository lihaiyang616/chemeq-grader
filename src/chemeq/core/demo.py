"""Synthetic demo data.

Used by ``chemeq demo`` so the UI and reports can be exercised without an API
key.  Everything here is generated sample data; no real student information is
included.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .. import db
from ..config import Config
from ..models import TranscribedEquation, TranscribedStudent, Transcription
from .grade import grade_from_transcription

DEMO_TITLE = "示例：化学方程式小测（合成数据）"
QUESTIONS = [
    ("1", "2H2 + O2 --点燃--> 2H2O", 2),
    ("2", "2KClO3 --MnO2,Δ--> 2KCl + 3O2↑", 2),
    ("3", "Fe + CuSO4 → FeSO4 + Cu", 2),
    ("4", "NaOH + HCl → NaCl + H2O", 2),
    ("5", "CaCO3 --高温--> CaO + CO2↑", 2),
]
STUDENTS = [
    ("01", "示例学生甲", ["2H2 + O2 --点燃--> 2H2O", "2KClO3 --MnO2,Δ--> 2KCl + 3O2↑",
                          "Fe + CuSO4 → FeSO4 + Cu", "NaOH + HCl → NaCl + H2O",
                          "CaCO3 --高温--> CaO + CO2↑"]),
    ("02", "示例学生乙", ["2H2 + O2 → 2H2O", "2KClO3 --MnO2,Δ--> 2KCl + 3O2↑",
                          "Fe + CuSO4 → FeSO4 + Cu", "NaOH + HCl → NaCl + H2O2",
                          "CaCO3 --高温--> CaO + CO2"]),
    ("03", "示例学生丙", ["2H2 + O2 --点燃--> 2H2O", "2KClO3 → 2KCl + 3O2↑",
                          "Fe + CuSO4 → FeSO4 + Cu", "NaOH + HCl → NaCl + H2O",
                          "CaCO3 --高温--> CaO + CO2↑"]),
]


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_text(draw, xy, text: str, fill: str, font) -> None:
    """Draw text; on CI without CJK fonts fall back to ASCII instead of failing."""

    try:
        draw.text(xy, text, fill=fill, font=font)
    except UnicodeEncodeError:
        draw.text(xy, text.encode("ascii", "replace").decode("ascii"), fill=fill, font=font)


def generate_page(path: Path, name: str, no: str, lines: list[str]) -> None:
    image = Image.new("RGB", (1400, 1000), "white")
    draw = ImageDraw.Draw(image)
    header_font = _font(40)
    body_font = _font(34)
    title_font = _font(44)
    _draw_text(draw, (60, 50), "化学方程式小测（示例数据）", "black", title_font)
    _draw_text(draw, (60, 130), f"姓名：{name}      学号：{no}", "black", header_font)
    draw.line((60, 200, 1340, 200), fill="black", width=2)
    y = 250
    for index, line in enumerate(lines, 1):
        _draw_text(draw, (60, y), f"{index}. {line}", "black", body_font)
        y += 120
    image.save(path, format="JPEG", quality=88)


def _transcription(name: str, no: str, lines: list[str]) -> Transcription:
    return Transcription(
        student=TranscribedStudent(name=name, no=no, class_name="示例班级", confidence=0.95),
        equations=[
            TranscribedEquation(qno=str(index + 1), raw=line, confidence=0.95)
            for index, line in enumerate(lines)
        ],
        notes="合成演示数据，不代表真实批改结果",
    )


def ensure_demo(cfg: Config) -> int:
    db.init_db(cfg.db_path)
    for worksheet in db.list_worksheets(cfg.db_path):
        if worksheet["title"] == DEMO_TITLE:
            return int(worksheet["id"])
    questions = [
        {
            "qno": qno,
            "answer": answer,
            "max_score": score,
            "question_type": "equation",
        }
        for qno, answer, score in QUESTIONS
    ]
    worksheet_id = db.create_worksheet(
        cfg.db_path, DEMO_TITLE, "示例班级", questions, notes="合成演示数据"
    )
    for no, name, lines in STUDENTS:
        image_path = cfg.uploads_dir / f"demo-{uuid.uuid4().hex}.jpg"
        generate_page(image_path, name, no, lines)
        data = image_path.read_bytes()
        submission_id, created = db.create_submission(
            cfg.db_path,
            worksheet_id,
            str(image_path),
            hashlib.sha256(data).hexdigest(),
        )
        if not created:
            continue
        grade_from_transcription(cfg, submission_id, _transcription(name, no, lines))
    return worksheet_id
