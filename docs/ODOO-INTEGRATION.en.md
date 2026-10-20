# Odoo 19 Community integration

## Verified site

This project uses an independently deployed official Odoo Community image, odoo:19.0-20260926, and a dedicated PostgreSQL database, purchaseflow_odoo. Docker image RepoDigest, actual modules, HTTP, and JSON-2 results appear in docs/TEST-EVIDENCE.md.

The official Odoo 19 JSON-2 request uses POST /json/2/<model>/<method>, Authorization: bearer <API_KEY>, and Content-Type: application/json; fields come only from the running database's `/doc` model methods and that database's fields_get. The site obtains CNY, vendor, product, UoM, and tax IDs through dynamic queries.

## Permissions and credentials

- purchaseflow.integration is an independent internal user, added only to base.group_user and purchase.group_purchase_user.
- The current user can access only the Demo Office Ltd. company.
- The API key scope is Odoo's default RPC scope, expiring in 30 days; model access remains limited by that user's Odoo ACLs, record rules, and company context.
- The API key is stored in Git-ignored .local/odoo-api-key; it never enters code, logs, n8n workflow JSON, or documentation.
- The Odoo seed temporarily stages the new key in Odoo's own filestore volume; PowerShell bootstrap captures the one-time return value in memory and writes it to local `.local`, without echoing the marker. The Odoo web service does not mount the entire `.local`; the API/worker reads it only through a read-only secret-file path.
- Unauthenticated JSON-2 requests receive HTTP 401; a permission-limited user reading ir.config_parameter receives HTTP 403.

## Stable intent and write verification

After local approval, every ERP intent has a stable unique purchaseflow_intent_id. Odoo purchase.order uses a minimal purchaseflow_link extension field, and a real PostgreSQL unique constraint enforces at most one purchase order per intent.

The PurchaseFlow Worker consumes only the ERP Intent/Outbox persisted in the same database transaction after approval. Each dispatch uses the stable `purchaseflow_intent_id`: it first queries Odoo by that marker, then creates a `purchase.order` draft, and finally reads it back through a new JSON-2 `search_read`. Supplier, company, currency, intent marker, product lines, quantity, UoM, untaxed unit price, tax convention, and `draft` state must all match before entering `erp_verified`.

A request timeout or a read-back failure after creation remains `erp_unknown`; this state never automatically initiates another creation. Procurement can run a read-only verification from the operations console, confirm the remote record exists, match the same intent, and restore state. Only after explicitly confirming that no record exists may procurement explicitly retry the original intent. `scripts/run-erp-unknown-demo.ps1` pauses this project's worker, creates a draft through real JSON-2 in Odoo, then intentionally discards the success response; procurement then reads it back, verifies, and closes it from the procurement workbench. Real field results and execution evidence appear in `docs/TEST-EVIDENCE.md`.

If independent read-back finds that supplier, amount, or purchase lines differ from the approval snapshot, it retains the `expected` and Odoo `actual` values and enters `erp_mismatch`. This state offers no closing action. `scripts/run-erp-mismatch-demo.ps1` modifies a just-created Odoo draft line price in the isolated acceptance environment, verifies that the UI/API shows the difference and refuses closing, then restores the original price and re-verifies the same draft.

## Demo tax convention

The company currency is fixed to CNY with no exchange-rate conversion. Seed products use a 13% purchase tax and services use a 6% purchase tax, both at untaxed prices. PurchaseFlow approval and amount display must separate untaxed amount, tax amount, and tax-inclusive total, and explain the approval-amount convention used by the policy.
