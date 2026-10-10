from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

from sqlalchemy import select

from app.auth import token_hash
from app.db import SessionLocal
from app.models import (
    Department,
    Membership,
    Organization,
    PolicyConfig,
    ProductMapping,
    ServiceCredential,
    SupplierMapping,
    User,
    utcnow,
)
from app.odoo import OdooJSON2Client

DEPARTMENTS = {
    "admin": "行政部",
    "operations": "运营部",
}
USERS = [
    ("requester.admin@demo.local", "行政部申请人", "requester", "admin"),
    ("requester.ops@demo.local", "运营部申请人", "requester", "operations"),
    ("manager.admin@demo.local", "行政部负责人", "manager", "admin"),
    ("manager.ops@demo.local", "运营部负责人", "manager", "operations"),
    ("finance.one@demo.local", "财务复核人甲", "finance", None),
    ("finance.two@demo.local", "财务复核人乙", "finance", None),
    ("procurement@demo.local", "采购管理员", "procurement", None),
    ("admin@demo.local", "演示系统管理员", "admin", None),
]


def _department(db, organization_id, code: str) -> Department:
    row = db.execute(
        select(Department).where(
            Department.organization_id == organization_id,
            Department.code == code,
        )
    ).scalar_one_or_none()
    if row is None:
        row = Department(organization_id=organization_id, code=code, name=DEPARTMENTS[code])
        db.add(row)
        db.flush()
    elif row.name != DEPARTMENTS[code]:
        row.name = DEPARTMENTS[code]
    return row


def _user(db, organization_id, email: str, display_name: str, role: str, department_id) -> User:
    row = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if row is None:
        row = User(email=email, display_name=display_name, active=True)
        db.add(row)
        db.flush()
    else:
        row.display_name = display_name
        row.active = True

    membership = db.execute(
        select(Membership).where(
            Membership.organization_id == organization_id,
            Membership.user_id == row.id,
            Membership.role == role,
        )
    ).scalar_one_or_none()
    if membership is None:
        db.add(
            Membership(
                organization_id=organization_id,
                user_id=row.id,
                role=role,
                department_id=department_id,
            )
        )
    elif membership.department_id != department_id:
        membership.department_id = department_id
    return row


def _upsert_supplier(db, organization_id, reference, odoo_row) -> None:
    row = db.execute(
        select(SupplierMapping).where(
            SupplierMapping.organization_id == organization_id,
            SupplierMapping.external_ref == reference,
        )
    ).scalar_one_or_none()
    values = {
        "name": odoo_row["name"],
        "odoo_partner_id": int(odoo_row["id"]),
        "active": True,
        "validated_at": utcnow(),
    }
    if row is None:
        row = SupplierMapping(
            organization_id=organization_id,
            external_ref=reference,
            mapping_version=1,
            **values,
        )
        db.add(row)
        return
    changed = any(
        getattr(row, key) != value for key, value in values.items() if key != "validated_at"
    )
    for key, value in values.items():
        setattr(row, key, value)
    if changed:
        row.mapping_version += 1


def _upsert_product(db, organization_id, sku, odoo_row, manifest_row, tax_rate) -> None:
    row = db.execute(
        select(ProductMapping).where(
            ProductMapping.organization_id == organization_id,
            ProductMapping.sku == sku,
        )
    ).scalar_one_or_none()
    values = {
        "name": odoo_row["name"],
        "odoo_product_id": int(odoo_row["id"]),
        "odoo_uom_id": int(odoo_row["uom_id"][0]),
        "odoo_tax_id": int(manifest_row["tax_id"]),
        "unit_price": manifest_row["unit_price_cny"],
        "tax_rate": tax_rate,
        "currency_code": "CNY",
        "active": bool(odoo_row["active"] and odoo_row["purchase_ok"]),
        "validated_at": utcnow(),
    }
    if not values["active"]:
        raise RuntimeError(f"Odoo product {sku} is inactive or not purchasable.")
    if row is None:
        row = ProductMapping(
            organization_id=organization_id,
            sku=sku,
            mapping_version=1,
            **values,
        )
        db.add(row)
        return
    changed = any(
        getattr(row, key) != value for key, value in values.items() if key != "validated_at"
    )
    for key, value in values.items():
        setattr(row, key, value)
    if changed:
        row.mapping_version += 1


