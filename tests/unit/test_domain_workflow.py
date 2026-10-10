from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import Approval, AuditEvent, ERPIntent, IdempotencyRecord, OutboxEvent, Procurement


def _draft(
    client,
    login,
    *,
    email="requester.admin@demo.local",
    department="admin",
    sku="PF-OFFICE-SET",
    quantity="1",
    price="1200.00",
):
    login("requester", email, department)
    response = client.post(
        "/api/procurements",
        json={
            "department_code": department,
            "supplier_ref": "PF-VENDOR-IT" if sku == "PF-IT-MONITOR" else "PF-VENDOR-OFFICE",
            "reason": "Unit test purchase request with a documented business need",
            "currency_code": "CNY",
            "lines": [{"sku": sku, "quantity": quantity, "unit_price": price}],
        },
        headers={"Idempotency-Key": f"create-{email}-{sku}-{quantity}-{price}"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_create_idempotency_replays_and_rejects_changed_content(authorized_client, session_factory):
    client, login = authorized_client
    login("requester", "requester.admin@demo.local", "admin")
    body = {
        "department_code": "admin",
        "supplier_ref": "PF-VENDOR-OFFICE",
        "reason": "Repeated event must not create a second procurement request",
        "currency_code": "CNY",
        "lines": [{"sku": "PF-OFFICE-SET", "quantity": "1", "unit_price": "1200.00"}],
    }
    headers = {"Idempotency-Key": "same-create-event"}
    first = client.post("/api/procurements", json=body, headers=headers)
    replay = client.post("/api/procurements", json=body, headers=headers)
    changed = {**body, "lines": [{"sku": "PF-OFFICE-SET", "quantity": "1", "unit_price": "1300.00"}]}
    conflict = client.post("/api/procurements", json=changed, headers=headers)

    assert first.status_code == 200
    assert replay.status_code == 200 and replay.json()["id"] == first.json()["id"]
    assert conflict.status_code == 409
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Procurement)) == 1
        assert db.scalar(select(func.count()).select_from(IdempotencyRecord)) == 1


def test_manager_department_and_request_version_are_enforced(authorized_client, session_factory):
    client, login = authorized_client
    draft = _draft(client, login, email="requester.ops@demo.local", department="operations")
    submitted = client.post(
        f"/api/procurements/{draft['id']}/submit",
        json={"expected_version": draft["version"]},
    )
    assert submitted.status_code == 200

    login("manager", "manager.admin@demo.local", "admin")
    cross_department = client.post(
        f"/api/procurements/{draft['id']}/decision",
        json={"decision": "approve", "expected_version": submitted.json()["version"]},
        headers={"Idempotency-Key": f"cross-department-{draft['id']}"},
    )
    assert cross_department.status_code == 403

    login("manager", "manager.ops@demo.local", "operations")
    stale_version = client.post(
        f"/api/procurements/{draft['id']}/decision",
        json={"decision": "approve", "expected_version": submitted.json()["version"] - 1},
        headers={"Idempotency-Key": f"stale-version-{draft['id']}"},
    )
    assert stale_version.status_code == 409
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Approval)) == 0
        assert db.scalar(select(func.count()).select_from(ERPIntent)) == 0


@pytest.mark.parametrize("outcome", ["reject", "cancel"])
def test_rejection_and_cancellation_never_create_erp_work(outcome, authorized_client, session_factory):
    client, login = authorized_client
    draft = _draft(client, login)
    submitted = client.post(
        f"/api/procurements/{draft['id']}/submit",
        json={"expected_version": draft["version"]},
    )
    assert submitted.status_code == 200
    version = submitted.json()["version"]
    if outcome == "cancel":
        response = client.post(
            f"/api/procurements/{draft['id']}/cancel", json={"expected_version": version}
        )
        assert response.status_code == 200 and response.json()["status"] == "cancelled"
    else:
        login("manager", "manager.admin@demo.local", "admin")
        response = client.post(
            f"/api/procurements/{draft['id']}/decision",
            json={"decision": "reject", "expected_version": version, "reason": "Not approved."},
            headers={"Idempotency-Key": f"reject-{draft['id']}"},
        )
        assert response.status_code == 200 and response.json()["status"] == "rejected"

    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(ERPIntent)) == 0
        assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 0


