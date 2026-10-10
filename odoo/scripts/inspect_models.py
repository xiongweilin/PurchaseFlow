checks = {
    "res.company": ["name", "currency_id", "partner_id", "country_id"],
    "res.currency": ["name", "active", "symbol", "rounding", "decimal_places"],
    "res.country": ["name", "code"],
    "res.partner": ["name", "ref", "supplier_rank", "company_type", "is_company", "company_id", "country_id"],
    "product.template": ["name", "default_code", "type", "detailed_type", "purchase_ok", "sale_ok", "supplier_taxes_id", "standard_price", "list_price", "uom_id", "uom_po_id", "company_id", "active", "product_variant_id"],
    "product.product": ["name", "default_code", "product_tmpl_id", "active", "purchase_ok", "uom_id", "uom_po_id"],
    "account.tax": ["name", "amount", "amount_type", "type_tax_use", "company_id", "country_id", "active", "price_include", "tax_group_id"],
    "purchase.order": ["partner_id", "company_id", "currency_id", "order_line", "origin", "purchaseflow_intent_id", "state", "name", "amount_untaxed", "amount_tax", "amount_total"],
    "purchase.order.line": ["order_id", "product_id", "product_qty", "product_uom", "product_uom_id", "price_unit", "taxes_id", "price_subtotal", "price_tax", "price_total"],
    "res.users": ["login", "name", "company_id", "company_ids", "groups_id", "active", "password"],
    "res.users.apikeys": ["name", "user_id", "scope", "expiration_date"],
}
for model_name, names in checks.items():
    model = env[model_name]
    print("MODEL", model_name)
    for name in names:
        field = model._fields.get(name)
        if field:
            print(" ", name, field.type, "comodel=", getattr(field, "comodel_name", None), "required=", field.required)
        else:
            print(" ", name, "ABSENT")
