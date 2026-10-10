# 演示录屏

成片：[PurchaseFlow 采购审批与 Odoo 草稿核验](assets/purchaseflow-demo.mp4) · [简体中文字幕](assets/purchaseflow-demo.zh-CN.srt)。

## 录制内容

1. 展示采购总览和岗位待办。
2. 申请人建立采购申请并提交。
3. 部门负责人审批；高额申请进入不同财务人员复核。
4. 展示 Odoo 中真实创建并独立读回的草稿采购单。
5. 展示真实 Odoo 已提交、应用却没有收到创建响应的 UNKNOWN 状态。
6. 采购人员按原意图只读查询、核验并结案。
7. 查看 n8n 接单、每日摘要工作流及 Mailpit 中的实际摘要邮件。

## 复现录制

从仓库根目录执行：

~~~powershell
pwsh ./scripts/start-demo.ps1
pwsh ./scripts/verify-demo.ps1 -ExerciseN8nWorkflows
pwsh ./scripts/run-erp-unknown-demo.ps1
cd frontend
npm ci
npx playwright install chromium
npm run record-demo
~~~

录制使用当前运行的 React、FastAPI、PostgreSQL、Odoo 19、n8n 与 Mailpit，不会连接真实支付、供应商邮箱或 Feishu。浏览器录制脚本会创建一笔合成的高额采购申请和一个本地摘要邮件；响应丢失场景由 `run-erp-unknown-demo.ps1` 生成。执行前检查画面中不包含 `.local` 文件、密码或 API key。生成源视频暂存于被 Git 忽略的 `.local/recording/`，脚本完成后输出可分享的 MP4 与 SRT 到 `docs/assets/`。

## 时间线

中文字幕逐段说明业务问题、两条 n8n 流程、部门与财务的人工作用、Odoo 独立读回，以及外部结果不确定时的人工核查。画面均来自本地真实服务和合成数据；成片不声称真实企业收益或生产部署效果。
