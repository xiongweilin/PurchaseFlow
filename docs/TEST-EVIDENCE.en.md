# Test evidence and environment boundaries

Recorded: 2026-10-11 (Asia/Shanghai). Results come from the local isolated demo stack and fresh GitHub Actions runners; this document records only observed acceptance, not production deployment.

## Real Odoo 19 Community

| Check | Site result |
|---|---|
| Official Odoo image | `odoo:19.0-20260926`; RepoDigest `sha256:dd9013e669caaa23d26765dc55814655eaeecca7cfc2c265dbabae913bce22fd` |
| Independent PostgreSQL image | `postgres:17.6-alpine`; RepoDigest `sha256:ef257d85f76e48da1c64832459b59fcaba1a4dac97bf5d7450c77753542eee94` |
| Database isolation | Database `purchaseflow_odoo` inside the private `purchaseflow-demo` Compose cluster; least-privilege role `purchaseflow_odoo` is non-superuser and `NOCREATEDB`; PostgreSQL publishes no host port |
| Odoo installation | Odoo reports version `19.0-20260926`; `base`, `account`, `purchase`, and `purchaseflow_link` are all installed |
| Remote idempotency constraint | The PostgreSQL unique constraint on `purchase.order.purchaseflow_intent_id` was read back from `pg_constraint` |
| Network binding | Odoo binds only to `127.0.0.1:18069`; PostgreSQL is accessible only inside the project network |
| Demo data | `Demo Office Ltd.`, CNY, vendor, products, UoM, and tax rules are all looked up by business key from the current Odoo database, not hard-coded remote IDs |
| Authentication boundary | Odoo login page HTTP 200; JSON-2 request without bearer HTTP 401; integration account reading protected `ir.config_parameter` returns HTTP 403 |
| Real draft and independent read-back | Deterministic acceptance intent `PF-STAGE1-ODOO-JSON2` currently maps to real draft `P00029`; a new `search_read/read` verifies company, supplier, intent marker, lines, quantity, tax rate, amounts, and `state=draft` |
| Amount convention | 1 × untaxed unit price CNY 1,200.00; 13% tax CNY 156.00; tax-inclusive total CNY 1,356.00 |
| Replay duplicate prevention | A second create for the same `purchaseflow_intent_id` returns HTTP 422; authoritative `search_read` still shows only one draft |
| Response loss and UNKNOWN recovery | The controlled script actually creates the Odoo draft, then discards the success response; the application records `erp_unknown` with 1 dispatch. The procurement UI performs a read-only verification by the same intent and closes the case without creating again |
| Secret bootstrap boundary | The Odoo container stages the new API key in its own filestore volume; PowerShell captures the one-time value without echoing it to logs and writes Git-ignored `.local/odoo-api-key` (Linux mode 0600); the Odoo web service does not mount the entire `.local` |
| Odoo order restart idempotency | After PostgreSQL and Odoo restart, `PF-STAGE1-ODOO-JSON2` still reads back the same draft `P00029`; duplicate create returns HTTP 422, and the query still shows only one draft for that stable intent |
| Application full-stack restart persistence | After restarting PurchaseFlow PostgreSQL, Odoo, API, worker, frontend, n8n, and Mailpit, `PR-202610-96BDCA11` still maps to Odoo draft `P00027`; a fresh Odoo read-back matches the persisted approval snapshot. Application requests, n8n workflows, and Mailpit email were also preserved |

The site verified self-hosted Odoo 19 Community and does not infer API licensing for Odoo Online or other hosted plans. All purchase orders remain drafts; the flow never confirms purchases, receives goods, posts, or pays.

## Local automation and frontend acceptance

| Check | Result |
|---|---|
| Python static quality | Ruff passed; mypy reported no issues across 20 Python source files |
| Python unit tests | 26 passed, 1 skipped locally; the only skip is the PostgreSQL concurrency test requiring `DATABASE_URL_TEST` |
| Isolated PostgreSQL container tests | 27 passed in a Python 3.12 container against an independent `purchaseflow_test` database (including concurrency idempotency tests); only a Starlette `TestClient` deprecation notice |
| Python dependency audit | `pip-audit`: No known vulnerabilities found |
| Frontend dependency audit | `npm audit --registry=https://registry.npmjs.org/ --audit-level=moderate`: 0 vulnerabilities |
| Frontend build | TypeScript checks and Vite production build passed |
| Browser E2E | 3 passed: requester → department manager → Odoo draft, different finance user reviewing a high-value request, and manual verification after real Odoo response loss; also verifies that the requester cannot self-approve through the API |
| n8n / API | Webhook unauthenticated returns 403, invalid payload returns 422, same-event replay returns the same request, same ID with different content returns 409; daily digest email arrives in local Mailpit |
| Service persistence | `scripts/verify-persistence.ps1` restarts project services without deleting volumes; API, workflows, email, and Odoo external-order read-back all pass |
| Feishu offline adapter | 7 synthetic unit tests cover URL challenge, Verification Token, v2.0 event ID, field mapping, stable idempotency key, and signature freshness; no tenant is connected |
| Demo recording | `docs/assets/purchaseflow-demo.mp4` is 4:32.96 long; 12 Chinese subtitle entries cover through the end, and screenshots/video come from the real local UI |

