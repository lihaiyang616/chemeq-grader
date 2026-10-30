# 验收记录

> 记录实际做过的测试与限制，不把“跑通一次”写成“已验收”。日期：2026-10-30。

## 环境

- Windows 11，Python 3.12.9，uv 0.13.5
- 模型：DeepSeek `deepseek-flash`（OpenAI 兼容 Chat Completions，`thinking` disabled）
- 测试 Key：仅本地联调，不写入仓库

## 自动化测试

- `uv run pytest -q`：全部通过（解析器 30+ 方程式、错误变体、热化学、多页、报告、Web 路由、MCP 工具列表）。
- `uv run ruff check src tests`：见 CI；提交前清零。

## 真实模型转写

### 合成 5 题一页

- 图片：1200×1600 合成“化学方程式练习”，含故意写错的 `H2O2` 和漏掉的 `↑`。
- 结果：姓名/学号正确；5 道题原样转写；**错误没有被纠正**。
- 用量：1,110 输入 + 129 输出 tokens；off-peak 约 ¥0.0018/页。

### 真实手写一页（脱敏，未入库）

- 图片：老师提供的学生样卷第 2 页；仅本地使用，未提交到仓库，也不包含姓名/学号。
- 转写：10 条方程式；题号使用了卷面印刷题号（`7(1)b`、`9(1)` 等），并保留了学生的错误产物。
- 自动匹配：按题号 + 化学内容匹配，10 条正确落到对应题；**2 道题的作答模型没转写出来**，复核页留空。
- 判定：20/24；两题未匹配需老师补。说明“AI 转写 + 程序判分”的边界：转写漏题时，老师必须补，不能假装满分。
- 用量：1,301 输入 + 500 输出 tokens；约 ¥0.0036/页。

## 打包

- `uv run pyinstaller packaging/chemeq.spec` 构建成功，`dist/chemeq` 约 99MB。
- 在中文+空格路径下运行 `chemeq.exe doctor` / `demo` 正常。
- 截图：`docs/images/`（合成示例数据）。

## WorkBuddy

- MCP server 工具列表与 `list_worksheets` 调用已在本地验证（mcp 2.x `MCPServer`）。
- 安装器已在模拟的 `~/.workbuddy` 上实际执行：技能复制、`mcp.json` 合并/备份/卸载、UTF-8 无 BOM 写入均正常。
- **阻塞项**：本机只剩 `~/.workbuddy` 配置目录，未找到 WorkBuddy 桌面程序（`Programs\WorkBuddy` 为空，进程/开始菜单/AppData 均无 exe），因此无法在本机做 WorkBuddy 5.3.14 UI 内的真实技能/MCP 调用。需要在老师的 WorkBuddy 机器上做最终 UI 验收；若版本不认自定义 MCP，L1 技能仍可用。

## 未验证/限制

- 真实手写的准确率随字迹差异很大；本记录只代表两张样本。
- 有机结构式、复杂络合物、一题多式未覆盖。
- 未在老师的真实电脑/手机上验收；需要她本机再跑一遍。
- 成本为按官方价估算，未与账单逐项核对。

## 复现

```bash
uv sync
uv run chemeq demo
uv run pytest -q
uv run chemeq doctor --net
```

真实模型测试需要 `CHEMEQ_API_KEY`（不要提交到仓库）。
