from __future__ import annotations

import argparse

from sqlalchemy import select

from app.db import SessionLocal
from app.models import ERPIntent, Procurement
from app.odoo import OdooJSON2Client, compare_order


def verify(external_intent_id: str) -> None:
    with SessionLocal() as db:
        intent = db.execute(
            select(ERPIntent).where(ERPIntent.external_intent_id == external_intent_id)
        ).scalar_one_or_none()
        if intent is None:
            raise RuntimeError("The persisted PurchaseFlow ERP intent was not found.")
        procurement = db.get(Procurement, intent.procurement_id)
        if procurement is None or procurement.status not in {"erp_verified", "closed"}:
            raise RuntimeError("The persisted request is not in a verified or closed state.")
        if intent.state != "verified" or not intent.remote_order_name:
            raise RuntimeError("The persisted ERP intent is not verified with an Odoo order number.")
        request_number = procurement.request_number
        expected_order_name = intent.remote_order_name
        snapshot = dict(intent.expected_snapshot)

    client = OdooJSON2Client()
    try:
        remote = client.read_order(external_intent_id)
        if remote is None:
            raise RuntimeError("The Odoo purchase draft was not found after the container restart.")
        if compare_order(snapshot, remote):
            raise RuntimeError("The Odoo draft no longer matches the persisted approval snapshot.")
        if remote["header"]["state"] != "draft":
            raise RuntimeError("The persisted Odoo purchase order is no longer a draft.")
        if remote["header"]["name"] != expected_order_name:
            raise RuntimeError("Odoo returned a different order number for the same intent.")
        print(
            f"PASS: {request_number} still maps to Odoo draft {expected_order_name}; "
            "read-back matches the persisted approved facts."
        )
    finally:
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify a persisted PurchaseFlow intent in live Odoo.")
    parser.add_argument("--external-intent-id", required=True)
    verify(parser.parse_args().external_intent_id)