def main() -> None:
    manifest_file = Path(os.environ["ODOO_SEED_MANIFEST_FILE"])
    automation_token_file = Path(os.environ["PURCHASEFLOW_AUTOMATION_TOKEN_FILE"])
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest["company"]["currency"] != "CNY" or manifest["company"]["country"] != "CN":
        raise RuntimeError("The Odoo seed company must be configured for China and CNY.")

    client = OdooJSON2Client()
    try:
        vendor_refs = list(manifest["vendors"])
        vendors = client.search_read(
            "res.partner",
            [["ref", "in", vendor_refs]],
            ["id", "name", "ref", "supplier_rank", "country_id"],
        )
        vendor_by_ref = {row["ref"]: row for row in vendors}
        if set(vendor_by_ref) != set(vendor_refs):
            raise RuntimeError("Odoo supplier mapping read-back did not match the seed manifest.")
        for ref, row in vendor_by_ref.items():
            if int(row["supplier_rank"]) < 1:
                raise RuntimeError(f"Odoo record {ref} is not a supplier.")

        product_skus = list(manifest["products"])
        products = client.search_read(
            "product.product",
            [["default_code", "in", product_skus]],
            ["id", "name", "default_code", "uom_id", "purchase_ok", "active"],
        )
        product_by_sku = {row["default_code"]: row for row in products}
        if set(product_by_sku) != set(product_skus):
            raise RuntimeError("Odoo product mapping read-back did not match the seed manifest.")

        tax_ids = [int(value["id"]) for value in manifest["taxes"].values()]
        taxes = client.search_read(
            "account.tax",
            [["id", "in", tax_ids]],
            ["id", "name", "amount", "type_tax_use", "company_id", "active"],
        )
        tax_by_id = {int(row["id"]): row for row in taxes}
        for row in manifest["taxes"].values():
            tax = tax_by_id.get(int(row["id"]))
            if (
                tax is None
                or not tax["active"]
                or tax["type_tax_use"] != "purchase"
                or str(tax["amount"]) != str(row["rate_percent"])
            ):
                raise RuntimeError("Odoo purchase tax read-back did not match the seed manifest.")
    finally:
        client.close()

    pending_file = automation_token_file.with_suffix(".pending")
    if automation_token_file.is_file():
        automation_token = automation_token_file.read_text(encoding="ascii").strip()
        if not automation_token:
            raise RuntimeError("The local automation token file is empty.")
    else:
        automation_token = secrets.token_urlsafe(40)
        automation_token_file.parent.mkdir(parents=True, exist_ok=True)
        pending_file = automation_token_file.with_suffix(".pending")
        pending_file.write_text(automation_token, encoding="ascii")
        os.chmod(pending_file, 0o600)

    with SessionLocal() as db:
        organization = db.execute(
            select(Organization).where(Organization.code == "demo-office")
        ).scalar_one_or_none()
        values = {
            "name": manifest["company"]["name"],
            "currency_code": manifest["company"]["currency"],
            "odoo_company_id": int(manifest["company"]["id"]),
            "odoo_currency_id": int(manifest["company"]["currency_id"]),
        }
        if organization is None:
            organization = Organization(code="demo-office", **values)
            db.add(organization)
            db.flush()
        else:
            for key, value in values.items():
                setattr(organization, key, value)
        organization_id = organization.id

        departments = {code: _department(db, organization_id, code) for code in DEPARTMENTS}
        for email, display_name, role, department_code in USERS:
            department_id = departments[department_code].id if department_code else None
            _user(db, organization_id, email, display_name, role, department_id)

        policy = db.execute(
            select(PolicyConfig).where(PolicyConfig.organization_id == organization_id)
        ).scalar_one_or_none()
        if policy is None:
            db.add(
                PolicyConfig(
                    organization_id=organization_id,
                    version=1,
                    manager_limit="5000.00",
                    policy_review_limit="20000.00",
                    tax_inclusive=True,
                )
            )

        for ref, row in vendor_by_ref.items():
            _upsert_supplier(db, organization_id, ref, row)

        tax_rates = {
            "PF-OFFICE-SET": "13.00",
            "PF-IT-MONITOR": "13.00",
            "PF-SERVICE-CONSULT": "6.00",
        }
        for sku, row in product_by_sku.items():
            manifest_row = manifest["products"][sku]
            _upsert_product(
                db,
                organization_id,
                sku,
                row,
                manifest_row,
                tax_rates[sku],
            )

        token_digest = token_hash(automation_token)
        credential = db.execute(
            select(ServiceCredential).where(ServiceCredential.name == "n8n-demo-intake")
        ).scalar_one_or_none()
        if credential is None:
            db.add(
                ServiceCredential(
                    organization_id=organization_id,
                    name="n8n-demo-intake",
                    token_hash=token_digest,
                    active=True,
                )
            )
        else:
            credential.organization_id = organization_id
            credential.token_hash = token_digest
            credential.active = True
        db.commit()

    if pending_file.is_file():
        pending_file.replace(automation_token_file)
        os.chmod(automation_token_file, 0o600)

    print(
        "PurchaseFlow demo seed complete:",
        f"departments={len(DEPARTMENTS)}",
        f"users={len(USERS)}",
        f"vendors={len(vendor_by_ref)}",
        f"products={len(product_by_sku)}",
        "service_token_stored=true",
    )


if __name__ == "__main__":
    main()
