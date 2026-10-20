# 架构

## 运行时

~~~mermaid
flowchart LR
  Browser[React / TypeScript] -->|同源 JSON API| API[FastAPI]
  API <--> D[(PurchaseFlow Postgres)]
  API -->|事务内插入| Outbox[(Outbox)]
  Worker[Outbox worker] -->|claim / retry| Outbox
  Worker -->|Odoo JSON-2| Odoo[Odoo 19 Community]
  Worker -->|写后读回| Odoo
  N8N[n8n 2.x] -->|受限服务凭据| API
  N8N -->|SMTP，私有 Compose 网络| Mailpit[Mailpit]
  Mailpit -->|仅回环 UI| Operator[本机操作者]
~~~

该演示是一个合成的单一 CNY 组织。Compose 使用一个 Postgres 服务器，但为应用、Odoo、n8n 和 Postgres 集成测试使用不同数据库与非 superuser 登录角色。PostgreSQL 不发布到宿主机。Odoo、n8n、Mailpit、API 与 Web UI 只绑定到 127.0.0.1。

## 应用边界

- **前端：** React 19 + TypeScript + Vite；按角色展示工作列表、申请编辑/详情、政策管理，以及 Odoo 已核验映射的只读视图。
- **API：** FastAPI/Pydantic 领域边界。演示身份选择显式且仅用于演示。API 操作会重新检查角色、部门、记录版本、状态转换与组织范围。
- **Postgres：** 申请、冻结的提交快照、审批、政策版本、幂等记录、审计事件、ERP 意图与 outbox 行的权威来源。
- **Worker：** 在短事务中领取 outbox 工作，在请求事务之外执行网络 I/O，并且只有在其单调递增的租约代次仍然当前且未过期时才记录结果。Worker 崩溃后租约可恢复；被替换或过期 Worker 的迟到结果会被隔离在本地状态之外。
- **Odoo：** 供应商/商品/税务记录的权威来源，以及最终采购草稿账本。API 不保存 Odoo 密码，也不使用浏览器/session cookie。
- **n8n：** 仅作认证服务集成。其工作流调用专用集成端点；凭据单独导入并加密保存在 n8n 数据库中。
- **Mailpit：** 捕获所有演示 SMTP 流量。未配置外部 SMTP 中继。

## 申请生命周期

~~~mermaid
stateDiagram-v2
  [*] --> draft
  draft --> pending_manager: 提交
  pending_manager --> rejected: 负责人拒绝
  pending_manager --> pending_finance: 金额 > 负责人额度
  pending_manager --> approved: 金额 <= 负责人额度
  pending_finance --> rejected: 财务拒绝
  pending_finance --> approved: 不同财务用户批准
  approved --> erp_pending: 持久意图 + outbox
  erp_pending --> erp_verified: 创建并独立读回匹配
  erp_pending --> erp_unknown: 远端结果不明确
  erp_pending --> erp_failed: 确定的远端失败
  erp_pending --> erp_mismatch: 读回不一致
  erp_unknown --> erp_verified: 对账找到匹配意图
  erp_unknown --> erp_mismatch: 对账找到冲突记录
  erp_verified --> closed: 采购在本地结案
~~~

5,000 与 20,000 CNY 是带版本的演示政策。提交会冻结用于决策的确切政策版本与行/主数据快照。政策编辑绝不会静默重算既有提交。

## 幂等与 ERP 边界

浏览器为可重试的用户操作发送幂等键。n8n 接入要求 Idempotency-Key 与 external_event_id 一致。稳定 ERP 意图与审批、outbox 工作一起提交后才会调用 Odoo。Odoo 扩展对该意图 ID 有数据库唯一约束。随后 Worker 独立读取 Odoo 订单并比较公司、币种、供应商、行、税与草稿状态。

超时是 **unknown** 结果，不是再次创建的许可。恢复首先按同一意图查询。演示只支持创建草稿与核验；确认、收货、账单与付款不在范围内。