def test_requester_draft_submission_and_manager_only_flow(authorized_client, session_factory):
    client, login = authorized_client
    draft = _draft(client, login)
    assert draft["status"] == "draft"
    assert draft["amount_untaxed"] == "1200.00"
    assert draft["amount_tax"] == "156.00"
    assert draft["amount_total"] == "1356.00"

    submitted = client.post(
        f"/api/procurements/{draft['id']}/submit",
        json={"expected_version": draft["version"]},
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "pending_manager"
    assert submitted.json()["currency_code"] == "CNY"
    assert submitted.json()["policy_version"] == 1

    locked_edit = client.patch(
        f"/api/procurements/{draft['id']}",
        json={
            "department_code": "admin",
            "supplier_ref": "PF-VENDOR-OFFICE",
            "reason": "Attempt to change frozen approval facts",
            "currency_code": "CNY",
            "lines": [{"sku": "PF-OFFICE-SET", "quantity": "1", "unit_price": "1.00"}],
            "expected_version": submitted.json()["version"],
        },
    )
    assert locked_edit.status_code == 409

    login("manager", "manager.admin@demo.local", "admin")
    body = {"decision": "approve", "expected_version": submitted.json()["version"]}
    decision = client.post(
        f"/api/procurements/{draft['id']}/decision",
        json=body,
        headers={"Idempotency-Key": f"manager-decision-{draft['id']}"},
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["status"] == "approved"

    replay = client.post(
        f"/api/procurements/{draft['id']}/decision",
        json=body,
        headers={"Idempotency-Key": f"manager-decision-{draft['id']}"},
    )
    assert replay.status_code == 200
    assert replay.json()["id"] == draft["id"]

    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(ERPIntent)) == 1
        assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 1
        assert db.scalar(select(func.count()).select_from(Approval)) == 1
        assert db.scalar(select(func.count()).select_from(AuditEvent)) >= 4
        assert db.scalar(select(func.count()).select_from(IdempotencyRecord)) == 2


def test_requester_cannot_approve_own_request_even_with_manager_membership(authorized_client):
    client, login = authorized_client
    draft = _draft(client, login, email="dual-role@demo.local")
    submitted = client.post(
        f"/api/procurements/{draft['id']}/submit",
        json={"expected_version": draft["version"]},
    )
    assert submitted.status_code == 200

    login("manager", "dual-role@demo.local", "admin")
    response = client.post(
        f"/api/procurements/{draft['id']}/decision",
        json={"decision": "approve", "expected_version": submitted.json()["version"]},
        headers={"Idempotency-Key": f"self-approval-{draft['id']}"},
    )
    assert response.status_code == 403


def test_high_value_requires_distinct_finance_approver(authorized_client, session_factory):
    client, login = authorized_client
    draft = _draft(
        client,
        login,
        email="requester.ops@demo.local",
        department="operations",
        sku="PF-IT-MONITOR",
        quantity="2",
        price="4000.00",
    )
    submitted = client.post(
        f"/api/procurements/{draft['id']}/submit",
        json={"expected_version": draft["version"]},
    )
    assert submitted.status_code == 200
    assert submitted.json()["amount_total"] == "9040.00"

    login("manager", "manager.ops@demo.local", "operations")
    manager_result = client.post(
        f"/api/procurements/{draft['id']}/decision",
        json={"decision": "approve", "expected_version": submitted.json()["version"]},
        headers={"Idempotency-Key": f"manager-{draft['id']}"},
    )
    assert manager_result.status_code == 200
    assert manager_result.json()["status"] == "pending_finance"

    same_manager = client.post(
        f"/api/procurements/{draft['id']}/decision",
        json={"decision": "approve", "expected_version": manager_result.json()["version"]},
        headers={"Idempotency-Key": f"same-manager-finance-{draft['id']}"},
    )
    assert same_manager.status_code == 403

    login("finance", "finance.one@demo.local")
    finance_result = client.post(
        f"/api/procurements/{draft['id']}/decision",
        json={"decision": "approve", "expected_version": manager_result.json()["version"]},
        headers={"Idempotency-Key": f"finance-{draft['id']}"},
    )
    assert finance_result.status_code == 200
    assert finance_result.json()["status"] == "approved"

    with session_factory() as db:
        approvals = db.scalars(
            select(Approval).where(Approval.procurement_id == __import__("uuid").UUID(draft["id"]))
        ).all()
        assert {row.stage for row in approvals} == {"manager", "finance"}
        assert len({row.actor_user_id for row in approvals}) == 2


def test_policy_review_has_no_automatic_erp_effect(authorized_client, session_factory):
    client, login = authorized_client
    draft = _draft(
        client,
        login,
        email="requester.ops@demo.local",
        department="operations",
        sku="PF-IT-MONITOR",
        quantity="5",
        price="4000.00",
    )
    submitted = client.post(
        f"/api/procurements/{draft['id']}/submit",
        json={"expected_version": draft["version"]},
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "policy_review"
    assert submitted.json()["amount_total"] == "22600.00"

    login("manager", "manager.ops@demo.local", "operations")
    blocked = client.post(
        f"/api/procurements/{draft['id']}/decision",
        json={"decision": "approve", "expected_version": submitted.json()["version"]},
        headers={"Idempotency-Key": f"policy-gate-{draft['id']}"},
    )
    assert blocked.status_code == 409

    with session_factory() as db:
        request = db.get(Procurement, __import__("uuid").UUID(draft["id"]))
        assert request is not None and request.status == "policy_review"
        assert db.scalar(select(func.count()).select_from(ERPIntent)) == 0
        assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 0


def test_admin_policy_review_is_explicit_and_keeps_manager_finance_steps(
    authorized_client, session_factory
):
    client, login = authorized_client
    draft = _draft(
        client,
        login,
        email="requester.ops@demo.local",
        department="operations",
        sku="PF-IT-MONITOR",
        quantity="5",
        price="4000.00",
    )
    submitted = client.post(
        f"/api/procurements/{draft['id']}/submit",
        json={"expected_version": draft["version"]},
    )
    assert submitted.status_code == 200
    login("admin", "admin@demo.local")

    override = client.post(
        f"/api/procurements/{draft['id']}/policy-review",
        json={
            "decision": "approve",
            "expected_version": submitted.json()["version"],
            "reason": "Documented exception approved for the demo purchase policy.",
        },
    )
    assert override.status_code == 200, override.text
    assert override.json()["status"] == "pending_manager"
    assert override.json()["policy_review"]["decision"] == "approved"
    assert override.json()["allowed_actions"] == []

    with session_factory() as db:
        request = db.get(Procurement, __import__("uuid").UUID(draft["id"]))
        assert request is not None
        assert request.status == "pending_manager"
        assert db.scalar(select(func.count()).select_from(ERPIntent)) == 0
        assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 0


def test_procurement_reconcile_is_read_only_and_retry_reuses_same_intent(
    authorized_client, session_factory, monkeypatch
):
    import app.main

    client, login = authorized_client
    draft = _draft(client, login)
    submitted = client.post(
        f"/api/procurements/{draft['id']}/submit",
        json={"expected_version": draft["version"]},
    )
    assert submitted.status_code == 200
    login("manager", "manager.admin@demo.local", "admin")
    approved = client.post(
        f"/api/procurements/{draft['id']}/decision",
        json={"decision": "approve", "expected_version": submitted.json()["version"]},
        headers={"Idempotency-Key": f"dispatch-{draft['id']}"},
    )
    assert approved.status_code == 200

    with session_factory() as db:
        request = db.get(Procurement, __import__("uuid").UUID(draft["id"]))
        intent = db.scalar(select(ERPIntent).where(ERPIntent.procurement_id == request.id))
        event = db.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == str(intent.id)))
        external_id = intent.external_intent_id
        request.status = "erp_unknown"
        intent.state = "unknown"
        intent.last_observation = {
            "disposition": "UNKNOWN",
            "write_attempted": True,
        }
        event.status = "done"
        db.commit()

    class ReadOnlyOdoo:
        calls = 0

        def read_order(self, marker):
            self.calls += 1
            assert marker == external_id
            return None

        def close(self):
            return None

    fake_odoo = ReadOnlyOdoo()
    monkeypatch.setattr(app.main, "OdooJSON2Client", lambda: fake_odoo)
    login("procurement", "procurement@demo.local")
    reconciled = client.post(f"/api/procurements/{draft['id']}/reconcile")
    assert reconciled.status_code == 200
    assert reconciled.json()["status"] == "erp_unknown"
    assert reconciled.json()["erp"]["observation"]["disposition"] == "ABSENT"
    assert fake_odoo.calls == 1

    retried = client.post(f"/api/procurements/{draft['id']}/retry")
    assert retried.status_code == 200
    assert retried.json()["status"] == "erp_pending"
    assert retried.json()["erp"]["external_intent_id"] == external_id
    assert fake_odoo.calls == 2

    with session_factory() as db:
        request = db.get(Procurement, __import__("uuid").UUID(draft["id"]))
        intent = db.scalar(select(ERPIntent).where(ERPIntent.procurement_id == request.id))
        event = db.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == str(intent.id)))
        assert intent.external_intent_id == external_id
        assert intent.state == "pending"
        assert request.status == "erp_pending"
        assert event.status == "pending"
        assert db.scalar(select(func.count()).select_from(ERPIntent)) == 1
        assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 1
