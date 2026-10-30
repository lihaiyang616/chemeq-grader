from __future__ import annotations

from pathlib import Path

from docx import Document

from chemeq.core.answer_key import (
    extract_docx_candidates,
    parse_answer_key,
)


def test_parse_answer_key_formats() -> None:
    text = """
    1. 2H2 + O2 --点燃--> 2H2O
    2 | 2KClO3 --MnO2,Δ--> 2KCl + 3O2↑ | 3
    (3) H2(g) + 1/2O2(g) → H2O(l) ΔH = -285.8 kJ/mol | 2
    4. NaOH + HCl → NaCl + H2O；H+ + OH- → H2O | 2
    """
    items, warnings = parse_answer_key(text)
    assert not warnings, warnings
    assert [item.qno for item in items] == ["1", "2", "3", "4"]
    assert items[0].question_type == "equation"
    assert items[1].max_score == 3
    assert items[2].question_type == "thermochemical"
    assert items[3].alternatives == ["H+ + OH- → H2O"]


def test_invalid_answer_is_flagged() -> None:
    items, warnings = parse_answer_key("5 | 这不是方程式 | 2")
    assert len(items) == 1
    assert items[0].question_type == "invalid"
    assert warnings


def test_extract_docx_candidates(tmp_path: Path) -> None:
    doc = Document()
    doc.add_paragraph("1、钠与氧气的反应：")
    doc.add_paragraph("4Na＋O2═══2Na2O")
    doc.add_paragraph("加热：2Na＋O2Na2O2")
    path = tmp_path / "answer.docx"
    doc.save(path)
    candidates, warnings = extract_docx_candidates(path)
    assert any("4Na" in line for line in candidates)
    # A flattened equation without an arrow is intentionally skipped, not
    # silently accepted.
    assert all("2Na2O2" not in line for line in candidates)
