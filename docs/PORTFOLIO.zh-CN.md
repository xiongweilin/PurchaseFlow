# 作品集叙事

## 问题

小团队通常把采购收集在聊天和表格里。申请、负责人决策、财务复核、供应商/商品映射和 ERP 录入变成彼此分离的交接，申请人不容易知道当前在等谁，也不容易确认 ERP 是否收到已批准的采购。一个朴素的集成还可能在 Odoo 已提交但响应丢失时创建重复采购单。

## 产品决策

PurchaseFlow 把 ERP 边界当作可靠性与权限问题，而不是表单提交问题：

1. 申请人提交经过验证的申请，并看到所使用的带版本演示政策。
2. 不同审批人做出有记录的决定；第二位财务复核人不能是申请人或负责人。
3. 审批在同一事务中提交冻结快照、稳定 ERP 意图和 outbox 事件。
4. Worker 只写入草稿，然后独立读回。
5. 结果不明确时进入 erp_unknown；恢复按同一稳定意图查询，不盲目创建另一张草稿。
6. 真实 Odoo 对意图 ID 的唯一约束提供第二道防重复保护。

## 技术栈与边界

React/TypeScript 提供角色感知工作台。FastAPI 拥有工作流转换与授权。Postgres 保存带版本的工作流/审计数据和 outbox。后台 Worker 通过 JSON-2 与真实 Odoo 19 Community 集成。n8n 使用单独的自动化角色和加密凭据进行认证接入与通知。Mailpit 在本地捕获摘要。

整个栈运行在 Docker Compose 中，宿主机端口仅回环，使用独立 Postgres 数据库/角色、合成 CNY 数据，以及一键启动/验证/停止脚本。

## 两条 n8n 工作流

- **采购接入：** 接受认证的外部申请事件，映射其申请人/部门/供应商/商品字段，并通过仅限自动化的 API 提交，以事件 ID 作为幂等键。重放相同内容返回同一申请；复用事件 ID 但内容改变会被拒绝。
- **每日审批与 ERP 摘要：** 在工作日早晨或通过认证的手动 Webhook 运行，从 API 读取经过脱敏的摘要，并把邮件发给合成的经理/财务地址进入 Mailpit。它不读数据库，也不创建/审批 ERP 订单。

## 人工决策与不确定结果

部门负责人批准或拒绝申请。超过演示阈值时，必须由不同财务用户批准后才存在 ERP 意图。超过政策复核上限的金额会停下，等待明确记录的管理员例外，之后仍走常规负责人和财务步骤。PurchaseFlow 只在所需决策完成后写入 Odoo 草稿。

如果创建响应丢失，应用记录 `erp_unknown` 并停止自动创建。采购用户按同一意图 ID 查询 Odoo，查看真实返回事实，只有在读回确认订单不存在后才重试该意图。受控响应丢失场景使用真实 Odoo 记录，由 `scripts/run-erp-unknown-demo.ps1` 和浏览器恢复测试覆盖。

## 证据

- 真实 Odoo 19 Community JSON-2 创建、独立读回、重复意图防护与持久化检查：[测试证据](TEST-EVIDENCE.md)。
- Python 单元与 Postgres 并发测试：tests/。
- 浏览器验收：申请人 -> 负责人 -> Odoo 草稿核验、不同财务复核、UNKNOWN 恢复：[frontend/tests](../frontend/tests/)。
- n8n 认证接入/重放与本地 Mailpit 摘要：scripts/verify-demo.ps1 -ExerciseN8nWorkflows。
- [PurchaseFlow 工作台](assets/purchaseflow-overview.png)、[已提交申请](assets/purchaseflow-submitted-request.png)、[真实 Odoo 草稿读回](assets/purchaseflow-odoo-verified.png)、[对账前的 UNKNOWN](assets/purchaseflow-unknown-before-reconcile.png)、[已恢复的 UNKNOWN 申请](assets/purchaseflow-unknown-recovered.png)、[n8n 接入](assets/n8n-procurement-intake.png)、[n8n 每日摘要](assets/n8n-daily-digest.png) 与 [Mailpit 摘要](assets/purchaseflow-mailpit-digest.png)。
- 录屏与中文字幕：[录屏](assets/purchaseflow-demo.mp4)、[SRT 字幕](assets/purchaseflow-demo.zh-CN.srt)、[录屏提纲](RECORDING.md)。
- 简短面试说明：[INTERVIEW-PITCH.md](INTERVIEW-PITCH.md)。

## 截图

### 角色感知工作台

![PurchaseFlow 工作台](assets/purchaseflow-overview.png)

### 从应用中核验的真实 Odoo 草稿

![Odoo 采购草稿读回](assets/purchaseflow-odoo-verified.png)

### 人工对账前后的不明确创建结果

![等待采购核验的 UNKNOWN](assets/purchaseflow-unknown-before-reconcile.png)

![同一意图已对账到现有 Odoo 草稿](assets/purchaseflow-unknown-recovered.png)

### 运营自动化与本地邮件投递

![认证的 n8n 采购接入](assets/n8n-procurement-intake.png)

![定时与按需 n8n 摘要](assets/n8n-daily-digest.png)

![投递到本地 Mailpit 收件箱的摘要](assets/purchaseflow-mailpit-digest.png)

## 范围诚实

这是本地演示，不是生产采购产品。角色选择器仅用于演示。审批阈值是示例性的。范围止于 Odoo 草稿；不会确认采购单、收货、过账账单、付款或实际外发邮件。

Feishu 连接器是可选的未来扩展。本仓库不声称已有真实 Feishu 租户连接，因为没有可用的授权租户凭据。
