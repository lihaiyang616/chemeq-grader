"""Generate the synthetic examples committed under examples/.

Run from the repository root:

    uv run python scripts/make_examples.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from chemeq.core.demo import QUESTIONS, STUDENTS, generate_page

OUT = Path("examples")
OUT.mkdir(exist_ok=True)

names = {"01": "worksheet_jia.png", "02": "worksheet_yi.png", "03": "worksheet_bing.png"}
for no, name, lines in STUDENTS:
    path = OUT / names[no]
    generate_page(path, name, no, lines)
    print(path)

answer_lines = []
for qno, answer, score in QUESTIONS:
    answer_lines.append(f"{qno} | {answer} | {score:g}")
(OUT / "answer_key.txt").write_text("\n".join(answer_lines) + "\n", encoding="utf-8")
print(OUT / "answer_key.txt")

roster_lines = ["学号,姓名,班级"] + [
    f"{no},{name},示例班级" for no, name, _ in STUDENTS
]
(OUT / "roster.csv").write_text("\n".join(roster_lines) + "\n", encoding="utf-8")
print(OUT / "roster.csv")

sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None
