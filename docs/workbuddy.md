# WorkBuddy 适配（摘要）

完整说明见 [`integrations/workbuddy/README.md`](../integrations/workbuddy/README.md)。

## 推荐用法

1. 安装 ChemEq（Windows zip）。
2. 运行：

```powershell
powershell -ExecutionPolicy Bypass -File integrations\workbuddy\install.ps1 -ChemeqExe "D:\智批\chemeq.exe"
```

3. 完全退出并重开 WorkBuddy。
4. 在 WorkBuddy 里说：

> 帮我把 `D:\作业\周三` 里这摞方程式批了，登记错题，出报告。

## 三层

- **L1 技能**：`~/.workbuddy/skills/chemeq-grade/`，调用本机 `chemeq grade`。最稳。
- **L2 MCP**：`chemeq mcp`，工具化（列作业/批文件夹/取结果/导报告）。
- **L3 build-kit**：让 WorkBuddy 生成薄前端；批改仍由 ChemEq 做。微信小程序需要公网 HTTPS+备案域名，本地场景不推荐。

## 验收

- MCP server 工具列表与 `list_worksheets` 调用已在本地验证。
- 安装器支持 `-DryRun` / `-Uninstall`，会备份 `mcp.json`。
- WorkBuddy 版本差异：若自定义 MCP 不被识别，L1 技能仍可用。
