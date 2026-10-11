from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.auth import Principal
from app.db import Base
from app.domain import DomainError
from app.models import (
    Approval,
    Department,
    ERPIntent,
    Organization,
    OutboxEvent,
    PolicyConfig,
    Procurement,
    SupplierMapping,
    User,
    utcnow,
)
from app.services.erp import process_one
from app.services.procurement import decide


@pytest.fixture
def postgres_factory():
    url = os.getenv("DATABASE_URL_TEST")
    test_url_file = os.getenv("DATABASE_URL_TEST_FILE")
    if not url and test_url_file and os.path.isfile(test_url_file):
        with open(test_url_file, encoding="utf-8") as stream:
            url = stream.read().strip()
    if not url:
        pytest.skip("DATABASE_URL_TEST is not set; Postgres integration tests run in CI.")
    engine = create_engine(url, pool_pre_ping=True)
    if not engine.url.database or not engine.url.database.endswith("_test"):
        engine.dispose()
        raise RuntimeError("Refusing to create/drop tables outside a database ending in _test.")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_concurrent_manager_approval_commits_one_decision_and_one_outbox(postgres_factory):
    with postgres_factory() as db:
        org = Organization(
            code=f"concurrency-{uuid4().hex[:8]}",
            name="Concurrency Test",
            currency_code="CNY",
            odoo_company_id=uuid4().int % 100000,
            odoo_currency_id=6,
        )
        db.add(org)
        db.flush()
        department = Department(organization_id=org.id, code="ops", name="Operations")
        applicant = User(
            email=f"applicant-{uuid4().hex}@test.local",
            display_name="Applicant",
        )
        manager_a = User(
            email=f"manager-a-{uuid4().hex}@test.local",
            display_name="Manager A",
        )
        manager_b = User(
            email=f"manager-b-{uuid4().hex}@test.local",
            display_name="Manager B",
        )
        supplier = SupplierMapping(
            organization_id=org.id,
            external_ref="TEST-VENDOR",
            name="Test vendor",
            odoo_partner_id=98765,
            mapping_version=1,
            active=True,
        )
        db.add_all([department, applicant, manager_a, manager_b, supplier])
        db.flush()
        policy = PolicyConfig(
            organization_id=org.id,
            version=1,
            manager_limit="5000.00",
            policy_review_limit="20000.00",
            tax_inclusive=True,
        )
        request = Procurement(
            organization_id=org.id,
            request_number=f"PR-TEST-{uuid4().hex[:8]}",
            requester_id=applicant.id,
            department_id=department.id,
            supplier_mapping_id=supplier.id,
            reason="Concurrency control test",
            currency_code="CNY",
            status="pending_manager",
            version=2,
            policy_version=1,
            amount_untaxed="1200.00",
            amount_tax="156.00",
            amount_total="1356.00",
            submitted_snapshot={
                "policy_version": 1,
                "manager_limit": "5000.00",
                "policy_review_limit": "20000.00",
                "amount_untaxed": "1200.00",
                "amount_tax": "156.00",
                "amount_total": "1356.00",
                "lines": [],
            },
        )
        db.add_all([policy, request])
        db.flush()
        request_id = request.id
        principal_a = Principal(manager_a.id, org.id, "manager", department.id)
        principal_b = Principal(manager_b.id, org.id, "manager", department.id)
        db.commit()

    barrier = Barrier(2)

    def attempt(principal: Principal) -> int:
        with postgres_factory() as db:
            barrier.wait(timeout=10)
            try:
                decide(
                    db,
                    principal,
                    request_id,
                    decision="approve",
                    expected_version=2,
                    reason=None,
                )
                db.commit()
                return 200
            except DomainError as error:
                db.rollback()
                return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [principal_a, principal_b]))

    assert sorted(results) == [200, 409]
    with postgres_factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(Approval)
                .where(Approval.procurement_id == request_id)
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(ERPIntent)
                .where(ERPIntent.procurement_id == request_id)
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.topic == "erp.create_draft")
            )
            == 1
        )


