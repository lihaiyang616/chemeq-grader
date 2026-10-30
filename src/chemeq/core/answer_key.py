"""Answer-key parsing and docx pre-extraction.

Teachers usually have the answers in a Word document.  Those documents are
written for humans, not machines: equations are mixed with prose, arrows are
rendered as ``═══``, and superscript charges are flattened (``CO32-``).  The
importer therefore extracts *candidates* and asks the teacher to confirm them;
it never silently treats a prose line as a question.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .equation import ParseError, normalize_text, try_parse


@dataclass
class AnswerKeyItem:
    qno: str
    answer: str
    alternatives: list[str] = field(default_factory=list)
    max_score: float = 2.0
    question_type: str = "equation"  # equation | ionic | thermochemical | other | invalid
    prompt_text: str = ""
    require_conditions: bool = True
    require_states: bool = True
    warnings: list[str] = field(default_factory=list)
    source: str = ""

    @property
    def valid(self) -> bool:
        return self.question_type != "invalid"

    def as_question(self) -> dict[str, Any]:
        return {
            "qno": self.qno,
            "answer": self.answer,
            "alternatives": self.alternatives,
            "max_score": self.max_score,
            "require_conditions": self.require_conditions,
            "require_states": self.require_states,
            "question_type": self.question_type,
            "prompt_text": self.prompt_text,
        }


_QNO_PATTERNS = [
    re.compile(r"^\s*(\d+)\s*[（(]\s*(\d+)\s*[）)]\s*[.、：:]?\s*(.+)$"),
    re.compile(r"^\s*[（(]\s*(\d+)\s*[）)]\s*[.、：:]?\s*(.+)$"),
    re.compile(r"^\s*第?\s*(\d+)\s*[.、：:）)]\s*(.+)$"),
    re.compile(r"^\s*(\d+)\s*[|｜]\s*(.+)$"),
]
_SCORE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*分?\s*$")
_HEADING_RE = re.compile(
    r"^\s*(?:第?\s*(\d+)\s*[、.．)]|[（(]\s*(\d+)\s*[）)]|([①②③④⑤⑥⑦⑧⑨⑩])|([a-zA-Z])\s*[、.])"
)


def _split_fields(line: str) -> list[str]:
    return [part.strip() for part in re.split(r"[|｜]", line)]


def _detect_qno(text: str) -> tuple[str | None, str]:
    for pattern in _QNO_PATTERNS:
        match = pattern.match(text)
        if match:
            if match.re.groups == 3:  # 1(1) form
                return f"{match.group(1)}({match.group(2)})", match.group(3).strip()
            return match.group(1), match.group(2).strip()
    return None, text.strip()


def classify_answer(answer: str) -> tuple[str, list[str]]:
    eq = try_parse(answer)
    if eq.parse_error:
        return "invalid", [f"无法解析：{eq.parse_error}"]
    if eq.is_thermochemical:
        return "thermochemical", []
    if eq.is_ionic:
        return "ionic", []
    return "equation", []


def parse_answer_key(text: str, default_score: float = 2.0) -> tuple[list[AnswerKeyItem], list[str]]:
    """Parse a simple teacher-facing text format.

    Accepted forms::

        1. 2H2 + O2 --点燃--> 2H2O
        1 | 2H2 + O2 --点燃--> 2H2O | 2
        (3) 2Na + 2H2O → 2NaOH + H2↑ | 2
        2Na2O2 + 2H2O → 4NaOH + O2↑

    With no question number the line is numbered sequentially.  Use ``；``
    between accepted alternatives of the same question.
    """

    items: list[AnswerKeyItem] = []
    warnings: list[str] = []
    pending_qno: str | None = None

    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Headings such as "7、Na2CO3 与 NaHCO3 的反应" set the current number but
        # are not answers themselves.
        heading = _HEADING_RE.match(line)
        if (
            heading
            and "=" not in line
            and "→" not in line
            and "⇌" not in line
            and "-->" not in line
            and "->" not in line
        ):
            pending_qno = next(group for group in heading.groups() if group)
            continue

        fields = _split_fields(line)
        qno: str | None = None
        answer = ""
        score = default_score
        alternatives: list[str] = []
        if len(fields) >= 2:
            if re.fullmatch(r"\d+", fields[0]):
                qno = fields[0]
                answer = fields[1]
                remaining = fields[2:]
            else:
                first_qno, first_rest = _detect_qno(fields[0])
                if first_qno and not first_rest:
                    qno = first_qno
                    answer = fields[1]
                    remaining = fields[2:]
                else:
                    qno, answer = _detect_qno(fields[0])
                    remaining = fields[1:]
            for part in remaining:
                if _SCORE_RE.match(part):
                    score = float(_SCORE_RE.match(part).group(1))  # type: ignore[union-attr]
                elif part:
                    alternatives.append(part)
        else:
            qno, answer = _detect_qno(line)

        if not answer:
            continue
        if not qno:
            qno = pending_qno or str(len(items) + 1)
        if "；" in answer or ";" in answer:
            parts = [p.strip() for p in re.split(r"[；;]", answer) if p.strip()]
            answer = parts[0] if parts else answer
            alternatives.extend(parts[1:])

        qtype, item_warnings = classify_answer(answer)
        if qtype == "invalid":
            warnings.append(f"第 {qno} 题：{item_warnings[0]}")
        item = AnswerKeyItem(
            qno=qno,
            answer=answer,
            alternatives=alternatives,
            max_score=score,
            question_type=qtype,
            warnings=item_warnings,
            source=raw_line,
        )
        items.append(item)

    # Duplicate qno: keep the first, warn about the rest.
    seen: set[str] = set()
    unique: list[AnswerKeyItem] = []
    for item in items:
        if item.qno in seen:
            warnings.append(f"题号 {item.qno} 重复，已保留第一条")
            continue
        seen.add(item.qno)
        unique.append(item)
    return unique, warnings


def extract_docx_candidates(path: str | Path) -> tuple[list[str], list[str]]:
    """Extract equation-looking candidate lines from a Word document.

    This is a *pre-fill* helper for the answer-key editor; the teacher still
    confirms every line.  It intentionally returns source text rather than
    silently building a worksheet.
    """

    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover - optional in some installs
        raise RuntimeError("导入 docx 需要 python-docx，请先安装依赖") from exc

    doc = Document(str(path))
    candidates: list[str] = []
    warnings: list[str] = []
    current_qno = ""
    for paragraph in doc.paragraphs:
        text = (paragraph.text or "").strip()
        if not text:
            continue
        heading = _HEADING_RE.match(text)
        if (
            heading
            and "=" not in text
            and "→" not in text
            and "⇌" not in text
            and "-->" not in text
            and "->" not in text
        ):
            current_qno = next(group for group in heading.groups() if group)
            continue
        # Split prose into clauses; equations usually live in one clause.
        for clause in re.split(r"[。；;，,]", text):
            clause = clause.strip()
            if not clause:
                continue
            if not any(token in clause for token in ("=", "→", "⇌", "═")):
                continue
            normalized = normalize_text(clause)
            # Drop a prose prefix up to the first plausible equation token.
            match = re.search(r"(?:\d+\s*)?(?:[A-Z(]|2H|Na|Ca|Fe|Cu|Al|Mg|Zn|Ag|Ba)", normalized)
            if match and match.start() > 0:
                normalized = normalized[match.start() :]
            eq = try_parse(normalized)
            if eq.parse_error:
                warnings.append(f"候选行无法解析：{clause[:80]}")
                continue
            qno = current_qno or str(len(candidates) + 1)
            candidates.append(f"{qno} | {normalized}")
    return candidates, warnings


def answer_key_to_text(items: list[AnswerKeyItem]) -> str:
    lines = []
    for item in items:
        parts = [item.qno, item.answer, f"{item.max_score:g}"]
        parts.extend(item.alternatives)
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def parse_equation_or_raise(text: str) -> None:
    """Helper used by tests/UI validation."""

    eq = try_parse(text)
    if eq.parse_error:
        raise ParseError(eq.parse_error)
