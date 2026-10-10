# Architecture

## Runtime

~~~mermaid
flowchart LR
  Browser[React / TypeScript] -->|same-origin JSON API| API[FastAPI]
  API <--> D[(PurchaseFlow Postgres)]
  API -->|transactional insert| Outbox[(Outbox)]
  Worker[Outbox worker] -->|claim / retry| Outbox
  Worker -->|Odoo JSON-2| Odoo[Odoo 19 Community]
  Worker -->|read-after-write| Odoo
  N8N[n8n 2.x] -->|scoped service credential| API
  N8N -->|SMTP, private Compose network| Mailpit[Mailpit]
  Mailpit -->|loopback UI only| Operator[Local operator]
~~~

The demo is a single synthetic CNY organization. Compose uses one Postgres server but distinct databases and non-superuser login roles for the application, Odoo, n8n, and Postgres integration tests. PostgreSQL is not published to the host. Odoo, n8n, Mailpit, the API, and the web UI bind only to 127.0.0.1.

## Application boundaries

- **Frontend:** React 19 + TypeScript + Vite; role-specific worklists, request composer/detail, policy administration, and a read-only view of Odoo-validated mappings.
- **API:** FastAPI/Pydantic domain boundary. Demo identity selection is explicit and demo-only. API actions re-check role, department, record version, state transition, and organization scope.
- **Postgres:** source of truth for requests, frozen submission snapshots, approvals, policy versions, idempotency records, audit events, ERP intents, and outbox rows.
- **Worker:** claims outbox work in a short transaction, performs network I/O outside the request transaction, and records the result. A worker lease is recoverable after a crash.
- **Odoo:** authoritative supplier/product/tax records and the final purchase-draft ledger. The API does not store an Odoo password or use a browser/session cookie.
- **n8n:** authenticated service integration only. Its workflows call purpose-built integration endpoints; credentials are imported separately and encrypted in n8n's database.
- **Mailpit:** captures all demo SMTP traffic. No external SMTP relay is configured.

## Request lifecycle

~~~mermaid
stateDiagram-v2
  [*] --> draft
  draft --> pending_manager: submit
  pending_manager --> rejected: manager rejects
  pending_manager --> pending_finance: amount > manager limit
  pending_manager --> approved: amount <= manager limit
  pending_finance --> rejected: finance rejects
  pending_finance --> approved: different finance user approves
  approved --> erp_pending: durable intent + outbox
  erp_pending --> erp_verified: create and independent read-back match
  erp_pending --> erp_unknown: remote result ambiguous
  erp_pending --> erp_failed: definitive remote failure
  erp_pending --> erp_mismatch: read-back differs
  erp_unknown --> erp_verified: reconcile finds matching intent
  erp_unknown --> erp_mismatch: reconcile finds conflicting record
  erp_verified --> closed: procurement closes locally
~~~

The 5,000 and 20,000 CNY limits are versioned demo policy. A submission freezes the exact policy version and line/master-data snapshot used for the decision. A policy edit never silently recalculates an existing submission.

## Idempotency and the ERP boundary

The browser sends idempotency keys for retriable user actions. The n8n intake requires Idempotency-Key to match external_event_id. A stable ERP intent is committed with approval and outbox work before Odoo is called. The Odoo extension has a database unique constraint on that intent ID. The worker then reads the Odoo order independently and compares company, currency, supplier, lines, taxes, and draft state.

A timeout is an **unknown** outcome, not permission to create again. Recovery first searches by the same intent. The demo supports draft creation and verification only; confirmation, receipts, bills, and payments are outside scope.
