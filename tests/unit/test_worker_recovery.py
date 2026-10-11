from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from threading import Event, Thread
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.models import (
    Department,
    ERPIntent,
    Organization,
    OutboxEvent,
    Procurement,
    ProcurementLine,
    ProductMapping,
    SupplierMapping,
    User,
    utcnow,
)
from app.odoo import (
    OdooJSON2Client,
    OdooOutcomeUnknown,
    OdooUnavailable,
    compare_order,
)
from app.services.erp import process_one


def seed_intent(factory, external_id: str = "PF-TEST-INTENT"):
    with factory() as db:
        org = Organization(
            code=f"test-{uuid4().hex[:8]}",
            name="Test Co",
            currency_code="CNY",
            odoo_company_id=1,
            odoo_currency_id=6,
        )
        db.add(org)
        db.flush()
        department = Department(organization_id=org.id, code="ops", name="Operations")
        user = User(email=f"{uuid4().hex}@test.local", display_name="Requester", active=True)
        db.add_all([department, user])
        db.flush()
        supplier = SupplierMapping(
            organization_id=org.id,
            external_ref="V",
            name="Vendor",
            odoo_partner_id=6,
            mapping_version=1,
            active=True,
            validated_at=utcnow(),
        )
        product = ProductMapping(
            organization_id=org.id,
            sku="SKU",
            name="Test product",
            odoo_product_id=1,
            odoo_uom_id=1,
            odoo_tax_id=5,
            unit_price=Decimal("1200.00"),
            tax_rate=Decimal("13.00"),
            currency_code="CNY",
            mapping_version=1,
            active=True,
            validated_at=utcnow(),
        )
        db.add_all([supplier, product])
        db.flush()
        procurement = Procurement(
            organization_id=org.id,
            request_number=f"PR-TEST-{uuid4().hex[:8]}",
            requester_id=user.id,
            department_id=department.id,
            supplier_mapping_id=supplier.id,
            reason="Worker reconciliation test",
            currency_code="CNY",
            status="approved",
            version=4,
            policy_version=1,
            amount_untaxed=Decimal("1200.00"),
            amount_tax=Decimal("156.00"),
            amount_total=Decimal("1356.00"),
            submitted_snapshot={
                "odoo_partner_id": 6,
                "odoo_company_id": 1,
                "odoo_currency_id": 6,
                "manager_limit": "5000.00",
                "policy_review_limit": "20000.00",
                "policy_version": 1,
            },
        )
        db.add(procurement)
        db.flush()
        procurement.lines = [
            ProcurementLine(
                product_mapping_id=product.id,
                line_number=1,
                sku="SKU",
                product_name="Test product",
                odoo_product_id=1,
                odoo_uom_id=1,
                odoo_tax_id=5,
                quantity=Decimal("1.00"),
                unit_price=Decimal("1200.00"),
                tax_rate=Decimal("13.00"),
                amount_untaxed=Decimal("1200.00"),
                amount_tax=Decimal("156.00"),
                amount_total=Decimal("1356.00"),
                mapping_version=1,
            )
        ]
        expected = {
            **procurement.submitted_snapshot,
            "erp_intent_id": external_id,
            "amount_untaxed": "1200.00",
            "amount_tax": "156.00",
            "amount_total": "1356.00",
            "lines": [
                {
                    "line_number": 1,
                    "sku": "SKU",
                    "product_name": "Test product",
                    "odoo_product_id": 1,
                    "odoo_uom_id": 1,
                    "odoo_tax_id": 5,
                    "quantity": "1.00",
                    "unit_price": "1200.00",
                    "amount_untaxed": "1200.00",
                    "amount_tax": "156.00",
                    "amount_total": "1356.00",
                }
            ],
        }
        intent = ERPIntent(
            procurement_id=procurement.id,
            external_intent_id=external_id,
            request_hash="a" * 64,
            expected_snapshot=expected,
            state="pending",
        )
        db.add(intent)
        db.flush()
        event = OutboxEvent(
            topic="erp.create_draft",
            aggregate_id=str(intent.id),
            payload_json={"erp_intent_id": str(intent.id)},
            status="pending",
            available_at=utcnow() - timedelta(seconds=1),
        )
        db.add(event)
        db.commit()
        return procurement.id, intent.id, event.id, expected


