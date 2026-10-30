from __future__ import annotations

import sys
from pathlib import Path

from docx import Document

M_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"

path = sys.argv[1]
out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
doc = Document(path)
lines: list[str] = []


def emit(value: str = "") -> None:
    lines.append(value)


emit("=== PARAGRAPHS ===")
for i, paragraph in enumerate(doc.paragraphs):
    text = paragraph.text.strip()
    if text:
        emit(f"[{i}] {paragraph.style.name}: {text}")

emit("=== TABLES ===")
for ti, table in enumerate(doc.tables):
    emit(f"--- table {ti}: rows={len(table.rows)} cols={len(table.columns)}")
    for row in table.rows:
        cells = [cell.text.strip().replace("\n", " / ") for cell in row.cells]
        emit(" | ".join(cells))

emit("=== OMML EQUATIONS ===")
for i, paragraph in enumerate(doc.paragraphs):
    maths = paragraph._p.findall(".//" + M_NS + "oMath")
    for math in maths:
        texts = math.findall(".//" + M_NS + "t")
        value = "".join(t.text or "" for t in texts)
        if value:
            emit(f"[{i}] {value}")

emit("=== INLINE SHAPES ===")
emit(str(len(doc.inline_shapes)))

text = "\n".join(lines)
if out_path:
    out_path.write_text(text, encoding="utf-8")
    print(f"wrote {out_path} ({len(text)} chars)")
else:
    sys.stdout.reconfigure(encoding="utf-8")
    print(text)
