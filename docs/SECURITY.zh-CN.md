# 安全边界与演示限制

## 设计上仅限本地

- Compose 只把应用、API、Odoo、n8n 与 Mailpit 发布到 127.0.0.1。Postgres 没有宿主端口。
- Mailpit 是唯一的 SMTP 目的地。未配置真实邮件服务商或外部中继。
- Odoo API key、PostgreSQL 密码、automation token、n8n 加密密钥、owner 密码和临时导入文件都位于 Git 忽略的 .local/。
- Odoo API key 以只读 secret 文件挂载到 API/worker；Odoo Web 服务不挂载宿主机 `.local` 目录。Seed 交接只在 PowerShell 内存中捕获，绝不回显到日志。key 不存在于源码、工作流 JSON、响应 payload 或本文档中。
- 在 Unix 上，应用 seed 容器写入本地 automation token 时使用调用方宿主 UID/GID，使 mode-0600 文件对宿主 provisioner 可读，同时不会变成全局可读。
- n8n 工作流 JSON 只包含凭据引用。临时本地凭据 JSON 导入 n8n 后即删除；n8n 使用 N8N_ENCRYPTION_KEY 加密持久化凭据。
- n8n owner 密码哈希从本地文件挂载。哈希文件、明文密码文件、加密密钥文件和持久化数据库都应在本地访问控制下。
- 独立 Postgres 角色/数据库限制应用、Odoo、n8n 与测试数据。

## 身份与审批控制

应用的角选择器有意绕过正常认证，仅用于本地演示。它可见，并明确记录为演示身份选择器。它**不**适用于生产或可网络访问的共享环境。领域操作仍然执行角色、部门、财务审批职责分离、版本检查与状态转换。

automation token 是带 automation 角色的受限服务凭据，只允许用于集成端点。n8n 摘要输出有意最小化。管理员/财务/采购视图有额外 ERP 细节；申请人/负责人视图不会收到原始 Odoo API key 或内部凭据数据。

## 运行限制

- 不声称具备 TLS、SSO、外部身份提供方、secrets manager、生产备份/恢复工作流或多租户隔离。
- Compose Odoo 用户与 API key 是合成的演示最小权限凭据，不能替代生产 IAM 审查。
- 仅使用本地合成数据。不要把真实员工、供应商、银行或合同数据放入演示。
- 保持所有端口仅回环。不要暴露 n8n；它是带有特权服务凭据的工作流编辑器。
- 系统只创建并核验草稿采购单。它不确认采购单、收货、过账账单或付款。
