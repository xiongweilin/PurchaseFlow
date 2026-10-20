# n8n 工作流源文件

这些 JSON 定义带版本管理，不包含服务 token 或 SMTP 密钥。scripts/provision-n8n.ps1 从被忽略的临时文件导入本地凭据，分配给生成的 n8n owner，导入并发布这些工作流，然后重建 n8n 以加载已发布版本。

- **PurchaseFlow · 认证采购接入**：认证 POST /webhook/purchaseflow/intake；将事件映射为申请人范围的 PurchaseFlow 提交。工作流从 external_event_id 设置 Idempotency-Key。
- **PurchaseFlow · 每日审批与 ERP 摘要**：工作日 Asia/Shanghai 09:00，以及认证 POST /webhook/purchaseflow/summary；调用最小集成摘要，并通过内部 Mailpit SMTP 发送到合成经理/财务地址。

两个 Webhook 节点都使用显式稳定 webhookId，因此其生产 URL 与 n8n 编辑器中显示的路径一致。所有服务凭据都使用本地加密密钥保存在 n8n 的加密凭据库中，而不是工作流 JSON。

手动摘要端点和接入端点要求 Authorization: Bearer 加上 .local/automation-token.txt 中的值。绝不要提交该文件、临时凭据导入 JSON 或 .local/n8n.env。
