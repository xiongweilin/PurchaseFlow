# Procurement demo rules

- Up to 5,000 CNY: department manager approval.
- Above 5,000 CNY and up to 20,000 CNY: department manager approval, then review by a different finance user.
- Above 20,000 CNY: enters manual policy review and is not automatically written to Odoo.
- A request must include requester, department, reason, controlled supplier, 1–3 purchase lines, product, quantity, unit price, and currency.
- The demo allows CNY only. Amounts use Decimal.
- After submission, department, supplier, product, quantity, price, currency, and reason are frozen; changes require a new version and new approvals.
- A draft purchase order is prepared only after all approvals pass, the mapping is valid, and Odoo is reachable.
- The actual purchase draft after writing must be read back independently; the case cannot be closed before verification passes.
- Rejection, cancellation, policy review, UNKNOWN, and MISMATCH never automatically become Odoo-synchronized.
- These amounts are Demo Policy and do not constitute a real company's financial approval system.
