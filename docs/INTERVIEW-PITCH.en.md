# Interview pitch

## About 90-second version

This project solves the problem of small and medium-sized businesses' procurement process being scattered across chat, spreadsheets, and ERP: requesters do not know who is approving, approvers lack a single amount convention, and procurement staff struggle to confirm whether ERP actually received the approved content.

I separated peripheral automation from business decisions into two n8n workflows. The first receives procurement-request events, validates fields, creates a request through a restricted API, and uses the event ID for idempotency. The second generates a weekday approval and ERP-exception digest from business API data; email goes only to local Mailpit. n8n does not approve and does not write to Odoo directly.

A request must be approved by the department manager; above the demo threshold, a different finance user must also review it. After submission, supplier, product, quantity, and price are frozen. Only after all approvals complete does the background process create a draft purchase order in Odoo from the saved approval version, then independently read it back to verify supplier, lines, currency, and draft state.

The key exception is "the request timed out, but Odoo may already have created the order." The system records this as UNKNOWN and pauses automatic creation; procurement queries Odoo by the stable intent, sees the real document, and then resumes verification, avoiding a blind second order. The entire demo uses isolated Odoo 19, PostgreSQL, n8n, and Mailpit environments and never confirms purchase orders or makes payments.

## Follow-up detail

### Why two n8n workflows?

Intake and to-do digest are two different trigger points: one responds to external events and creates requests, the other periodically tells a role "what needs handling now." Both access the business through the API, do not share database write permission, and do not replace human approval.

### Which steps remain human?

The department manager judges business necessity; high-value requests are reviewed by another finance user; requests beyond the demo policy are first recorded as an administrator exception, then go through the full approval; procurement handles unknown or mismatched ERP outcomes and final closing. The system constrains roles and states; hiding a button cannot replace server-side authorization.

### Why not retry directly on timeout?

A timeout only means the caller did not receive a definitive response; it does not prove Odoo did not commit. The system therefore queries Odoo first by the same ERP intent identifier. If found and matching, it resumes as verified; only when confirmed absent may procurement explicitly retry the original intent; when the query is unavailable, the state remains unknown.

### How do you describe the verified scope?

You can show the real Odoo 19 JSON-2 write and read-back, PostgreSQL concurrency tests, browser approval flow, n8n webhook and Mailpit email, and controlled response-loss recovery in `docs/TEST-EVIDENCE.en.md`. Real enterprise saved hours, lower error rates, and Feishu tenant onboarding have not been measured or verified, so no such claims are made.
