from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
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
)
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
