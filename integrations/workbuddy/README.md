# ChemEq × WorkBuddy 适配

WorkBuddy 5.3.14 与 CodeBuddy 同源，支持 MCP、Skills 和本地模型配置。ChemEq 的适配分三层，**推荐 L1/L2**。

## L1 技能（推荐，一句话批改）

安装后，WorkBuddy 里可以直接说：

> 帮我把 `D:\作业\周三` 里这摞方程式批了，登记错题，出报告。

技能会调用本机的 `chemeq grade`，返回：批改份数、平均分、错得最多的题、需订正名单、报告路径。

安装：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -ChemeqExe "D:\智批\chemeq.exe"
```

脚本会：

1. 复制技能到 `~/.workbuddy/skills/chemeq-grade/`；
2. 备份 `~/.workbuddy/mcp.json`，合并 `chemeq` MCP 条目；
3. 打印验收步骤。

完全退出并重新打开 WorkBuddy 后生效。

## L2 MCP（结构化工具）

`chemeq mcp` 是一个 stdio MCP server，工具：

- `list_worksheets`
- `create_worksheet`
- `grade_folder_tool`
- `get_submission`
- `regrade_submission`
- `worksheet_report`
- `list_students`
- `import_students`

适合让 Agent 自己决定“先查作业、再批文件夹、最后导出报告”。MCP 配置示例见 `mcp.example.json`。

## L3 让 WorkBuddy 生成前端（可选）

如果老师坚持“在 WorkBuddy 里做一个网页/小程序”，把 `build-kit/` 交给 WorkBuddy：里面是 API 说明 + 提示词 + 验收标准。**批改核心仍由 ChemEq 提供**，WorkBuddy 只生成薄前端。

注意：微信小程序需要已备案的 HTTPS 域名和公网服务器，无法直接访问老师电脑上的 `127.0.0.1`。本地部署场景建议直接用 ChemEq 自带的手机网页（扫码即用，免注册）。

## 卸载

```powershell
.\uninstall.ps1
```

或：

```powershell
.\install.ps1 -Uninstall
```

## 调试

```powershell
# 程序自检
chemeq doctor --net

# 直接看 MCP 是否能启动（会等待 stdin，Ctrl+C 退出）
chemeq mcp
```

如果 WorkBuddy 版本不认自定义 MCP，L1 技能仍然可用；把 `install.ps1` 的 `-McpArgs` 忽略即可，或在 WorkBuddy 的 MCP/连接器设置里手动添加 `chemeq mcp`。

## 数据与隐私

- 技能只把**文件路径**交给本机 ChemEq，不把图片内容喂给 WorkBuddy 的模型。
- 图片只在 ChemEq 内部按配置发给 DeepSeek/智谱；原图、成绩、名单都在老师电脑上。
- 不要在学生照片里保留不需要的姓名/学号暴露面；ChemEq 的复核页会显示识别结果，老师确认后才算最终成绩。
