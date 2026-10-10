for model_name in ["purchase.order.line", "res.users", "res.groups", "account.tax", "account.tax.group", "product.template"]:
    model = env[model_name]
    print("MODEL", model_name)
    for name, field in sorted(model._fields.items()):
        if any(term in name for term in ["group", "tax", "uom", "company", "currency", "api_key"]):
            print(" ", name, field.type, getattr(field, "comodel_name", None), "required=", field.required)
print("GROUP XMLIDS")
for xmlid in ["base.group_user", "purchase.group_purchase_user", "purchase.group_purchase_manager", "base.group_system"]:
    try:
        rec = env.ref(xmlid)
        print(xmlid, rec.id, rec.display_name)
    except ValueError:
        print(xmlid, "NOT FOUND")
print("CNY", env["res.currency"].search_read([("name", "=", "CNY")], ["id", "name", "active", "symbol", "rounding"]))
print("CN", env["res.country"].search_read([("code", "=", "CN")], ["id", "name", "code"]))
print("COMPANY", env.company.id, env.company.name, env.company.currency_id.name)
print("TAX GROUPS", env["account.tax.group"].search_read([], ["id", "name", "country_id"]))
