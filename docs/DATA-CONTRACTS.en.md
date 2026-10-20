# Business field source, version, and verification contract

This document defines responsibility for persisted fields across the request API, approvals, background execution, and Odoo. An API request becomes a procurement fact only after validation completes and it is bound to a request version.

| Field | authoritative source / state | owner and version binding | validation / read-back | allowed use |
|---|---|---|---|---|
| requester_id | PurchaseFlow login identity, active | Auth service; bound to request version | token valid, membership exists | Audit and "my requests" filtering |
| department_id | PurchaseFlow department master data | Admin configuration; request submission snapshot | Requester's organization and department match | Manager approval routing |
| reason | Requester's submitted field | Requester can edit only in draft; frozen with request version | Non-empty, length limit, audit | Approval context |
| vendor_ref | Controlled mapping to Odoo res.partner | Admin mapping; mapping version stored in snapshot | Startup validates Odoo ID/vendor flag; reads again before writing | purchase.order.partner_id |
| product_ref | Controlled mapping to Odoo product.product | Admin mapping; stores Odoo ID, SKU, and mapping version | Odoo active, purchasable, company/currency applicable | purchase.order.line.product_id |
| quantity | Decimal string entered by requester | Requester draft; submission snapshot | Decimal, >0, precision compatible with UoM | Approval and order lines |
| unit_price | Controlled product price; requester may enter within an allowed range | Requester draft; snapshot records source | Decimal, non-negative, currency rounding; frozen after approval | Approval amount and price_unit |
| currency | Demo policy fixed to CNY | Admin demo company configuration; bound to request version | Compare with Odoo company currency and purchase.order.currency_id | No exchange-rate conversion |
| amount_untaxed | Calculated from line quantity, unit price, and Odoo tax rules | PurchaseFlow Decimal calculation; Odoo is the landed fact | Odoo read-back compared with local expectation within rounding tolerance | Display untaxed amount |
| amount_tax / amount_total | Odoo calculates from lines and supplier taxes | Odoo owns tax and tax-inclusive amounts; synchronized snapshot records tax-rule version | JSON-2 read-back fields; verify tax and tax-inclusive total | Finance approval explanation, verification |
| approval_policy_version | PurchaseFlow current demo rules | Admin publishes version; bound at request submission | Revalidate that the version is unchanged at approval time | Explain approval path |
| erp_intent_id | PurchaseFlow UUID | Created once by Worker after approval; unique constraint | Odoo purchaseflow_intent_id unique; re-read matches | Remote lookup, UNKNOWN recovery, duplicate prevention |
| odoo_order_id / odoo_order_name | Odoo purchase.order | Saved only by Verifier from read-back | Search_read/read again to verify ID, source marker, and order number | Display real ERP reference |
| erp_disposition | Verifier's current observation | Verifier saves observation time, request identity, and version | VERIFIED/ABSENT/MISMATCH/UNAVAILABLE/UNKNOWN; must not be conflated with success/failure | Business-state advancement and human handoff |
| audit_actor_id / event | Server-authenticated identity and business action | Audit service appends | Every approval, mapping change, ERP call, and recovery leaves a record | Accountability and reproduction; never accept client-forged values |

## Numerical conventions

- All request amounts use Decimal, never binary floating point.
- Demo-policy approval uses the CNY subtotal of quantity × unit price; if supplier tax is configured, approval routing must use the estimated tax-inclusive amount. Frontend and backend consistently use the amount calculated from Odoo's actual tax-rule read-back.
- The UI distinguishes untaxed amount, tax amount, and tax-inclusive total. Demo seed uses fixed, explicit tax rates and does not rely on database default taxes or fixed record IDs.
- Odoo read-back is the current remote fact; the PurchaseFlow approval snapshot is the approved intent. If either does not match, the case must not advance to synchronized.
