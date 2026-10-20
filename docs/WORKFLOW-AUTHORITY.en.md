# Procurement process participants and permissions

## Flow diagram

~~~mermaid
stateDiagram-v2
  [*] --> draft
  draft --> pending_manager: requester submits and business fields are frozen
  draft --> cancelled: requester cancels
  pending_manager --> rejected: department manager rejects
  pending_manager --> pending_finance: amount > 5,000 CNY and manager approves
  pending_manager --> approved: amount <= 5,000 CNY and manager approves
  pending_finance --> rejected: finance rejects
  pending_finance --> approved: a different finance user approves
  pending_manager --> policy_review: amount > 20,000 CNY
  pending_finance --> policy_review: amount > 20,000 CNY
  approved --> erp_pending: system persists the ERP intent for the approved version
  erp_pending --> erp_unknown: Odoo request outcome is ambiguous
  erp_pending --> erp_verified: independent read-back after Odoo write matches
  erp_pending --> erp_mismatch: read-back facts do not match
  erp_unknown --> erp_verified: manual query matches
  erp_unknown --> erp_mismatch: query finds a mismatch
  erp_unknown --> erp_pending: verified absent, then redispatch the same intent
  erp_mismatch --> erp_verified: after procurement admin correction/verification
  erp_verified --> closed: procurement admin closes
~~~

## Participants and responsibilities

| Participant | Can do | Cannot do | transition owner / evidence |
|---|---|---|---|
| Requester | Create/edit drafts, submit, cancel unapproved requests | Approve their own request; change approved fields after submission | Backend verifies owning user; saves business snapshot and version at submission |
| Manager | Approve pending requests in their department | Approve their own request; approve another department | Backend checks department scope, role, request version, and pending state; decision writes audit |
| Finance | Review high-value requests, view amounts and ERP state | Review as the same person who approved at department level; directly change procurement content | Backend checks amount stage, different user, and version; decision writes audit |
| Procurement | View approved requests, handle ERP exceptions, confirm verified documents and close | Close before verification; bypass approval to create orders | Manual handling is audited; closing requires erp_verified |
| Admin | Manage demo users, rules, and mappings | Bypass amount/four-eyes/approval-freeze gates | Rule changes are versioned and audited; does not own ERP writes |
| Automation / n8n | Submit requests as a service identity, read summaries | Approve, directly operate the database or Odoo | API accepts only restricted input; server validates token and fields |
| Worker | Consume approved ERP intents, call Odoo to create drafts, read back | Approve on its own, confirm purchase orders, pay | Processes only unique intents that are approved in the database and version-matched; only a Worker with the current unexpired lease generation may submit results |
| Verifier | Classify based on independent Odoo read-back evidence | Use write-request HTTP 200 instead of read-back | Marks erp_verified only after all key fields match |

## Key external boundaries

- purchase.order/create is the only Odoo purchase write method; no code path may call button_confirm, receipt, bill posting, or payment interfaces.
- The creation intent is persisted before the call. Request timeout, connection interruption, or unparseable response enters erp_unknown; a second intent is never created automatically.
- Recovery queries Odoo by the stable purchaseflow_intent_id. If read-back exists, verify it; if the authoritative query is unavailable, remain unknown; after confirming absence, only the same stable identifier may be retried.
- Odoo's written draft state, the request snapshot, API facts, and manual closing are separate evidence and states.
- Every Outbox claim increments `lease_generation`. A Worker may save the ERP intent, request state, and read-back observation in the same transaction only while the event is still `processing`, the generation still matches, and the lease is unexpired; late results from expired executions are discarded. The unique constraint on the stable Odoo intent still prevents duplicate purchase drafts.

## Approval state rules

- A requester cannot approve their own request.
- amount_total > 5000.00 CNY requires department-manager approval first, then review by a different finance user.
- amount_total > 20000.00 CNY moves to manual policy review and does not automatically create an Odoo order.
- Every approval must submit the version under review; business fields are frozen. A version conflict or concurrent duplicate decision does not produce a second approval result.
- Rejection or cancellation terminates automation and creates no ERP Effect.

## Retry and manual recovery

- Safe retry is determined by an explicit not-executed result (for example, a deterministic Odoo 4xx error), not inferred from generic network exceptions.
- When an external call outcome is unknown, only read-only queries are allowed. An unavailable query remains unknown and creates no new ERP intent.
- After confirming that Odoo has no record, Procurement may explicitly recover the original ERP Effect. The remote unique constraint and stable source marker prevent duplicates.
- Verification failure is erp_mismatch, retaining the expected snapshot and remote read-back for manual investigation; it must not be marked successful or closed.
