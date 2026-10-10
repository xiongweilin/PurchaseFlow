from __future__ import annotations

import json
import os
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = os.environ.get("ODOO_BASE_URL", "http://127.0.0.1:8069").rstrip("/")
API_KEY_FILE = Path(os.environ.get("ODOO_API_KEY_FILE", "/run/purchaseflow-local/odoo-api-key"))
MANIFEST_FILE = Path(
    os.environ.get("ODOO_SEED_MANIFEST_FILE", "/run/purchaseflow-local/odoo-seed-manifest.json")
)
RESULT_FILE = Path(os.environ.get("ODOO_JSON2_RESULT_FILE", "/tmp/odoo-json2-acceptance.json"))
CENT = Decimal("0.01")


class Json2Error(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


def post(model: str, method: str, payload: dict, *, authenticated: bool = True):
    headers = {"Content-Type": "application/json", "User-Agent": "PurchaseFlow acceptance"}
    if authenticated:
        headers["Authorization"] = f"bearer {api_key}"
    request = Request(
        f"{BASE_URL}/json/2/{model}/{method}",
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read()
            return json.loads(raw) if raw else None
    except HTTPError as error:
        try:
            body = json.loads(error.read())
            message = str(body.get("message", "Odoo API error"))[:300]
        except Exception:
            message = "Odoo API error"
        raise Json2Error(error.code, message) from None
    except URLError as error:
        raise RuntimeError(f"Odoo JSON-2 transport failed: {type(error.reason).__name__}") from None


if not API_KEY_FILE.is_file():
    raise RuntimeError("Odoo integration API key file is missing.")
api_key = API_KEY_FILE.read_text(encoding="ascii").strip()
if not api_key:
    raise RuntimeError("Odoo integration API key file is empty.")
manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))

try:
    post(
        "res.partner",
        "search_read",
        {"domain": [], "fields": ["id"], "limit": 1},
        authenticated=False,
    )
    raise AssertionError("Unauthenticated JSON-2 request was accepted.")
except Json2Error as error:
    if error.status != 401:
        raise
    unauthenticated_status = error.status

vendors = post(
    "res.partner",
    "search_read",
    {
        "domain": [["ref", "in", list(manifest["vendors"])]],
        "fields": ["id", "name", "ref", "supplier_rank", "company_type"],
        "limit": 20,
    },
)
vendor_by_ref = {row["ref"]: row for row in vendors}
if set(vendor_by_ref) != set(manifest["vendors"]):
    raise AssertionError("Odoo did not return the seeded supplier master records.")
vendor = vendor_by_ref["PF-VENDOR-OFFICE"]
if vendor["supplier_rank"] < 1:
    raise AssertionError("The selected Odoo partner is not marked as a supplier.")

product_skus = list(manifest["products"])
products = post(
    "product.product",
    "search_read",
    {
        "domain": [["default_code", "in", product_skus]],
        "fields": ["id", "name", "default_code", "uom_id", "purchase_ok", "active"],
        "limit": 20,
    },
)
product_by_sku = {row["default_code"]: row for row in products}
if set(product_by_sku) != set(product_skus):
    raise AssertionError("Odoo did not return the seeded purchasable products.")
product = product_by_sku["PF-OFFICE-SET"]
if not product["active"] or not product["purchase_ok"]:
    raise AssertionError("The selected Odoo product is not active and purchasable.")

try:
    post(
        "ir.config_parameter",
        "search_read",
        {"domain": [], "fields": ["id", "key"], "limit": 1},
    )
    raise AssertionError("The integration user unexpectedly read system configuration.")
except Json2Error as error:
    if error.status not in {403, 404}:
        raise
    protected_model_status = error.status

try:
    previous_result = json.loads(RESULT_FILE.read_text(encoding="utf-8"))
except FileNotFoundError:
    previous_result = {}
intent_id = previous_result.get("intent_id", "PF-STAGE1-ODOO-JSON2")
tax = manifest["taxes"]["PF-CN-PURCHASE-13"]
product_master = manifest["products"]["PF-OFFICE-SET"]
quantity = Decimal("1")
unit_price = Decimal("1200.00")
tax_rate = Decimal(str(tax["rate_percent"]))
expected_untaxed = (quantity * unit_price).quantize(CENT, rounding=ROUND_HALF_UP)
expected_tax = (expected_untaxed * tax_rate / Decimal("100")).quantize(CENT, rounding=ROUND_HALF_UP)
expected_total = expected_untaxed + expected_tax
create_values = {
    "partner_id": int(vendor["id"]),
    "company_id": int(manifest["company"]["id"]),
    "currency_id": int(manifest["company"]["currency_id"]),
    "origin": intent_id,
    "purchaseflow_intent_id": intent_id,
    "order_line": [[
        0,
        0,
        {
            "product_id": int(product["id"]),
            "product_qty": float(quantity),
            "product_uom_id": int(product["uom_id"][0]),
            "price_unit": float(unit_price),
            "tax_ids": [[6, 0, [int(tax["id"])]]],
        },
    ]],
}
existing_before = post(
    "purchase.order",
    "search_read",
    {
        "domain": [["purchaseflow_intent_id", "=", intent_id]],
        "fields": ["id", "state"],
        "limit": 5,
    },
)
if len(existing_before) > 1:
    raise AssertionError("More than one Odoo order exists for the stable acceptance intent.")
if existing_before:
    order_id = int(existing_before[0]["id"])
    create_disposition = "reused_existing"
else:
    created = post("purchase.order", "create", {"vals_list": [create_values]})
    if not isinstance(created, list) or len(created) != 1:
        raise AssertionError(f"Odoo create returned an unexpected shape: {type(created).__name__}")
    order_id = int(created[0])
    create_disposition = "created"

