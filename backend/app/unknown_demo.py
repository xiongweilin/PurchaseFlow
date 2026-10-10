from __future__ import annotations

import argparse
from uuid import UUID

from sqlalchemy import select

from app.db import SessionLocal
from app.models import ERPIntent, OutboxEvent, Procurement
from app.odoo import OdooJSON2Client, OdooOutcomeUnknown, compare_order
from app.services.erp import process_one


class DropCreateResponseAfterCommit(OdooJSON2Client):
    """Create in the real Odoo instance, then lose only the response for this demo."""

    create_calls = 0

    def create_purchase_order(self, snapshot: dict) -> int:
        self.create_calls += 1
        remote_id = super().create_purchase_order(snapshot)
        raise OdooOutcomeUnknown(
            f"Controlled demo discarded the create response after Odoo committed order {remote_id}."
        )


def run(procurement_id: UUID) -> None:
    with SessionLocal() as db:
        procurement = db.get(Procurement, procurement_id)
        if procurement is None or procurement.status not in {"approved", "erp_pending"}:
            raise RuntimeError("The target must be an approved request awaiting ERP dispatch.")
        intent = db.execute(
            select(ERPIntent).where(ERPIntent.procurement_id == procurement_id)
        ).scalar_one()
        event = db.execute(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == str(intent.id))
        ).scalar_one()
        if intent.state != "pending" or event.status != "pending":
            raise RuntimeError("The target ERP intent must not have been dispatched already.")
        request_number = procurement.request_number
        event_id = event.id
        intent_id = intent.external_intent_id
        snapshot = dict(intent.expected_snapshot)

    client = DropCreateResponseAfterCommit()
    try:
        if not process_one(client=client, outbox_id=event_id):
            raise RuntimeError("The target ERP outbox event was not available to the worker.")
        if client.create_calls != 1:
            raise RuntimeError("The controlled response-loss path did not create exactly one Odoo order.")

        with SessionLocal() as db:
            procurement = db.get(Procurement, procurement_id)
            intent = db.execute(
                select(ERPIntent).where(ERPIntent.procurement_id == procurement_id)
            ).scalar_one()
            if (
                procurement is None
                or procurement.status != "erp_unknown"
                or intent.state != "unknown"
                or intent.last_observation is None
                or intent.last_observation.get("disposition") != "UNKNOWN"
                or intent.last_observation.get("write_attempted") is not True
                or intent.attempts != 1
            ):
                raise RuntimeError("PurchaseFlow did not persist the expected single-attempt UNKNOWN state.")

        remote = client.read_order(intent_id)
        if remote is None or compare_order(snapshot, remote):
            raise RuntimeError("The real Odoo draft could not be independently read back as a match.")
        remote_name = str(remote["header"]["name"])
    finally:
        client.close()

    print(
        f"PASS: {request_number} created real Odoo draft {remote_name}; "
        "the app recorded UNKNOWN after one dispatch and is ready for manual reconciliation."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inject a real-Odoo create-response-loss demo.")
    parser.add_argument("--procurement-id", required=True, type=UUID)
    run(parser.parse_args().procurement_id)
