# n8n workflow source

These JSON definitions are versioned without service tokens or SMTP secrets. scripts/provision-n8n.ps1 imports local credentials from an ignored temporary file, assigns them to the generated n8n owner, imports and publishes these workflows, then recreates n8n so published versions load.

- **PurchaseFlow · Authenticated procurement intake**: authenticated POST /webhook/purchaseflow/intake; maps an event to a requester-scoped PurchaseFlow submission. The workflow sets Idempotency-Key from external_event_id.
- **PurchaseFlow · Daily approval and ERP digest**: weekdays at 09:00 Asia/Shanghai, plus authenticated POST /webhook/purchaseflow/summary; calls the minimal integration summary and sends to synthetic manager/finance addresses through internal Mailpit SMTP.

Both webhook nodes use an explicit stable webhookId, so their production URLs match the paths shown in the n8n editor. All service credentials are stored in n8n's encrypted credentials store using the local encryption key, not in the workflow JSON.

The manual digest endpoint and intake endpoint require Authorization: Bearer followed by the value in .local/automation-token.txt. Never commit that file, the temporary credential import JSON, or .local/n8n.env.
