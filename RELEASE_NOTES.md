# ChemEq Grader v0.1.0

本地部署的高中化学方程式拍照批改工具：手机扫码拍学生手写的方程式，AI 只负责“认字”，程序按化学规则检查配平、电荷、条件、↑↓、状态符号，按卷面姓名/学号把错题登记到学生名下，导出 Excel 和可打印的订正报告。

## 下载

- `chemeq-grader-0.1.0-windows-x64.zip`（约 45 MB）
- 同目录的 `.sha256` 是校验值

解压到普通文件夹（例如 `D:\智批`），双击 `启动智批.bat`。不要直接在压缩包里运行。

> Windows 可能提示“未知发布者”（未签名 exe）。点“更多信息 → 仍要运行”；源码可自行用 PyInstaller 构建。若被安全软件拦截，请添加信任或从源码构建。

## 5 分钟上手

1. 启动后打开 `http://127.0.0.1:8765`。
2. 右上角“设置”：模型 `deepseek-flash`，Base URL `https://api.deepseek.com`，填自己的 DeepSeek API Key，点“测试当前模型”。
3. “新建作业”，粘贴标准答案（每行一题）：`1. 2H2 + O2 --点燃--> 2H2O`。
4. 手机和电脑连同一个 Wi-Fi，扫二维码上传；多页学生勾选“同一学生的多页”。
5. 电脑上复核：改转写、改分、指定学生；确认后导出 Excel / 打印报告。

老师版说明：[docs/teacher-guide.md](https://github.com/lihaiyang616/chemeq-grader/blob/main/docs/teacher-guide.md)

## 这一版能做什么

- 化学方程式、离子方程式、热化学（ΔH）、常见有机 condensed 式
- 配平、电荷、条件、↑↓、状态符号、系数约简、箭头类型
- 严格评分（错一点就是 0 分），但报告写清错因
- 按姓名/学号匹配名单；匹配不上进“待确认”；可把识别结果手动填入任意题
- 改完转写后本地重判，不再调 API
- Excel 六表 + 可打印 HTML 学情报告 + 订正名单
- WorkBuddy 技能 / MCP（安装脚本见 `integrations/workbuddy/`）

## 已知限制

- 手写识别不完美；老师必须复核。真实手写样卷测试中，10/12 道题自动落到正确题号，2 道模型漏转写，需要老师补。
- 有机结构式/键线式、复杂络合物、一题多个方程式：会标“无法解析/待复核”，请拆题号。
- 微信小程序需要已备案 HTTPS 域名和公网服务器，不能直接访问老师电脑；本版用手机网页替代。
- WorkBuddy 的 MCP/技能安装器与 MCP 工具已在本地验证；本机未找到 WorkBuddy 桌面程序，UI 内的最终调用需在老师的 WorkBuddy 机器上验收。若自定义 MCP 不被识别，L1 技能仍可用。

## 成本与隐私

- 一页 5 题约 0.002 元，真实手写一页 12 题约 0.0036 元；40 页约 0.07–0.15 元（夜间价）。以账单为准。
- 程序、数据库、原图、成绩、名单都在老师电脑；识别时只把压缩后的作业图片发给所配置的模型服务。

## 反馈

请用仓库 Issues，附 `诊断.bat` 生成的 `诊断结果.txt`；不要贴真实学生姓名/照片/API Key。

完整文档：[README](https://github.com/lihaiyang616/chemeq-grader/blob/main/README.md) · [验收记录](https://github.com/lihaiyang616/chemeq-grader/blob/main/docs/validation.md) · [隐私](https://github.com/lihaiyang616/chemeq-grader/blob/main/docs/privacy.md)
