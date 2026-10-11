from __future__ import annotations

import argparse
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from app.db import SessionLocal
from app.models import ERPIntent, Procurement
from app.odoo import OdooJSON2Client, compare_order

MISMATCH_DEMO_REASON = "Controlled demo: recover from a real Odoo field mismatch."


def run(mode: str, procurement_id: UUID) -> None:
    with SessionLocal() as db:
        procurement = db.get(Procurement, procurement_id)
        if procurement is None or procurement.reason != MISMATCH_DEMO_REASON:
            raise RuntimeError("The target must be the synthetic Odoo mismatch demo request.")
        intent = db.execute(
            select(ERPIntent).where(ERPIntent.procurement_id == procurement_id)
        ).scalar_one()
        marker = intent.external_intent_id
        expected = dict(intent.expected_snapshot)
        current_state = intent.state
        current_status = procurement.status

    if len(expected["lines"]) != 1:
        raise RuntimeError("The mismatch demo expects exactly one approved Odoo line.")
    expected_price = Decimal(expected["lines"][0]["unit_price"])
    target_price = expected_price + Decimal("1.00") if mode == "tamper" else expected_price

    client = OdooJSON2Client()
    try:
        remote = client.read_order(marker)
        if remote is None or "duplicate_rows" in remote:
            raise RuntimeError("The target real Odoo draft could not be read uniquely.")
        if remote["header"].get("state") != "draft":
            raise RuntimeError("The mismatch demo may only change an Odoo draft.")
        lines = remote.get("lines", [])
        if len(lines) != 1:
            raise RuntimeError("The target Odoo draft must have exactly one line.")

        if mode == "tamper":
            if current_state != "verified" or current_status != "erp_verified":
                raise RuntimeError("Only an independently verified draft may be tampered with.")
            if compare_order(expected, remote):
                raise RuntimeError("The Odoo draft must match the approved snapshot before tampering.")
        elif mode == "restore" and current_state not in {"mismatch", "verified"}:
            raise RuntimeError("The synthetic request is not in a restorable ERP state.")

        current_price = Decimal(str(lines[0]["price_unit"]))
        if current_price != target_price:
            client._post(
                "purchase.order.line",
                "write",
                {"ids": [int(lines[0]["id"])], "vals": {"price_unit": float(target_price)}},
                write=True,
            )

        observed = client.read_order(marker)
        if observed is None or "duplicate_rows" in observed:
            raise RuntimeError("The Odoo draft could not be read after the controlled price update.")
        if observed["header"].get("state") != "draft":
            raise RuntimeError("The controlled price update changed the Odoo order state.")
        if len(observed.get("lines", [])) != 1:
            raise RuntimeError("The Odoo draft line disappeared during the controlled update.")
        actual_price = Decimal(str(observed["lines"][0]["price_unit"]))

        if mode == "tamper":
            differences = compare_order(expected, observed)
            if actual_price != target_price or "line_1" not in differences:
                raise RuntimeError("PurchaseFlow's expected-vs-actual price mismatch was not created.")
            if "amount_total" not in differences:
                raise RuntimeError("Odoo did not recompute the total after the controlled price change.")
            print(
                f"PASS: real Odoo draft {remote['header']['name']} remains draft; "
                f"unit price changed from {expected_price} to {actual_price}."
            )
        else:
            differences = compare_order(expected, observed)
            if actual_price != expected_price or differences:
                raise RuntimeError("The real Odoo draft did not return to the approved snapshot.")
            print(
                f"PASS: real Odoo draft {remote['header']['name']} was restored to "
                f"unit price {actual_price} and matches the approved snapshot."
            )
    finally:
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inject or restore a controlled Odoo price mismatch.")
    parser.add_argument("--mode", choices=("tamper", "restore"), required=True)
    parser.add_argument("--procurement-id", required=True, type=UUID)
    arguments = parser.parse_args()
    run(arguments.mode, arguments.procurement_id)
