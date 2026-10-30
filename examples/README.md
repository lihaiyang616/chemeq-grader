# 合成示例数据

这里的图片、名单、答案都是**程序生成的合成数据**，不对应任何真实学生。

- `worksheet_jia.png` / `worksheet_yi.png` / `worksheet_bing.png`：三位“示例学生”的方程式练习，包含正确/错误写法。
- `answer_key.txt`：这份练习的标准答案，格式 `题号 | 方程式 | 分值`。
- `roster.csv`：示例名单。

用途：

```bash
uv run chemeq worksheet create --title "示例练习" --class-name "示例班级" --answers examples/answer_key.txt
uv run chemeq grade --folder examples --worksheet "示例练习"
```

`chemeq demo` 会直接在数据目录里生成另一套相同的合成数据，用于看界面/报告。