def remote_order(snapshot: dict, *, order_id: int = 77, state: str = "draft") -> dict:
    return {
        "header": {
            "id": order_id,
            "name": f"P{order_id:05d}",
            "partner_id": [snapshot["odoo_partner_id"], "Vendor"],
            "company_id": [snapshot["odoo_company_id"], "Test Co"],
            "currency_id": [snapshot["odoo_currency_id"], "CNY"],
            "state": state,
            "origin": snapshot["erp_intent_id"],
            "purchaseflow_intent_id": snapshot["erp_intent_id"],
            "order_line": [101],
            "amount_untaxed": 1200.0,
            "amount_tax": 156.0,
            "amount_total": 1356.0,
        },
        "lines": [
            {
                "id": 101,
                "order_id": [order_id, f"P{order_id:05d}"],
                "product_id": [1, "Test product"],
                "product_qty": 1.0,
                "product_uom_id": [1, "Units"],
                "price_unit": 1200.0,
                "tax_ids": [5],
                "price_subtotal": 1200.0,
                "price_tax": 156.0,
                "price_total": 1356.0,
            }
        ],
    }


class CreatingOdoo:
    def __init__(self) -> None:
        self.remote = None
        self.create_calls = 0
        self.read_calls = 0

    def read_order(self, marker: str):
        self.read_calls += 1
        return self.remote

    def create_purchase_order(self, snapshot):
        self.create_calls += 1
        self.remote = remote_order(snapshot)
        return 77


class UnknownAfterCreate:
    def __init__(self) -> None:
        self.create_calls = 0

    def read_order(self, marker: str):
        return None

    def create_purchase_order(self, snapshot):
        self.create_calls += 1
        raise OdooOutcomeUnknown("simulated lost create response")


class UnavailableThenCreating(CreatingOdoo):
    def __init__(self) -> None:
        super().__init__()
        self.read_calls = 0

    def read_order(self, marker: str):
        self.read_calls += 1
        if self.read_calls == 1:
            raise OdooUnavailable("simulated unavailable Odoo read")
        return self.remote


def test_worker_creates_then_independently_reads_and_verifies(session_factory):
    _, intent_id, _, _ = seed_intent(session_factory)
    client = CreatingOdoo()

    assert process_one(factory=session_factory, client=client) is True
    assert client.create_calls == 1
    assert client.read_calls == 2

    with session_factory() as db:
        intent = db.get(ERPIntent, intent_id)
        procurement = db.get(Procurement, intent.procurement_id)
        event = db.execute(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == str(intent_id))
        ).scalar_one()
        assert intent.state == "verified"
        assert intent.remote_order_id == 77
        assert intent.remote_order_name == "P00077"
        assert procurement.status == "erp_verified"
        assert event.status == "done"
        assert intent.last_observation["disposition"] == "VERIFIED"


def test_unknown_create_is_not_blindly_retried(session_factory):
    _, intent_id, _, _ = seed_intent(session_factory)
    client = UnknownAfterCreate()

    assert process_one(factory=session_factory, client=client) is True
    assert process_one(factory=session_factory, client=client) is False
    assert client.create_calls == 1

    with session_factory() as db:
        intent = db.get(ERPIntent, intent_id)
        procurement = db.get(Procurement, intent.procurement_id)
        event = db.execute(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == str(intent_id))
        ).scalar_one()
        assert intent.state == "unknown"
        assert intent.last_observation["disposition"] == "UNKNOWN"
        assert procurement.status == "erp_unknown"
        assert event.status == "done"


def test_unavailable_before_write_is_rescheduled_safely(session_factory):
    _, intent_id, event_id, _ = seed_intent(session_factory)
    client = UnavailableThenCreating()

    assert process_one(factory=session_factory, client=client) is True
    with session_factory() as db:
        intent = db.get(ERPIntent, intent_id)
        event = db.get(OutboxEvent, event_id)
        assert intent.state == "unavailable"
        assert intent.last_observation["write_attempted"] is False
        assert event.status == "pending"
        event.available_at = utcnow() - timedelta(seconds=1)
        db.commit()

    assert process_one(factory=session_factory, client=client) is True
    assert client.create_calls == 1
    with session_factory() as db:
        intent = db.get(ERPIntent, intent_id)
        procurement = db.get(Procurement, intent.procurement_id)
        assert intent.state == "verified"
        assert procurement.status == "erp_verified"


