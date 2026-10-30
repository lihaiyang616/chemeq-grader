# 让 WorkBuddy 生成 ChemEq 的薄前端（可选）

> 目标：让 WorkBuddy 生成一个“手机拍照上传 + 报告查看”的页面，**批改仍由本机 ChemEq 完成**。
> 不要让它重新实现化学配平；那部分交给确定性解析器。

## 给 WorkBuddy 的提示词

```text
你是资深前端工程师。请为 ChemEq（本地化学方程式批改服务）生成一个手机优先的网页前端。

要求：
1. 页面一：手机上传页。URL 形如 http://<电脑IP>:8765/m/<手机令牌>。
   - 下拉选择作业（调用 GET /m/<token>/worksheets）。
   - 多选照片，调用 POST /m/<token>/upload，multipart 字段：worksheet_id、files[]、same_student（可选）。
   - 上传后轮询 GET /m/<token>/status?ids=1,2。
   - 显示每份：排队/识别中/已批改/待复核/失败；不要在前端算分。
2. 页面二：老师报告页。调用 GET /worksheets/<id>/report（HTML）和 GET /worksheets/<id>/export.xlsx。
3. 技术栈：单文件 HTML + 原生 JS（可以用 fetch / FormData），不引入构建工具，不依赖 CDN。
4. 视觉：中文、字号大、按钮大、适合手机；颜色用墨绿/白，打印友好。
5. 不要实现：OCR、配平、评分、学生匹配；这些都在后端。
6. 验收：手机浏览器可拍照上传；上传后能看到状态；错误有中文提示；不把图片发到第三方。

接口细节见同目录 openapi.yaml。
```

## 本地接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/m/{token}` | 手机上传页（ChemEq 自带） |
| GET | `/m/{token}/worksheets` | 手机端作业列表（JSON） |
| POST | `/m/{token}/upload` | multipart：`worksheet_id`、`files`、`same_student` |
| GET | `/m/{token}/status?ids=1,2` | 批改状态 |
| GET | `/worksheets/{id}/report` | HTML 学情报告 |
| GET | `/worksheets/{id}/export.xlsx` | Excel 报告 |
| GET | `/api/health` | 健康检查 |

## 验收标准

- [ ] 手机（iPhone/Android）能选图/拍照并上传。
- [ ] 上传后 3 秒内出现状态行；批改完成后显示分数/待复核。
- [ ] 网络错误/令牌失效有中文提示。
- [ ] 页面不直接调用 DeepSeek/智谱，也不把图片发到其它服务。
- [ ] 桌面端报告页可打印。

## 为什么不让 WorkBuddy 生成批改核心

化学方程式的配平、电荷、条件、↑↓、状态符号是确定性规则；生成式模型容易“算错但看起来合理”。ChemEq 的设计是 **VLM 只转写，解析器判分**，所以前端可以换，判分引擎不换。