def test_expired_erp_worker_cannot_overwrite_takeover_result(postgres_factory):
    external_intent_id = f"PF-LEASE-{uuid4().hex.upper()}"
    with postgres_factory() as db:
        org = Organization(
            code=f"lease-{uuid4().hex[:8]}",
            name="Lease Test",
            currency_code="CNY",
            odoo_company_id=uuid4().int % 100000 + 1,
            odoo_currency_id=6,
        )
        db.add(org)
        db.flush()
        department = Department(organization_id=org.id, code="ops", name="Operations")
        requester = User(
            email=f"lease-requester-{uuid4().hex}@test.local",
            display_name="Lease Test Requester",
        )
        supplier = SupplierMapping(
            organization_id=org.id,
            external_ref=f"LEASE-{uuid4().hex[:8]}",
            name="Lease Test Vendor",
            odoo_partner_id=uuid4().int % 100000 + 1,
            mapping_version=1,
            active=True,
        )
        db.add_all([department, requester, supplier])
        db.flush()
        request = Procurement(
            organization_id=org.id,
            request_number=f"PR-LEASE-{uuid4().hex[:8]}",
            requester_id=requester.id,
            department_id=department.id,
            supplier_mapping_id=supplier.id,
            reason="Outbox lease takeover test",
            currency_code="CNY",
            status="approved",
            version=4,
            policy_version=1,
            amount_untaxed="1200.00",
            amount_tax="156.00",
            amount_total="1356.00",
            submitted_snapshot={"policy_version": 1},
        )
        db.add(request)
        db.flush()
        snapshot = {
            "erp_intent_id": external_intent_id,
            "odoo_partner_id": supplier.odoo_partner_id,
            "odoo_company_id": org.odoo_company_id,
            "odoo_currency_id": org.odoo_currency_id,
            "amount_untaxed": "1200.00",
            "amount_tax": "156.00",
            "amount_total": "1356.00",
            "lines": [
                {
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
            procurement_id=request.id,
            external_intent_id=external_intent_id,
            request_hash="b" * 64,
            expected_snapshot=snapshot,
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
        procurement_id = request.id
        intent_id = intent.id
        outbox_id = event.id

    def remote_order(state: str) -> dict:
        order_name = "P00077"
        return {
            "header": {
                "id": 77,
                "name": order_name,
                "partner_id": [snapshot["odoo_partner_id"], "Lease Test Vendor"],
                "company_id": [snapshot["odoo_company_id"], "Lease Test"],
                "currency_id": [snapshot["odoo_currency_id"], "CNY"],
                "state": state,
                "origin": external_intent_id,
                "purchaseflow_intent_id": external_intent_id,
                "order_line": [101],
                "amount_untaxed": 1200.0,
                "amount_tax": 156.0,
                "amount_total": 1356.0,
            },
            "lines": [
                {
                    "id": 101,
                    "order_id": [77, order_name],
                    "product_id": [1, "Lease Test Product"],
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

    read_started = Event()
    release_old_read = Event()

    class SlowExpiredWorker:
        def read_order(self, marker: str):
            read_started.set()
            if not release_old_read.wait(timeout=10):
                raise TimeoutError("The expired worker read was not released.")
            return remote_order("purchase")

        def create_purchase_order(self, source):
            raise AssertionError("The slow worker must not create from its stale response.")

    class TakeoverWorker:
        def read_order(self, marker: str):
            return remote_order("draft")

        def create_purchase_order(self, source):
            raise AssertionError("The takeover worker should verify the existing order.")

    with ThreadPoolExecutor(max_workers=1) as pool:
        old_worker = pool.submit(
            process_one,
            factory=postgres_factory,
            client=SlowExpiredWorker(),
            lease_seconds=60,
            outbox_id=outbox_id,
        )
        assert read_started.wait(timeout=10)
        with postgres_factory() as db:
            event = db.get(OutboxEvent, outbox_id)
            assert event.status == "processing"
            assert event.lease_generation == 1
            event.lease_until = utcnow() - timedelta(seconds=1)
            db.commit()

        assert process_one(
            factory=postgres_factory,
            client=TakeoverWorker(),
            lease_seconds=60,
            outbox_id=outbox_id,
        ) is True
        release_old_read.set()
        assert old_worker.result(timeout=10) is True

    with postgres_factory() as db:
        intent = db.get(ERPIntent, intent_id)
        request = db.get(Procurement, procurement_id)
        event = db.get(OutboxEvent, outbox_id)
        assert intent.state == "verified"
        assert intent.last_observation["disposition"] == "VERIFIED"
        assert intent.remote_order_id == 77
        assert request.status == "erp_verified"
        assert event.status == "done"
        assert event.lease_generation == 2
        assert event.attempts == 2
        assert event.lease_until is None
