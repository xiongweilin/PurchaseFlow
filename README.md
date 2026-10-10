# PurchaseFlow

**Small-business procurement approvals with a verified Odoo 19 draft handoff.**

PurchaseFlow is a local-first, portfolio-grade demo: employees create a purchase request, the system routes it through department and (where required) finance approval, then an outbox worker creates **only an Odoo draft** and independently reads it back before showing the ERP check as verified.

![PurchaseFlow workbench](docs/screenshots/dashboard.png)

## What it demonstrates

- Role-aware requester, department manager, finance, procurement, and admin worklists.
- Decimal-based CNY calculations, explicit tax-inclusive approval thresholds, optimistic versions, and a frozen submission snapshot.
- Append-only decisions and audit history, idempotency keys, a transactional outbox, and an at-least-once worker.
- A stable external intent key and a read-after-write comparison against a real Odoo 19 Community database.
- Recovery that distinguishes unknown, failed, mismatched, and verified ERP outcomes; it never blindly creates a second PO after an ambiguous timeout.
- Two published n8n workflows: authenticated procurement intake and a weekday approval/ERP digest. Digest email is captured locally by Mailpit.
- Docker Compose, isolated Postgres roles/databases, Alembic migrations, unit/Postgres concurrency tests, and a Playwright end-to-end acceptance flow.

~~~mermaid
flowchart LR
  U[Requester / approver] --> W[React + TypeScript]
  W --> A[FastAPI policy and workflow API]
  A <--> D[(PurchaseFlow Postgres)]
  A --> O[Transactional outbox]
  O --> X[Background worker]
  X -->|JSON-2, stable intent| E[Odoo 19 Community]
  X -->|read-after-write| E
  N[n8n] -->|scoped service credential| A
  N -->|SMTP, private network only| M[Mailpit inbox]
~~~

This demo **does not confirm purchase orders, receive goods, post vendor bills, or pay suppliers**. Approval thresholds are synthetic demo policy, not financial advice or a recommendation for a real company.

## Start locally

Requirements: Docker Desktop with Compose v2, PowerShell 7, and network access for the first image/dependency download.

~~~powershell
pwsh ./scripts/start-demo.ps1
~~~

The command bootstraps Odoo 19 and local secrets, creates separate app/n8n databases, builds the API/web images, runs Alembic and idempotent seed data, imports encrypted n8n credentials/workflows, and runs health/acceptance checks.

| Service | Local URL |
|---|---|
| PurchaseFlow | <http://127.0.0.1:18081> |
| FastAPI docs | <http://127.0.0.1:18000/docs> |
| Odoo 19 | <http://127.0.0.1:18069> |
| n8n editor | <http://127.0.0.1:18082> |
| Mailpit inbox | <http://127.0.0.1:18025> |

The app login is an **explicit demo identity selector**; it is not production authentication. Choose a synthetic role in the login screen to explore the corresponding workflow. n8n uses a generated local owner account (<code>automation-admin@demo.local</code>); its password is in the ignored file <code>.local/n8n-owner-password</code>. Odoo bootstrap/admin credentials are kept in ignored files under <code>.local/</code>.

### n8n flows

- **Authenticated procurement intake**: <code>POST http://127.0.0.1:18082/webhook/purchaseflow/intake</code>. It validates and submits an idempotent request through the automation-only API surface.
- **Daily approval and ERP digest**: runs weekdays at 09:00 Asia/Shanghai, or on demand at <code>POST http://127.0.0.1:18082/webhook/purchaseflow/summary</code>. It calls the sanitized summary API and sends to synthetic manager/finance addresses; Mailpit captures the message and nothing is delivered externally.

Both webhooks require <code>Authorization: Bearer &lt;local automation token&gt;</code>. The token is in <code>.local/automation-token.txt</code>; the n8n credential is imported from a temporary ignored file and stored encrypted using the persistent <code>.local/n8n.env</code> encryption key. The token and SMTP settings are **not** embedded in workflow JSON. <code>scripts/verify-demo.ps1 -ExerciseN8nWorkflows</code> exercises intake idempotency and the local digest, creating one synthetic pending request and one Mailpit message.

