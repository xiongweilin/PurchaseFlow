# Feishu adapter status

**Status: NOT VERIFIED against a tenant.** No Feishu tenant, application, Verification Token, Encrypt Key, or authorized webhook endpoint was provided. The local adapter is offline-testable only; it does not register an external callback, call Feishu APIs, or store a tenant credential.

## Supported local contract

`backend/app/feishu_adapter.py` is the boundary between a tenant-specific Feishu form/approval event extractor and the existing n8n procurement intake. It:

1. Handles Feishu URL-verification challenges and checks the configured Verification Token with constant-time comparison.
2. Accepts v2.0 callback metadata and returns the stable `header.event_id`. v1 callbacks are intentionally rejected until a tenant selects and tests a v1 event.
3. Provides optional freshness-bounded SHA-256 signature verification over the exact request body when an Encrypt Key is configured.
4. Maps configured tenant field IDs to the existing intake contract: `external_event_id`, `requester_email`, `department_code`, `supplier_ref`, `reason`, and one to three `lines` (`sku`, `quantity`, `unit_price`).
5. Uses Feishu's event ID as the existing API idempotency key. An identical replay therefore returns the original request; a changed body with the same ID is rejected by the API as a conflict.

The selected Feishu event type and the extraction of approval/form values are tenant-specific. Configure a `field_map` from stable Feishu field IDs to the canonical fields above, then POST the normalized JSON to the authenticated n8n Intake webhook with `Idempotency-Key` equal to `external_event_id`. Keep Feishu's Verification Token, Encrypt Key, and the separate n8n service credential in a secret store; never put them in this repository or a form response.

The Encrypt Key signature helper verifies origin and freshness, but this demo does not decrypt Feishu's optional encrypted event envelope or call Feishu's APIs. Before enabling that mode, add the tenant-approved decryption/key-rotation path and validate it with a real tenant. Until then, leave Feishu unconfigured and continue using the authenticated local n8n webhook.

## Offline verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\unit\test_feishu_adapter.py
```

The tests use synthetic tokens, event IDs, and form fields only. They do not send network requests.
The normalized payload shape is illustrated in [`docs/examples/feishu-normalized-intake.example.json`](examples/feishu-normalized-intake.example.json).

## Protocol references

- [Feishu event overview](https://open.feishu.cn/document/server-docs/event-subscription-guide/overview) (event callback modes and v2.0 envelope).
- [Lark event example](https://open.larksuite.com/document/server-docs/meeting_room-v1/event/third-room-event-changes) (callback Verification Token and unique `event_id`).
- [Official Lark Node SDK callback verification](https://github.com/larksuite/node-sdk/blob/main/dispatcher/request-handle.ts) (signature verification implementation).
