# Local operations runbook

## Prerequisites

- Docker Desktop with Docker Compose v2.
- PowerShell 7 (pwsh).
- First run needs network access for pinned images and package downloads.
- All published ports are bound to loopback; do not change them to 0.0.0.0 for a shared machine.

## Start and verify

~~~powershell
pwsh ./scripts/start-demo.ps1
pwsh ./scripts/verify-demo.ps1
~~~

Start bootstraps Odoo, creates the app/n8n database roles, runs the API migrations and idempotent seed, builds the app images, provisions encrypted n8n credentials/workflows, and waits for health checks. The first Odoo module install can take several minutes.

| Component | URL |
|---|---|
| PurchaseFlow | http://127.0.0.1:18081 |
| FastAPI docs | http://127.0.0.1:18000/docs |
| Odoo 19 | http://127.0.0.1:18069 |
| n8n editor | http://127.0.0.1:18082 |
| Mailpit | http://127.0.0.1:18025 |

Choose a synthetic app role on the PurchaseFlow login screen. n8n owner email is automation-admin@demo.local; the generated password is in .local/n8n-owner-password. Odoo admin credentials are only in .local/odoo.env.

The normal verify is read-only. This optional exercise creates one pending synthetic request and delivers one local digest email:

~~~powershell
pwsh ./scripts/verify-demo.ps1 -ExerciseN8nWorkflows
~~~

Rerun the idempotent migration and seed after startup with `pwsh ./scripts/seed-demo.ps1`.

To show the real-Odoo response-loss recovery, run:

~~~powershell
pwsh ./scripts/run-erp-unknown-demo.ps1
~~~

This pauses only the PurchaseFlow worker while the requester submits and the department manager approves a synthetic request. A one-shot worker call creates a real Odoo draft, drops the create response, and verifies the stored state is `erp_unknown` with one attempt. The worker restarts in `finally`; open the request as procurement and select **只读核验** to recover it.

## Tests

~~~powershell
pwsh ./scripts/bootstrap-test-db.ps1
docker compose -p purchaseflow-demo -f docker-compose.yml --profile test run --rm tests
~~~

The Postgres integration fixture refuses to create/drop tables unless the configured database name ends in _test.

~~~powershell
cd frontend
npm ci
npx playwright install chromium
npm run build
npm run e2e
~~~

The browser tests cover requester -> manager -> Odoo draft verification, high-value distinct-approver review, and a requester API authorization check. If `.local/unknown-demo.json` exists from the response-loss script, they also reconcile the existing Odoo order in the procurement worklist and close it.

After the browser recovery succeeds, verify data survives an ordinary service restart:

~~~powershell
pwsh ./scripts/verify-persistence.ps1
~~~

This restarts only the `purchaseflow-demo` containers, never removes a volume, and confirms the same application request and Odoo draft by stable intent ID. It also checks that the imported n8n workflows and Mailpit messages remain available. On failure, it attempts to bring this same service stack back up.

## Stop and persistence

~~~powershell
pwsh ./scripts/stop-demo.ps1
~~~

This stops the containers and keeps named volumes. It does not erase requests, Odoo drafts, n8n workflows/credentials, or Mailpit messages. Start again with scripts/start-demo.ps1; seed routines are idempotent.

The n8n encryption key is stored in .local/n8n.env and must stay paired with the persistent n8n database/volume. Losing it makes stored credentials unreadable. The n8n service credential is encrypted at rest by n8n; the temporary import JSON is deleted after provisioning.

## Troubleshooting

- **Port already in use:** stop the other local process or edit the host-side loopback port consistently in Compose, scripts, and Vite/Playwright config.
- **Docker is stopped:** start Docker Desktop, then rerun scripts/start-demo.ps1.
- **Service is unhealthy:** inspect docker compose -p purchaseflow-demo -f docker-compose.yml ps and docker compose -p purchaseflow-demo -f docker-compose.yml logs --tail 120 SERVICE.
- **n8n cannot decrypt a credential:** do not rotate .local/n8n.env casually. Restore the matching key or local database/volume pair.
- **Local data should be reset:** `scripts/reset-demo.ps1` prints the PurchaseFlow-only volume scope and requires the exact confirmation phrase `RESET PURCHASEFLOW DEMO DATA`. It removes that Compose project's named volumes, retains the ignored `.local/` configuration, and never targets other Compose projects. `scripts/stop-demo.ps1` remains non-destructive.