## Verify and test

~~~powershell
pwsh ./scripts/verify-demo.ps1
pwsh ./scripts/verify-demo.ps1 -ExerciseN8nWorkflows
pwsh ./scripts/bootstrap-test-db.ps1
docker compose -p purchaseflow-demo -f docker-compose.yml --profile test run --rm tests
~~~

The first verify is read-only. The optional n8n exercise creates a synthetic request and local email.

For the browser acceptance test (Node.js 24):

~~~powershell
cd frontend
npm ci
npx playwright install chromium
npm run build
npm run e2e
~~~

The browser suite covers the normal Odoo handoff and distinct manager/finance approval; it also checks that a requester cannot approve through the API. For the response-loss recovery test, prepare the real Odoo `UNKNOWN` scenario first:

~~~powershell
pwsh ./scripts/run-erp-unknown-demo.ps1
~~~

The script creates a synthetic request through the API, pauses only this project's worker, writes one real Odoo draft, intentionally discards the successful create response, and restarts the worker. The procurement browser test then reconciles the same stable intent and closes the request. Run `npm run e2e` after the script to include that recovery flow. The script reuses an existing matching `UNKNOWN` record after an interrupted run, so rerunning it does not create another draft unnecessarily.

After a successful browser recovery, `pwsh ./scripts/verify-persistence.ps1` restarts only this project's services (without removing volumes) and rechecks the request, live Odoo draft, n8n workflows, and Mailpit messages.

`scripts/seed-demo.ps1` reruns the idempotent database migration and seed after startup. `scripts/reset-demo.ps1` removes only the PurchaseFlow project volumes after an explicit typed confirmation; it is not run by the normal stop command. The reset phrase and affected volumes are printed before confirmation.

GitHub Actions runs Python lint/type checks, Python and npm dependency audits, the isolated Postgres concurrency suite, the full Docker/Odoo/n8n/Mailpit bootstrap, static n8n JSON contracts, and browser acceptance. The manual [`controlled-purchaseflow-integration`](.github/workflows/controlled-purchaseflow-integration.yml) workflow also injects and recovers a lost Odoo create response, then restarts the services to verify persistence in an isolated runner.

## Stop safely

~~~powershell
pwsh ./scripts/stop-demo.ps1
~~~

This stops containers but **retains Postgres, Odoo filestore, n8n, and Mailpit volumes**. Starting again is non-destructive and reruns idempotent seeds. Local credentials are under <code>.local/</code>, which is Git-ignored. Keep <code>.local/n8n.env</code> and the named n8n volume together; without the encryption key, stored n8n credentials cannot be decrypted. All service ports bind to loopback (<code>127.0.0.1</code>), not the LAN.

## Architecture and evidence

- [Architecture](docs/ARCHITECTURE.md)
- [Business rules](docs/BUSINESS-RULES.md)
- [Workflow authority and failure states](docs/WORKFLOW-AUTHORITY.md)
- [Data contracts](docs/DATA-CONTRACTS.md)
- [Odoo integration and security boundary](docs/ODOO-INTEGRATION.md)
- [Local operations runbook](docs/RUNBOOK.md)
- [Security boundary](docs/SECURITY.md)
- [Test evidence and limitations](docs/TEST-EVIDENCE.md)
- [Portfolio narrative](docs/PORTFOLIO.md)
- [Interview pitch](docs/INTERVIEW-PITCH.md)
- [Recording and subtitles](docs/RECORDING.md)
- [Feishu adapter status and tenant setup](docs/FEISHU.md)
- [Versioned n8n workflows](n8n/workflows/)

Feishu is an optional extension and has not been connected to a real tenant; no live Feishu integration is claimed.
