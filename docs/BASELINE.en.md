# Development baseline

Recorded: 2026-10-10 (Asia/Shanghai)

## Workspace and isolation

- Project: an independent PurchaseFlow workspace, initially on branch main with no commits and no source files.
- No remote was configured. The suggested GitHub name xiongweilin/PurchaseFlow returned 404 at the start of the inspection; access will be checked again before pushing.
- No existing purchaseflow containers, volumes, or networks were found. PurchaseFlow does not connect to ReturnOps-Mini, AIOS, commerce-orchestrator, or personal infrastructure.
- ReturnOps-Mini and AIOS services exist in Docker. Their containers, networks, volumes, and data are not managed by this project; this task does not stop, modify, or clean those resources.
- A local listening-port check found no host processes on 5432, 5678, 8025, 8069, 8072, 8000, 4173, 8090, 18069, 18072. AIOS uses 18080, 18083, 18086, 18100, 18110, 19090; ReturnFlow uses 25432, 28000, 28025, 28090, 28417, 28567.
- PurchaseFlow Odoo binds only to 127.0.0.1:18069; PostgreSQL publishes no host port. Odoo / PostgreSQL containers, volumes, and networks use the purchaseflow-demo name.
- Odoo/PostgreSQL use independent databases and roles. The Odoo database is owned by the non-superuser, NOCREATEDB role purchaseflow_odoo; the PostgreSQL admin role is used only for project bootstrap.

## Tool versions (measured on this machine)

| Tool | Version/result |
|---|---|
| PowerShell | 7.6.4 |
| Git | 2.56.0.windows.1 |
| Python | 3.14.8 |
| Node.js | v24.14.0 |
| Docker CLI / Engine | 29.7.2 / 29.7.2 |

Current CI and container development target Python 3.12; the local Python 3.14 is auxiliary only and does not replace CI's target runtime.

## Odoo 19 site

- Official Community image: odoo:19.0-20260926, RepoDigest sha256:dd9013e669caaa23d26765dc55814655eaeecca7cfc2c265dbabae913bce22fd.
- Independent PostgreSQL image: postgres:17.6-alpine, RepoDigest sha256:ef257d85f76e48da1c64832459b59fcaba1a4dac97bf5d7450c77753542eee94.
- In database purchaseflow_odoo, base, account, purchase, and purchaseflow_link are all installed; company, CNY, vendor, products, and tax rules were written through Odoo models.
- The Odoo login page returns HTTP 200; unauthenticated JSON-2 returns HTTP 401; a real permission-limited account completed purchase-order creation and independent read-back. Evidence is in docs/TEST-EVIDENCE.md.
- Odoo 19 model constraints use models.Constraint; at runtime it was found that old-style _sql_constraints no longer take effect in 19.0, so the official constraint API was used and the unique constraint was read back from PostgreSQL.
- For the external JSON-2 API format and plan limitations, see the official Odoo 19 documentation. The official documentation describes hosted-plan limitations; this machine's self-hosted Community was verified in practice, and the conclusion is not generalized to another deployment mode.

## Reference implementations and reuse boundaries

- ReturnOps-Mini: learned PostgreSQL idempotency keys, Outbox leases, server-side role/organization authorization, audit events, demo sessions, and health-check patterns. PurchaseFlow independently implements only the required behavior and does not import ReturnOps packages or runtime services.
- AIOS: learned to separate draft preparation from confirmation/payment and to distinguish unavailable, unknown, missing, mismatched, and successfully verified outcomes; its monorepo and runtime were not adopted.
- commerce-orchestrator: learned Odoo 19 JSON-2 requests, unknown-outcome classification, read-back, and concurrent approval patterns; DBOS was not adopted.
- agent-skills: used workflow-owner and field source/allowed-use contracts to guide this document; the skill library was not copied.
- Reference repositories are all MIT licensed; only design experience was reused, and no files or code were copied. If code is copied later, license notices will be retained and provenance recorded.

## Official interface references

- JSON-2 API: https://www.odoo.com/documentation/19.0/developer/reference/external_api.html
- Odoo CLI: https://www.odoo.com/documentation/19.0/developer/reference/cli.html
- Odoo ORM / constraints: https://www.odoo.com/documentation/19.0/developer/reference/backend/orm.html
- Official Odoo Docker source: https://github.com/odoo/docker/tree/master/19.0

## Baseline note

This document records the environment and repository state at project start and does not represent the final delivery state. The final implementation, acceptance runs, limitations, and unverified items are governed by [`TEST-EVIDENCE.en.md`](TEST-EVIDENCE.en.md). No authorized credentials were available for a real Feishu tenant, so it remains `NOT VERIFIED` and does not affect the scope of the local procurement and Odoo main flow.
