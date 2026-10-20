# PurchaseFlow

[简体中文](README.md) | English

**A procurement approval and Odoo 19 draft purchase-order integration demo for small and medium-sized businesses.**

After an employee submits a purchase request, the system routes it for human approval by department and amount. Once approved, a background worker creates a draft purchase order only in real Odoo and independently reads it back for verification; only requests that pass verification can be closed.

![PurchaseFlow workbench](docs/screenshots/dashboard.png)

## What it demonstrates

- Role-specific workbenches for requesters, department managers, finance, procurement, and administrators.
- CNY amounts calculated with Decimal, approval levels determined by pre-tax/tax-inclusive policy, and the request version frozen at submission.
- Append-only approvals and audit records, idempotency keys, a transactional Outbox, and an at-least-once background Worker.
- Stable external intent identifiers and read-after-write verification of real Odoo 19 Community purchase drafts.
- Distinguishing ERP unknown, failed, mismatched, and verified outcomes; when the result is unclear, it does not blindly create another purchase order.
- Two n8n workflows: authenticated procurement-request intake and a weekday approval/ERP digest; email is received by local Mailpit.
- Docker Compose, isolated PostgreSQL databases and roles, Alembic migrations, unit and PostgreSQL concurrency tests, and Playwright browser acceptance.

~~~mermaid
flowchart LR
  U[Requester / approver] --> W[React + TypeScript workbench]
  W --> A[FastAPI business flow and permissions]
  A <--> D[(PurchaseFlow PostgreSQL)]
  A --> O[Transactional Outbox]
  O --> X[Background Worker]
  X -->|JSON-2, stable intent| E[Odoo 19 Community]
  X -->|independent read-back| E
  N[n8n] -->|restricted service credential| A
  N -->|internal SMTP only| M[Mailpit mailbox]
~~~

This demo **does not confirm purchase orders, receive goods, post vendor bills, or make payments**. Approval thresholds and procurement data are synthetic demo data and do not constitute financial-rule advice for a real business.

## Local start

Docker Desktop with Compose v2, PowerShell 7, and network access for the initial image and dependency downloads are required.

~~~powershell
pwsh ./scripts/start-demo.ps1
~~~

The command prepares Odoo 19 and local credentials, creates isolated application and n8n databases, builds the API and frontend images, runs Alembic migrations and an idempotent seed, imports encrypted n8n credentials and workflows, and runs health checks.

| Service | Local address |
|---|---|
| PurchaseFlow | <http://127.0.0.1:18081> |
| FastAPI docs | <http://127.0.0.1:18000/docs> |
| Odoo 19 | <http://127.0.0.1:18069> |
| n8n editor | <http://127.0.0.1:18082> |
| Mailpit inbox | <http://127.0.0.1:18025> |

The login page provides an **explicit demo identity selector**, not production authentication. Choose a synthetic role to see the corresponding workflow. n8n uses a generated local administrator account (`automation-admin@demo.local`); the password is stored in Git-ignored `.local/n8n-owner-password`. Odoo bootstrap and administrator credentials are also stored in ignored files under `.local/`.

### n8n workflows

- **Authenticated procurement intake**: `POST http://127.0.0.1:18082/webhook/purchaseflow/intake`. Validates and submits an idempotent request through an API available only to the automation role.
- **Daily approval and ERP digest**: runs at 09:00 Asia/Shanghai on weekdays, and can also be invoked at `POST http://127.0.0.1:18082/webhook/purchaseflow/summary`. The workflow reads a filtered summary API and sends email to synthetic manager/finance addresses; Mailpit receives it locally and never delivers externally.

Both webhooks require `Authorization: Bearer <local automation token>`. The token is stored in `.local/automation-token.txt`; n8n credentials are imported from a temporary ignored file and stored encrypted with the persistent `.local/n8n.env` key. Workflow JSON contains no token or SMTP settings. Running `scripts/verify-demo.ps1 -ExerciseN8nWorkflows` tests intake idempotency and the local digest email, creating one synthetic pending request and one Mailpit message.

## Acceptance and testing

~~~powershell
pwsh ./scripts/verify-demo.ps1
pwsh ./scripts/verify-demo.ps1 -ExerciseN8nWorkflows
pwsh ./scripts/bootstrap-test-db.ps1
docker compose -p purchaseflow-demo -f docker-compose.yml --profile test run --rm tests
~~~

