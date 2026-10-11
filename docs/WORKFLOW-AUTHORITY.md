# 采购流程参与者与权限

## 流程图

~~~mermaid
stateDiagram-v2
  [*] --> draft
  draft --> pending_manager: 申请人提交并冻结业务字段
  draft --> cancelled: 申请人撤销
  pending_manager --> rejected: 部门负责人拒绝
  pending_manager --> pending_finance: 金额 > 5,000 CNY 且负责人批准
  pending_manager --> approved: 金额 ≤ 5,000 CNY 且负责人批准
  pending_finance --> rejected: 财务拒绝
  pending_finance --> approved: 不同财务人员批准
  pending_manager --> policy_review: 金额 > 20,000 CNY
  pending_finance --> policy_review: 金额 > 20,000 CNY
  approved --> erp_pending: 系统持久化获批版本对应的 ERP 意图
  erp_pending --> erp_unknown: Odoo 请求结果不明确
  erp_pending --> erp_verified: Odoo 写入后独立读回匹配
  erp_pending --> erp_mismatch: 读回事实不匹配
  erp_unknown --> erp_verified: 人工发起查询后匹配
  erp_unknown --> erp_mismatch: 查询发现错配
  erp_unknown --> erp_pending: 经核验确认不存在后重派同一意图
  erp_mismatch --> erp_verified: 采购管理员纠正/核验后
  erp_verified --> closed: 采购管理员结案
~~~

## 参与者与责任

| 参与者 | 可做的事 | 不可做的事 | transition owner / evidence |
|---|---|---|---|
| Requester | 创建/编辑草稿、提交、撤销未审批申请 | 审批自己的申请；提交后改动获批字段 | 后端验证所属用户；提交时保存业务快照与版本 |
| Manager | 审批本部门待审申请 | 审批自己提出的申请；审批其他部门 | 后端检查部门范围、角色、申请版本和待审状态；决定写审计 |
| Finance | 复核高额申请、查看金额和 ERP 状态 | 与部门审批同一人复核；直接改采购内容 | 后端检查金额阶段、不同用户与版本；决定写审计 |
| Procurement | 查看获批申请、处理 ERP 异常、确认已核验单据并结案 | 未核验时结案；直接绕过审批创建订单 | 人工处理有审计；结案要求 erp_verified |
| Admin | 管理演示用户、规则和映射 | 绕过金额/四眼/审批冻结门禁 | 规则变更有版本与审计；不拥有 ERP 写入 |
| Automation / n8n | 按服务身份提交申请、读取摘要 | 审批、直接操作数据库或 Odoo | API 只接受受限输入；服务端验证 token 与字段 |
| Worker | 消费获批 ERP 意图，调用 Odoo 创建草稿、回读 | 自行批准、确认采购单、付款 | 只处理数据库中已批准且版本匹配的唯一意图；只有当前未过期租约代次的 Worker 能提交结果 |
| Verifier | 根据独立 Odoo 读回证据分类 | 用写请求 HTTP 200 代替读回 | 匹配完整关键字段后标记 erp_verified |

## 关键外部边界

- purchase.order/create 是唯一 Odoo 采购写入方法；任何代码路径不得调用 button_confirm、收货、账单过账或付款接口。
- 创建意图在调用前持久化。请求超时、连接中断或响应无法解析进入 erp_unknown；不自动新建第二个意图。
- 恢复按稳定 purchaseflow_intent_id 查询 Odoo。读回存在则验证；权威查询不可用时保持未知；确认不存在后只能重试同一稳定标识。
- Odoo 写入的草稿状态、申请快照、API 事实及人工结案分别是不同证据和状态。
- Outbox 每次领取都递增 `lease_generation`。Worker 只有在事件仍为 `processing`、代次仍匹配且租约未过期时，才能在同一事务中保存 ERP 意图、申请状态和读回观察；过期执行的迟到结果被丢弃。Odoo 上稳定意图的唯一约束仍负责阻止重复采购草稿。

## 审批状态规则

- 申请人不能批准本人申请。
- amount_total > 5000.00 CNY 必须部门负责人先批准，再由不同财务用户复核。
- amount_total > 20000.00 CNY 转入人工政策审核，不自动创建 Odoo 订单。
- 每次批准必须提交被审版本；业务字段冻结。版本冲突或并发重复决策不产生第二个批准结果。
- 拒绝或撤销终止自动化，不生成 ERP Effect。

## 重试与人工恢复

- 可安全重试的情况由明确的未执行结果（例如 Odoo 的确定性 4xx error）决定，不用通用网络异常推断。
- 外部调用 outcome unknown 时，仅允许只读查询。查询 unavailable 仍为 unknown，不生成新的 ERP 意图。
- Procurement 可以在确认 Odoo 无记录后对原 ERP Effect 执行显式恢复。远端唯一约束和稳定来源标记防止重复。
- 验证失败为 erp_mismatch，保留期望快照和远端读回，待人工调查；不得标记成功或结案。
