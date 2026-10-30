# ChemEq Grader

Photograph a stack of high-school chemistry equation worksheets, transcribe the
handwriting with a vision model, and grade the equations with a deterministic
checker: element/charge balance, reaction conditions, gas/precipitate symbols,
state symbols, coefficients, thermochemical ΔH and common ionic equations.

- **AI only transcribes.** Wrong answers are preserved verbatim; the parser does
  the grading.
- **Teacher review is first-class.** Fix a misread equation and re-grade without
  another API call.
- **Local-first.** The app, SQLite database, images, scores and roster stay on
  the teacher's PC. Only compressed page images go to the configured model API.
- **WorkBuddy ready.** A skill and an MCP server let the teacher say “grade this
  folder” inside WorkBuddy.
- **Reports.** Excel (student summary, mistakes, question stats, mistake matrix,
  correction list, per-question detail) and a printable HTML report.

## Quick start (source)

```bash
uv sync
uv run chemeq demo
uv run chemeq serve --open
uv run pytest -q
```

Windows portable release: see the Releases page. Teacher guide (Chinese):
`docs/teacher-guide.md`.

## Status

v0.1.0. Handwriting recognition is imperfect by nature; the teacher must review.
Organic structural formulae, one-question-multiple-equations and WeChat
mini-programs are out of scope. See `docs/validation.md` for the measured
results and known gaps.

## License

MIT.
