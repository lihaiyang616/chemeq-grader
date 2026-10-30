# 快速开始

## 一、老师用（Windows 免安装）

1. 下载 Release 的 `chemeq-grader-0.1.0-windows-x64.zip`，解压到普通文件夹（例如 `D:\智批`）。不要直接在压缩包里运行。
2. 双击 `启动智批.bat`。浏览器会自动打开 `http://127.0.0.1:8765`。
3. 点右上角“设置”：
   - 模型名：`deepseek-flash`
   - Base URL：`https://api.deepseek.com`
   - API Key：你的 DeepSeek Key
   - 点“测试当前模型”
4. 点“新建作业”，粘贴标准答案（每行一题），创建。
5. 手机和电脑连同一个 Wi-Fi，扫电脑上的二维码，拍照/选图上传。
6. 电脑上复核、改分、确认，然后导出 Excel / 打印报告。

遇到问题先双击 `诊断.bat`，把 `诊断结果.txt` 发给技术支持。

## 二、开发者用（源码）

```bash
git clone <repo>
cd chemeq-grader
uv sync
uv run chemeq demo
uv run chemeq serve --open
```

- 数据目录默认 `%LOCALAPPDATA%\ChemEq`；设置 `CHEMEQ_HOME` 可改。
- API Key 可以放 `CHEMEQ_API_KEY` 环境变量，或在设置页填写。
- 测试：`uv run pytest -q`；静态检查：`uv run ruff check src tests`。

## 三、从 Word 答案导入

“新建作业”页面支持上传 `.docx`，点“提取到上面”。Word 里的公式经常被压平成 `═══`、`CO32-`，导入器只提供**候选行**，必须逐条核对：

- 题号是否是卷面印刷题号；
- 条件是否丢失（如 `2NaHCO3 =△= …` 要写成 `--加热-->`）；
- 一题多式是否拆成 `6(1)`、`6(2)`。

提取不出来的行会提示警告；不要直接把整份 Word 当标准答案。

## 四、命令行批改

```bash
uv run chemeq grade --folder "D:/作业/周三" --worksheet 1 --json
uv run chemeq report --worksheet 1 --out 报告.xlsx
uv run chemeq report --worksheet 1 --html --out 报告.html
```

`--worksheet` 可以是 ID 或作业标题。文件夹里的 jpg/png/webp/heic 会按文件名排序，一张 = 一位学生；多页学生请用手机端的“同一学生的多页”。

## 五、更新

替换程序文件夹即可，数据在 `%LOCALAPPDATA%\ChemEq` 不动。更新前建议备份 `data` 目录。

## 六、卸载

删除程序文件夹；如需彻底删除学生数据，删除 `%LOCALAPPDATA%\ChemEq`（先确认已备份）。