orders = post(
    "purchase.order",
    "search_read",
    {
        "domain": [["purchaseflow_intent_id", "=", intent_id]],
        "fields": [
            "id",
            "name",
            "partner_id",
            "company_id",
            "currency_id",
            "state",
            "origin",
            "purchaseflow_intent_id",
            "order_line",
            "amount_untaxed",
            "amount_tax",
            "amount_total",
        ],
        "limit": 5,
    },
)
if len(orders) != 1:
    raise AssertionError(f"Expected one independently read Odoo order, found {len(orders)}.")
order = orders[0]


def relation_id(value):
    if isinstance(value, (list, tuple)):
        return int(value[0])
    return int(value)


def money(value):
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


if int(order["id"]) != order_id:
    raise AssertionError("The independent Odoo read returned a different order ID.")
if relation_id(order["partner_id"]) != int(vendor["id"]):
    raise AssertionError("The Odoo order supplier does not match the approved supplier.")
if relation_id(order["company_id"]) != int(manifest["company"]["id"]):
    raise AssertionError("The Odoo order company does not match the PurchaseFlow company.")
if relation_id(order["currency_id"]) != int(manifest["company"]["currency_id"]):
    raise AssertionError("The Odoo order currency does not match CNY.")
if order["state"] != "draft":
    raise AssertionError(f"Odoo order state is {order['state']!r}, expected draft.")
if order["origin"] != intent_id or order["purchaseflow_intent_id"] != intent_id:
    raise AssertionError("The Odoo order does not retain its stable PurchaseFlow intent.")

line_ids = [int(value) for value in order["order_line"]]
if len(line_ids) != 1:
    raise AssertionError(f"Expected one Odoo purchase line, found {len(line_ids)}.")
lines = post(
    "purchase.order.line",
    "search_read",
    {
        "domain": [["id", "in", line_ids]],
        "fields": [
            "id",
            "order_id",
            "product_id",
            "product_qty",
            "product_uom_id",
            "price_unit",
            "tax_ids",
            "price_subtotal",
            "price_tax",
            "price_total",
        ],
        "limit": 5,
    },
)
if len(lines) != 1:
    raise AssertionError("The Odoo purchase line could not be independently read.")
line = lines[0]
if relation_id(line["product_id"]) != int(product["id"]):
    raise AssertionError("The Odoo purchase line product does not match the seeded SKU.")
if relation_id(line["product_uom_id"]) != int(product["uom_id"][0]):
    raise AssertionError("The Odoo purchase line UoM differs from the live product UoM.")
if Decimal(str(line["product_qty"])) != quantity:
    raise AssertionError("The Odoo purchase line quantity does not match the requested quantity.")
if money(line["price_unit"]) != unit_price:
    raise AssertionError("The Odoo purchase line unit price does not match the requested price.")
if int(tax["id"]) not in [int(value) for value in line["tax_ids"]]:
    raise AssertionError("The Odoo purchase line is missing the configured purchase tax.")
if money(line["price_subtotal"]) != expected_untaxed:
    raise AssertionError("Odoo's independently read untaxed subtotal is incorrect.")
if money(line["price_tax"]) != expected_tax:
    raise AssertionError("Odoo's independently read line tax is incorrect.")
if money(line["price_total"]) != expected_total:
    raise AssertionError("Odoo's independently read line total is incorrect.")
if money(order["amount_untaxed"]) != expected_untaxed:
    raise AssertionError("Odoo's independently read order untaxed total is incorrect.")
if money(order["amount_tax"]) != expected_tax:
    raise AssertionError("Odoo's independently read order tax total is incorrect.")
if money(order["amount_total"]) != expected_total:
    raise AssertionError("Odoo's independently read order total is incorrect.")

if (
    existing_before
    and previous_result.get("intent_id") == intent_id
    and previous_result.get("duplicate_create_http") is not None
    and previous_result.get("line_count_after_duplicate_attempt") == 1
):
    duplicate_status = int(previous_result["duplicate_create_http"])
else:
    try:
        post("purchase.order", "create", {"vals_list": [create_values]})
        raise AssertionError("A duplicate PurchaseFlow intent unexpectedly created another Odoo order.")
    except Json2Error as error:
        duplicate_status = error.status

after_duplicate = post(
    "purchase.order",
    "search_read",
    {
        "domain": [["purchaseflow_intent_id", "=", intent_id]],
        "fields": ["id", "name", "state", "purchaseflow_intent_id"],
        "limit": 5,
    },
)
if len(after_duplicate) != 1 or int(after_duplicate[0]["id"]) != order_id:
    raise AssertionError("A repeated Odoo create produced zero or multiple records for one intent.")
if after_duplicate[0]["state"] != "draft":
    raise AssertionError("The deduplicated Odoo order left draft state.")

result = {
    "odoo_version": "19.0-20260926",
    "unauthenticated_json2_http": unauthenticated_status,
    "protected_model_http": protected_model_status,
    "company": manifest["company"],
    "supplier_id": int(vendor["id"]),
    "product_id": int(product["id"]),
    "intent_id": intent_id,
    "create_disposition": create_disposition,
    "odoo_order_id": order_id,
    "odoo_order_name": order["name"],
    "state": order["state"],
    "currency": manifest["company"]["currency"],
    "quantity": str(quantity),
    "unit_price": str(unit_price),
    "amount_untaxed": str(expected_untaxed),
    "tax_rate_percent": str(tax_rate),
    "amount_tax": str(expected_tax),
    "amount_total": str(expected_total),
    "line_count_after_duplicate_attempt": len(after_duplicate),
    "duplicate_create_http": duplicate_status,
}
RESULT_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print("JSON-2 acceptance passed:", json.dumps(result, ensure_ascii=False))