The first `verify-demo.ps1` is read-only. The optional n8n workflow acceptance creates one synthetic request and one local email.

Browser acceptance uses Node.js 24:

~~~powershell
cd frontend
npm ci
npx playwright install chromium
npm run build
npm run e2e
~~~

Browser tests cover the normal Odoo handoff, department-manager and distinct-finance approvals, and the requester being unable to approve through the API. Real Odoo field mismatch and UNKNOWN recovery require preparing the corresponding scenarios first:

~~~powershell
pwsh ./scripts/run-erp-unknown-demo.ps1
pwsh ./scripts/run-erp-mismatch-demo.ps1 -Prepare
npm run e2e
pwsh ./scripts/run-erp-mismatch-demo.ps1 -Restore
~~~

The UNKNOWN script creates a synthetic request through the API, briefly stops this project's Worker, creates one draft in real Odoo, discards the success response, and then restarts the Worker. Procurement verifies through the same stable intent and can close the case. The mismatch script creates and verifies a real Odoo draft, then changes a line unit price by CNY 1. PurchaseFlow must show the actual difference, mark the request `erp_mismatch`, and refuse to close it; the browser can inspect the difference and run a read-only verification again. Finally the script restores the original unit price and requires PurchaseFlow to read the same draft back as `erp_verified`. The control scripts modify only synthetic drafts newly created in this project's isolated demo environment.

When scenario files exist, `npm run e2e` includes the corresponding browser recovery or mismatch tests. After browser acceptance, run `pwsh ./scripts/verify-persistence.ps1`; it restarts only this project's services (without deleting volumes) and rechecks requests, real Odoo drafts, n8n workflows, and Mailpit email.

`scripts/seed-demo.ps1` can rerun idempotent migrations and seed data after startup. `scripts/reset-demo.ps1` deletes only the PurchaseFlow project's own volumes after an explicit confirmation phrase is entered; normal stop commands never call it. The script lists the confirmation phrase and affected volumes before asking for confirmation.

GitHub Actions runs Python static checks and type checks, Python and npm dependency audits, isolated PostgreSQL concurrency tests, Docker/Odoo/n8n/Mailpit startup acceptance, static n8n contract checks, and browser tests. The manually run [`controlled-purchaseflow-integration`](.github/workflows/controlled-purchaseflow-integration.yml) also verifies real Odoo response loss, UNKNOWN recovery, field mismatch, refusal to close a mismatched case, browser display of differences, restoration and re-verification, and persistence after service restart. `main` requires merging through a Pull Request and passing the `acceptance` check in `PurchaseFlow CI`.

## Safe stop

~~~powershell
pwsh ./scripts/stop-demo.ps1
~~~

The command stops containers and **preserves** PostgreSQL, Odoo filestore, n8n, and Mailpit data volumes. Starting again does not delete data and reruns the idempotent seed steps. Local credentials are stored in Git-ignored `.local/`. Keep the pairing between `.local/n8n.env` and the named n8n data volume; without the encryption key, n8n cannot decrypt stored credentials. All service ports bind only to loopback `127.0.0.1`, never to the LAN.

## Architecture and evidence

[4.5-minute product demo with Chinese subtitles](docs/RECORDING.en.md)

![PurchaseFlow role-specific workbench](docs/assets/purchaseflow-overview.png)

- [System architecture](docs/ARCHITECTURE.md)
- [Business rules](docs/BUSINESS-RULES.en.md)
- [Workflow authority and failure states](docs/WORKFLOW-AUTHORITY.en.md)
- [Data contracts](docs/DATA-CONTRACTS.en.md)
- [Odoo integration and security boundaries](docs/ODOO-INTEGRATION.en.md)
- [Local operations runbook](docs/RUNBOOK.md)
- [Security boundaries](docs/SECURITY.md)
- [Test evidence and limitations](docs/TEST-EVIDENCE.en.md)
- [Portfolio narrative](docs/PORTFOLIO.md)
- [Interview pitch](docs/INTERVIEW-PITCH.en.md)
- [Recording and subtitles](docs/RECORDING.en.md)
- [Feishu adapter status and tenant onboarding](docs/FEISHU.md)
- [Versioned n8n workflows](n8n/workflows/)

Feishu is an optional extension and is not connected to a real tenant; this project does not claim a live Feishu integration.