`npm audit` uses the official npm registry because the mirror configured in this environment does not implement the advisory bulk endpoint. Container tests run against an independent `_test` database; the fixture refuses to create/drop tables in a database whose name does not end in `_test`.

## CI and reproducible delivery

GitHub Actions automated CI installs dependencies on a fresh runner, starts isolated Docker/Odoo/n8n/Mailpit, runs PostgreSQL concurrency tests, static workflow contracts, and browser acceptance. The manual `controlled-purchaseflow-integration` workflow additionally injects real Odoo response loss, performs UNKNOWN browser recovery, and then restarts services to verify persistence.

Initial source commit `ce25b1bba31655e555ad390a75c1252caa7f6b78` passed automated CI and controlled end-to-end acceptance on a fresh GitHub runner: [PurchaseFlow CI #38067068398](https://github.com/xiongweilin/PurchaseFlow/actions/runs/38067068398); [controlled-purchaseflow-integration #38067080112](https://github.com/xiongweilin/PurchaseFlow/actions/runs/38067080112). Controlled acceptance included real Odoo response loss, UNKNOWN manual verification, three browser flows, and a persistence check after service restart. Early clean-run attempts found and fixed bootstrap ordering, Linux secret-file ownership, and webhook registration timing issues; the links above are the all-green results after the fixes.

## Worker lease fencing, real Odoo mismatch, and PR delivery

Source acceptance commit `ea26985665dff2b0f603fd7f1bf21aecdb804973` added the Outbox `lease_generation` migration and a write fence for invalidated Workers. The PostgreSQL concurrency test blocks Worker A in a slow read-back, lets the lease expire, has Worker B take over and verify the same Odoo order, then lets A return a mismatched read-back; the final intent remains `VERIFIED`, the request remains `erp_verified`, the Outbox remains `done` with generation 2: the PostgreSQL concurrency test and full `acceptance` checks in [PR CI #38102500592](https://github.com/xiongweilin/PurchaseFlow/actions/runs/38102500592) passed.

The controlled runner uses a newly created synthetic request and real Odoo 19 draft, changing the order-line unit price from CNY 1,200.00 to CNY 1,201.00. PurchaseFlow's independent read-back must enter `erp_mismatch`, save and display the approval snapshot versus Odoo's actual line price/amount difference on the procurement detail page; the workbench offers no closing action, and a direct close request returns HTTP 409. The script then restores the same Odoo draft to the original price, and the new read-back becomes `erp_verified` with the same order ID and number: [controlled-purchaseflow-integration #38102503416](https://github.com/xiongweilin/PurchaseFlow/actions/runs/38102503416). Browser difference display, closing interception, recovery, and persistence after service restart all passed.

PR delivery record: [PurchaseFlow PR #1](https://github.com/xiongweilin/PurchaseFlow/pull/1). `main` has branch protection requiring a Pull Request, a passing `acceptance` check, an up-to-date branch, and is enabled for administrators; the current required approval count is 0 so a single maintainer can still merge through a PR.

## Unverified items and data boundaries

- Feishu provided no authorized tenant, application credentials, or callback address, so no callback is registered and no API is called. `backend/app/feishu_adapter.py` only provides an offline-testable v2.0 event validation and tenant-field mapping boundary; signature/decryption and real field extraction still require tenant acceptance. See [Feishu adapter status](FEISHU.md).
- PurchaseFlow login is an explicit demo identity selector, not production SSO/MFA. Demo roles, approval thresholds, and amounts are all synthetic.
- No payment, supplier email, external Feishu tenant, or production Odoo is connected. SMTP goes only to local Mailpit.
- `scripts/reset-demo.ps1` requires an exact confirmation phrase; local acceptance did not run the reset script or delete local service volumes.
- Other projects in local Docker (including ReturnOps-Mini and AIOS) are outside this repository's Compose scope; local start, restart, stop, and persistence acceptance all use the `purchaseflow-demo` project and perform no operations on them.
