# Odoo 19 Community 集成

## 已验证现场

本项目使用独立部署的官方 Odoo Community 镜像 odoo:19.0-20260926 与专用 PostgreSQL 数据库 purchaseflow_odoo。Docker 镜像 RepoDigest、实际模块、HTTP 与 JSON-2 结果见 docs/TEST-EVIDENCE.md。

Odoo 19 官方 JSON-2 请求使用 POST /json/2/<model>/<method>、Authorization: bearer <API_KEY>、Content-Type: application/json；只有模型方法标注的字段来自运行中数据库 /doc 和该数据库的 fields_get。现场以动态查询取得 CNY、供应商、商品、UoM 与税的 ID。

## 权限与凭据

- purchaseflow.integration 是独立内部用户，仅加入 base.group_user 和 purchase.group_purchase_user。
- 当前用户只能访问 Demo Office Ltd. 公司。
- API key scope 为 Odoo 默认 RPC scope，30 天到期；模型访问继续受该用户的 Odoo ACL、record rule 与 company context 限制。
- API key 存放在被 Git 忽略的 .local/odoo-api-key；不进入代码、日志、n8n 工作流 JSON 或文档。
- Odoo seed 在 Odoo 自己的 filestore volume 中暂存新 key；PowerShell bootstrap 捕获一次性返回值到内存后写入本机 `.local`，不会回显 marker。Odoo web service 不挂载整个 `.local`；API/worker 仅以只读 secret-file 路径读取它。
- 未认证 JSON-2 请求得到 HTTP 401，限权用户读取 ir.config_parameter 得到 HTTP 403。

## 稳定意图和写入核验

本地审批通过后，每个 ERP 意图有稳定唯一 purchaseflow_intent_id。Odoo purchase.order 使用 purchaseflow_link 最小扩展字段，并在真实 PostgreSQL 中以唯一约束限制每个意图至多对应一张采购单。

PurchaseFlow Worker 只消费审批完成后在同一数据库事务中持久化的 ERP Intent/Outbox。每次 dispatch 使用稳定 `purchaseflow_intent_id`，先按该标记查询 Odoo，再创建 `purchase.order` 草稿，最后通过新的 JSON-2 `search_read` 读回。供应商、公司、币种、意图标记、商品行、数量、UoM、未税单价、税额口径及 `draft` 状态都必须匹配，才能进入 `erp_verified`。

请求超时或创建后的读回失败会保留为 `erp_unknown`；该状态不会自动再发起创建。采购人员可在业务操作台执行只读核验，确认远端存在后匹配同一意图并恢复状态。只有明确查无记录后，采购人员才可显式重试原意图。`scripts/run-erp-unknown-demo.ps1` 会暂停本项目 worker，通过真实 JSON-2 在 Odoo 创建一张 draft，再有意丢弃成功响应；随后从采购工作台读回、核验并结案。真实字段结果和执行证据见 `docs/TEST-EVIDENCE.md`。

独立读回若发现供应商、金额或采购明细与审批快照不同，会保留 `expected` 与 Odoo `actual` 值并进入 `erp_mismatch`。该状态不提供结案操作。`scripts/run-erp-mismatch-demo.ps1` 在隔离验收环境中修改刚创建的 Odoo 草稿行价，验证 UI/API 展示差异且拒绝结案，再恢复原价并对同一草稿重新读回核验。

## 演示税务口径

公司币种固定 CNY，不做汇率换算。种子货品使用 13% 购买税，服务使用 6% 购买税，均为不含税价格。PurchaseFlow 审批与金额显示须将未税额、税额、含税总额分开，并按政策说明使用的审批金额口径。