def test_mismatch_is_not_reported_as_success(session_factory):
    _, intent_id, _, snapshot = seed_intent(session_factory)
    client = CreatingOdoo()
    client.remote = remote_order(snapshot, state="purchase")

    assert process_one(factory=session_factory, client=client) is True
    with session_factory() as db:
        intent = db.get(ERPIntent, intent_id)
        procurement = db.get(Procurement, intent.procurement_id)
        assert intent.state == "mismatch"
        assert "state" in intent.last_observation["differences"]
        assert procurement.status == "erp_mismatch"


def test_expired_worker_cannot_overwrite_new_workers_verified_observation(session_factory):
    _, intent_id, event_id, snapshot = seed_intent(session_factory)
    first_request_started = Event()
    allow_first_request_to_return = Event()
    first_result = []
    first_errors = []

    class SlowStaleOdoo:
        def read_order(self, marker: str):
            first_request_started.set()
            if not allow_first_request_to_return.wait(timeout=5):
                raise TimeoutError("The test did not release the expired worker request.")
            return remote_order(snapshot, state="purchase")

        def create_purchase_order(self, snapshot):
            raise AssertionError("The stale worker must not create after its read returns.")

    def run_expired_worker():
        try:
            first_result.append(
                process_one(
                    factory=session_factory,
                    client=SlowStaleOdoo(),
                    lease_seconds=60,
                    outbox_id=event_id,
                )
            )
        except Exception as error:  # surfaced in the main test thread below
            first_errors.append(error)

    first_worker = Thread(target=run_expired_worker, daemon=True)
    first_worker.start()
    assert first_request_started.wait(timeout=5)

    with session_factory() as db:
        event = db.get(OutboxEvent, event_id)
        assert event.status == "processing"
        assert event.lease_generation == 1
        event.lease_until = utcnow() - timedelta(seconds=1)
        db.commit()

    second_worker = CreatingOdoo()
    second_worker.remote = remote_order(snapshot)
    assert process_one(
        factory=session_factory,
        client=second_worker,
        lease_seconds=60,
        outbox_id=event_id,
    ) is True

    allow_first_request_to_return.set()
    first_worker.join(timeout=5)
    assert not first_worker.is_alive()
    assert not first_errors
    assert first_result == [True]

    with session_factory() as db:
        intent = db.get(ERPIntent, intent_id)
        procurement = db.get(Procurement, intent.procurement_id)
        event = db.get(OutboxEvent, event_id)
        assert intent.state == "verified"
        assert intent.last_observation["disposition"] == "VERIFIED"
        assert intent.remote_order_id == 77
        assert procurement.status == "erp_verified"
        assert event.status == "done"
        assert event.lease_generation == 2
        assert event.attempts == 2
        assert event.lease_until is None


def test_create_transport_timeout_is_unknown_but_read_timeout_is_unavailable():
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated network loss", request=request)

    client = httpx.Client(transport=httpx.MockTransport(timeout_handler))
    adapter = OdooJSON2Client(
        base_url="http://odoo.test",
        database="purchaseflow_odoo",
        api_key="not-a-real-key",
        client=client,
    )
    with pytest.raises(OdooOutcomeUnknown):
        adapter.create_purchase_order(
            {
                "odoo_partner_id": 1,
                "odoo_company_id": 1,
                "odoo_currency_id": 1,
                "erp_intent_id": "PF-TIMEOUT",
                "lines": [],
            }
        )
    with pytest.raises(OdooUnavailable):
        adapter.search_read("res.partner", [], ["id"])
    adapter.close()


def test_compare_order_checks_all_approved_purchase_facts():
    snapshot = {
        "odoo_partner_id": 6,
        "odoo_company_id": 1,
        "odoo_currency_id": 6,
        "erp_intent_id": "PF-COMPARE",
        "amount_untaxed": "1200.00",
        "amount_tax": "156.00",
        "amount_total": "1356.00",
        "lines": [
            {
                "odoo_product_id": 1,
                "odoo_uom_id": 1,
                "odoo_tax_id": 5,
                "quantity": "1",
                "unit_price": "1200.00",
                "amount_untaxed": "1200.00",
                "amount_tax": "156.00",
                "amount_total": "1356.00",
            }
        ],
    }
    assert compare_order(snapshot, remote_order(snapshot)) == {}
    mismatched = remote_order(snapshot, state="purchase")
    assert "state" in compare_order(snapshot, mismatched)
