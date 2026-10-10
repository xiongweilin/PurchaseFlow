from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import secrets

local = Path("/run/purchaseflow-local")
company = env.company.sudo()
country = env["res.country"].sudo().search([("code", "=", "CN")], limit=1)
currency = env["res.currency"].sudo().with_context(active_test=False).search([("name", "=", "CNY")], limit=1)
if not country or not currency:
    raise RuntimeError("Odoo does not contain the China country or CNY currency master record.")
currency.active = True
company.write({"name": "Demo Office Ltd.", "country_id": country.id, "currency_id": currency.id})
company.partner_id.sudo().write({"name": "Demo Office Ltd.", "country_id": country.id})

tax_group = env["account.tax.group"].sudo().search([
    ("name", "=", "PurchaseFlow Demo Taxes"),
    ("company_id", "=", company.id),
], limit=1)
if not tax_group:
    tax_group = env["account.tax.group"].sudo().create({
        "name": "PurchaseFlow Demo Taxes",
        "company_id": company.id,
        "country_id": country.id,
    })

tax_specs = {
    "PF-CN-PURCHASE-13": ("PF Demo Purchase VAT 13%", 13.0),
    "PF-CN-PURCHASE-6": ("PF Demo Purchase VAT 6%", 6.0),
}
taxes = {}
for ref, (name, rate) in tax_specs.items():
    tax = env["account.tax"].sudo().search([
        ("name", "=", name),
        ("company_id", "=", company.id),
        ("type_tax_use", "=", "purchase"),
    ], limit=1)
    values = {
        "name": name,
        "amount": rate,
        "amount_type": "percent",
        "type_tax_use": "purchase",
        "company_id": company.id,
        "country_id": country.id,
        "tax_group_id": tax_group.id,
        "price_include": False,
        "active": True,
    }
    if tax:
        tax.write(values)
    else:
        tax = env["account.tax"].sudo().create(values)
    taxes[ref] = tax

vendors = {}
for ref, name in [
    ("PF-VENDOR-OFFICE", "Demo Office Supplies Ltd."),
    ("PF-VENDOR-IT", "Demo Technology Ltd."),
    ("PF-VENDOR-SERVICE", "Demo Business Services Ltd."),
]:
    vendor = env["res.partner"].sudo().search([("ref", "=", ref)], limit=1)
    values = {
        "name": name,
        "ref": ref,
        "company_type": "company",
        "supplier_rank": 1,
        "country_id": country.id,
        "company_id": False,
    }
    if vendor:
        vendor.write(values)
    else:
        vendor = env["res.partner"].sudo().create(values)
    vendors[ref] = vendor

products = {}
for sku, name, kind, unit_price, tax_ref in [
    ("PF-OFFICE-SET", "Office supplies set", "consu", 1200.0, "PF-CN-PURCHASE-13"),
    ("PF-IT-MONITOR", "Business monitor", "consu", 4000.0, "PF-CN-PURCHASE-13"),
    ("PF-SERVICE-CONSULT", "Business services package", "service", 5000.0, "PF-CN-PURCHASE-6"),
]:
    template = env["product.template"].sudo().search([("default_code", "=", sku)], limit=1)
    values = {
        "name": name,
        "default_code": sku,
        "type": kind,
        "purchase_ok": True,
        "sale_ok": False,
        "list_price": unit_price,
        "standard_price": unit_price,
        "supplier_taxes_id": [(6, 0, [taxes[tax_ref].id])],
        "company_id": company.id,
    }
    if template:
        template.write(values)
    else:
        template = env["product.template"].sudo().create(values)
    product = template.product_variant_id
    product.write({"default_code": sku})
    products[sku] = product

admin_password = os.environ["ODOO_ADMIN_PASSWORD"]
admin_user = env.ref("base.user_admin").sudo()
admin_user.write({"password": admin_password})

service_login = "purchaseflow.integration"
service_user = env["res.users"].sudo().search([("login", "=", service_login)], limit=1)
internal_group = env.ref("base.group_user")
purchase_group = env.ref("purchase.group_purchase_user")
if service_user:
    service_user.write({
        "name": "PurchaseFlow Integration",
        "company_id": company.id,
        "company_ids": [(6, 0, [company.id])],
        "group_ids": [(6, 0, [internal_group.id, purchase_group.id])],
        "active": True,
    })
else:
    service_user = env["res.users"].sudo().create({
        "name": "PurchaseFlow Integration",
        "login": service_login,
        "password": secrets.token_urlsafe(48),
        "company_id": company.id,
        "company_ids": [(6, 0, [company.id])],
        "group_ids": [(6, 0, [internal_group.id, purchase_group.id])],
        "active": True,
    })

env.cr.commit()

key_path = local / "odoo-api-key"
key_temp = local / "odoo-api-key.pending"
if not key_path.exists():
    if key_temp.exists():
        raise RuntimeError("A pending Odoo API key exists; reconcile it before generating another.")
    expiration = datetime.utcnow() + timedelta(days=30)
    key = env["res.users.apikeys"].with_user(service_user).sudo()._generate(
        None,
        "PurchaseFlow local integration (30 days)",
        expiration,
    )
    with key_temp.open("x", encoding="ascii") as stream:
        stream.write(key)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(key_temp, 0o600)
    env.cr.commit()
    key_temp.replace(key_path)
    os.chmod(key_path, 0o600)
else:
    env.cr.commit()

manifest = {
    "odoo_version": "19.0",
    "database": "purchaseflow_odoo",
    "company": {"id": company.id, "name": company.name, "currency": currency.name, "currency_id": currency.id, "country": country.code},
    "taxes": {ref: {"id": tax.id, "name": tax.name, "rate_percent": tax.amount} for ref, tax in taxes.items()},
    "vendors": {ref: {"id": vendor.id, "name": vendor.name} for ref, vendor in vendors.items()},
    "products": {
        sku: {
            "id": product.id,
            "template_id": product.product_tmpl_id.id,
            "name": product.name,
            "unit_price_cny": product.standard_price,
            "tax_id": taxes[tax_ref].id,
            "uom_id": product.uom_id.id,
        }
        for sku, product in products.items()
        for tax_ref in [
            "PF-CN-PURCHASE-13" if sku != "PF-SERVICE-CONSULT" else "PF-CN-PURCHASE-6"
        ]
    },
    "integration_user": {"id": service_user.id, "login": service_user.login},
}
(local / "odoo-seed-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print("Odoo seed complete:", json.dumps({
    "company": manifest["company"],
    "vendor_count": len(vendors),
    "product_count": len(products),
    "taxes": len(taxes),
    "integration_user": manifest["integration_user"],
    "api_key_stored": key_path.exists(),
}, ensure_ascii=False))
