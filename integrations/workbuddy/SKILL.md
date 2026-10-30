---
name: chemeq-grade
display_name: 化学方程式批改
description: 批改学生化学方程式作业照片，按姓名/学号登记错题并生成 Excel/学情报告；当用户说“批改作业 / 批方程式 / 登记错题 / 出错题报告”时使用。
description_zh: 化学方程式拍照批改、错题登记与学情报告
description_en: Grade photographed chemistry equations, log mistakes and export reports
category: Education
version: 1.0.0
allowed-tools: Bash,Read
---

# ChemEq 化学方程式批改

## 什么时候用

老师/用户说：

- “帮我把 `D:\作业\周三` 里这摞方程式批了”
- “登记一下这次小测的错题”
- “出一份错题报告 / 订正名单”
- “看看这个班哪几道方程式错得最多”

## 前置

- 本机已安装 ChemEq（`{{CHEMEQ_EXE}}` 存在）。
- 如果还没有作业：先用 `worksheet list` 看；没有就让用户提供“作业名 + 标准答案（每行一题）”，再 `worksheet create`。
- 如果需要老师复核/看原图：提示用户双击 `启动智批.bat`，或运行 `"{{CHEMEQ_EXE}}" serve --open`。

## 执行步骤

1. 列出作业：

```bash
"{{CHEMEQ_EXE}}" worksheet list
```

2. 确认作业 ID（或标题）和照片文件夹。批改：

```bash
"{{CHEMEQ_EXE}}" grade --folder "<作业照片文件夹>" --worksheet "<作业ID或标题>" --json
```

3. 读取 JSON 结果，向用户汇报：

- 批改了几份、成功几份、失败几份；
- 平均分 / 满分；
- 错得最多的 3 道题（从返回的 `answers` 或报告摘要里找）；
- 需要订正的学生名单；
- 如果有失败项，原样报告错误，不要编造分数。

4. 需要文件时导出：

```bash
"{{CHEMEQ_EXE}}" report --worksheet "<作业ID>" --out "<输出.xlsx>"
"{{CHEMEQ_EXE}}" report --worksheet "<作业ID>" --html --out "<输出.html>"
```

## 规则（必须遵守）

- **只转写、不批改**：ChemEq 内部用视觉模型只认字，配平/电荷/条件/状态由程序判定；不要自己心算分数。
- **不要臆造**：命令失败、API Key 缺失、图片读不出时，直接告诉用户原因；不要给“看起来合理”的分数。
- **不要修改学生原图**；不要删除作业数据。
- **学生匹配不上时**：报告里会显示“未识别/待复核”，提醒老师在电脑上点一下指定，不要把错题记到别人名下。
- **隐私**：照片只通过本机 ChemEq 处理；不要把它上传到 WorkBuddy 自己的模型或其它云服务。
- 默认严格评分：只要有一点错就是 0 分；报告里仍会写清错因。

## 失败处理

- `找不到作业`：先 `worksheet list`，或让用户提供标准答案新建。
- `还没有填写 API Key`：让用户打开 `http://127.0.0.1:8765/settings` 填写并测试。
- `文件夹不存在/没有图片`：确认路径；支持 jpg/png/webp/heic。
- `无法解析`：把该题原样告诉用户，让老师在复核页改转写后点“重新判定”。
