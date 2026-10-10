# Security boundaries and demo limitations

## Local-only by design

- Compose publishes the app, API, Odoo, n8n, and Mailpit on 127.0.0.1 only. Postgres has no host port.
- Mailpit is the only SMTP destination. No real email provider or external relay is configured.
- Odoo API key, PostgreSQL passwords, the automation token, n8n encryption key, owner password, and temporary import files live under .local/, which is Git-ignored.
- The Odoo API key is mounted as a read-only secret file into the API/worker; the Odoo web service does not mount the host `.local` directory. The seed handoff is captured in PowerShell memory and never echoed to logs. The key is not present in source, workflow JSON, response payloads, or this documentation.
- On Unix, the app seed container runs with the invoking host UID/GID when it writes the local automation token, keeping its mode-0600 file readable to the host provisioner without making it world-readable.
- n8n workflow JSON contains only credential references. A temporary local credential JSON is imported into n8n and deleted; n8n persists the credential encrypted with N8N_ENCRYPTION_KEY.
- The n8n owner password hash is mounted from a local file. Keep the hash file, plaintext password file, encryption-key file, and persistent database under local access control.
- Separate Postgres roles/databases restrict app, Odoo, n8n, and test data.

## Identity and approval controls

The app's role picker intentionally bypasses normal authentication for a local demo. It is visible and documented as a demo identity selector. It is **not** suitable for production or a network-accessible shared environment. Domain actions still enforce role, department, separation of duties for finance approval, version checks, and state transitions.

The automation token is a scoped service credential with the automation role and is allowed only on integration endpoints. n8n summary output is deliberately minimized. Admin/finance/procurement views have additional ERP detail; the requester/manager view does not receive the raw Odoo API key or internal credential data.

## Operational limitations

- No TLS, SSO, external identity provider, secrets manager, production backup/restore workflow, or multi-tenant isolation is claimed.
- The Compose Odoo user and API key are synthetic and least-privileged for the demo, not a substitute for production IAM review.
- Use local synthetic data only. Do not put real employee, supplier, bank, or contract data into the demo.
- Keep all ports loopback-only. Do not expose n8n; it is a workflow editor with privileged service credentials.
- The system creates and verifies draft purchase orders only. It does not confirm POs, receive goods, post bills, or make payments.
