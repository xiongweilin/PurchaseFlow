# Feishu 适配器状态

**状态：未针对真实租户验证。** 未提供 Feishu 租户、应用、Verification Token、Encrypt Key 或授权 Webhook 端点。本地适配器只能离线测试；它不注册外部回调、不调用 Feishu API，也不保存租户凭据。

## 支持的本地契约

`backend/app/feishu_adapter.py` 是租户特定 Feishu 表单/审批事件提取器与现有 n8n 采购接入之间的边界。它：

1. 处理 Feishu URL 验证 challenge，并用常量时间比较检查配置的 Verification Token。
2. 接受 v2.0 回调 metadata 并返回稳定的 `header.event_id`。v1 回调被有意拒绝，直到租户选择并测试 v1 事件。
3. 在配置 Encrypt Key 时，对精确请求体提供可选的、带新鲜度约束的 SHA-256 签名验证。
4. 将配置的租户字段 ID 映射到现有接入契约：`external_event_id`、`requester_email`、`department_code`、`supplier_ref`、`reason`，以及 1–3 条 `lines`（`sku`、`quantity`、`unit_price`）。
5. 使用 Feishu 事件 ID 作为现有 API 幂等键。因此完全相同的重放返回原申请；同一 ID 的不同内容会被 API 作为冲突拒绝。

选定的 Feishu 事件类型和审批/表单值提取是租户特定的。配置从稳定 Feishu 字段 ID 到上述规范字段的 `field_map`，然后将规范化 JSON POST 到认证的 n8n Intake Webhook，并令 `Idempotency-Key` 等于 `external_event_id`。将 Feishu 的 Verification Token、Encrypt Key 和单独的 n8n 服务凭据保存在 secret store 中；绝不要放入本仓库或表单响应。

Encrypt Key 签名辅助函数验证来源与新鲜度，但本演示不解密 Feishu 的可选加密事件 envelope，也不调用 Feishu API。启用该模式前，加入租户批准的解密/密钥轮换路径并用真实租户验证。在此之前，保持 Feishu 未配置，继续使用认证的本地 n8n Webhook。

## 离线验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\unit\test_feishu_adapter.py
```

测试只使用合成 token、事件 ID 和表单字段，不发送网络请求。
规范化 payload 形状见 [`docs/examples/feishu-normalized-intake.example.json`](examples/feishu-normalized-intake.example.json)。

## 协议参考

- [Feishu 事件概览](https://open.feishu.cn/document/server-docs/event-subscription-guide/overview)（事件回调模式与 v2.0 envelope）。
- [Lark 事件示例](https://open.larksuite.com/document/server-docs/meeting_room-v1/event/third-room-event-changes)（回调 Verification Token 与唯一 `event_id`）。
- [官方 Lark Node SDK 回调验证](https://github.com/larksuite/node-sdk/blob/main/dispatcher/request-handle.ts)（签名验证实现）。
