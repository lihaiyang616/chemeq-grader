# 贡献指南

## 开发环境

```bash
uv sync
uv run chemeq demo
uv run chemeq serve --open
uv run pytest -q
uv run ruff check src tests
```

## 目录

```
src/chemeq/core/equation.py   化学式/方程式解析、配平、电荷
src/chemeq/core/compare.py    学生答案 vs 标准答案、错因、严格评分
src/chemeq/core/grade.py      多页转写、题号/内容匹配、入库
src/chemeq/core/report.py     Excel / HTML 报告
src/chemeq/web/               本机管理端 + 手机上传页
src/chemeq/mcp_server.py      WorkBuddy MCP 工具
```

## 改解析器时

- 在 `tests/test_equation.py` 加正向用例（必须能配平）和错误变体。
- 不要为了“让某道题过”而放宽到接受错误写法；宁可标 `无法解析` 进复核。
- 新增离子/条件/状态写法时，同时加 `test_compare.py` 的判定用例。
- 热化学方程式的系数影响 ΔH，不能简单约分。

## 改提示词时

- 系统提示词的核心是“只转写、不纠正、不补全”；不要让它顺手判分。
- 用合成样卷 + 真实脱敏样卷各跑一次，确认学生的错误没有被“改对”。
- 提示词变更要在 PR 描述里贴出 token 用量与费用变化。

## PR

- 一个 PR 做一件事；附测试命令和结果。
- 不要提交：真实学生照片、姓名/学号、老师的微信截图、API Key、`local/`。
- UI 改动附截图（合成数据）；移动端说明真机/模拟器。
- 报告字段变更要更新 `docs/grading-rules.md` 和 `docs/validation.md`。

## 数据/隐私

- 测试用 `examples/` 的合成数据，或自己生成。
- 不要把真实作业上传到任何在线服务做测试。

## 许可

贡献即同意以 MIT 许可发布。
