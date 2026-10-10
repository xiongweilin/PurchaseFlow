# 业务字段来源、版本与核验契约

本文件定义跨申请 API、审批、后台执行和 Odoo 的持久字段责任。API 请求只在完成验证并绑定申请版本后成为采购事实。

| 字段 | authoritative source / state | owner 与版本绑定 | validation / read-back | allowed use |
|---|---|---|---|---|
| requester_id | PurchaseFlow 登录身份，active | Auth 服务；绑定申请 version | token 有效、成员存在 | 审计和“我的申请”筛选 |
| department_id | PurchaseFlow 部门主数据 | Admin 配置；申请提交快照 | 申请人所属组织和部门匹配 | 负责人审批路由 |
| reason | Requester 的提交字段 | Requester 仅在 draft 编辑；随申请版本冻结 | 非空、长度限制、审计 | 审批上下文 |
| vendor_ref | 受控映射到 Odoo res.partner | Admin 映射；映射版号存于快照 | 启动校验 Odoo ID/供应商标志；写入前再读 | purchase.order.partner_id |
| product_ref | 受控映射到 Odoo product.product | Admin 映射；保存 Odoo ID、SKU 与映射版本 | Odoo 活跃、可采购、公司/币种适用 | purchase.order.line.product_id |
| quantity | Requester 输入的十进制字符串 | Requester draft；提交快照 | Decimal、>0、精度符合 UoM | 审批和订单行 |
| unit_price | 受控商品价格，申请者可按允许范围输入 | Requester draft；提交快照记录来源 | Decimal、非负、币种舍入；审批后冻结 | 审批金额与 price_unit |
| currency | 演示政策固定 CNY | Admin 演示公司配置；申请版本绑定 | 对照 Odoo 公司币种与 purchase.order.currency_id | 不做汇率换算 |
| amount_untaxed | 由行数量、单价及 Odoo 税规则计算 | PurchaseFlow Decimal 计算；Odoo 是落地事实 | Odoo 读回与本地预期在舍入容差内比较 | 展示未税额 |
| amount_tax / amount_total | Odoo 根据行与供应商税计算 | Odoo 是税额和含税额 owner；同步快照记录税率规则 | JSON-2 读回字段；核对税额和含税总额 | 财务审批说明、核验 |
| approval_policy_version | PurchaseFlow 当前演示规则 | Admin 发布版本；申请提交时绑定 | 审批时重验版本未变 | 解释审批路径 |
| erp_intent_id | PurchaseFlow UUID | 审批通过后 Worker 创建一次；唯一约束 | Odoo purchaseflow_intent_id 唯一；重读匹配 | 远端定位、UNKNOWN 恢复、防重复 |
| odoo_order_id / odoo_order_name | Odoo purchase.order | 仅 Verifier 根据 read-back 保存 | 再次 search_read/read 查证 ID、来源标记和单号 | 展示真实 ERP 引用 |
| erp_disposition | Verifier 的当前观察 | Verifier 保存观察时间、请求身份与版本 | VERIFIED/ABSENT/MISMATCH/UNAVAILABLE/UNKNOWN；不能混为成功/失败 | 业务状态推进与人工交接 |
| audit_actor_id / event | 服务端认证身份与业务动作 | Audit 服务追加写入 | 每次审批、映射变更、ERP 调用和恢复都留痕 | 追责与复现，不可写入客户端伪值 |

## 数值口径

- 所有申请金额使用 Decimal，不使用二进制浮点。
- 演示政策审批用数量 × 单价的 CNY 小计；若配置供应商税，则审批路由必须使用预计含税金额。实现前后端统一采用 Odoo 实际 tax rule 读回计算后的金额。
- 画面区分未税额、税额、含税总额。Demo seed 使用固定且明确的税率；不依赖数据库默认税或固定记录 ID。
- Odoo 只读回是当前远端事实；PurchaseFlow 审批快照是获批意图，两者任一不匹配都不得推进为已同步。
