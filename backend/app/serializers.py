from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import Principal
from app.models import (
    Approval,
    AuditEvent,
    Department,
    ERPIntent,
    PolicyReviewDecision,
    Procurement,
)


def procurement_view(
    db: Session, procurement: Procurement, principal: Principal | None = None
) -> dict:
    department = db.get(Department, procurement.department_id)
    requester = procurement.requester
    supplier = procurement.supplier
    approvals = (
        db.execute(
            select(Approval)
            .where(Approval.procurement_id == procurement.id)
            .order_by(Approval.decided_at, Approval.stage)
        )
        .scalars()
        .all()
    )
    erp = db.execute(
        select(ERPIntent).where(ERPIntent.procurement_id == procurement.id)
    ).scalar_one_or_none()
    policy_review = db.execute(
        select(PolicyReviewDecision).where(PolicyReviewDecision.procurement_id == procurement.id)
    ).scalar_one_or_none()
    erp_view = None
    if erp is not None:
        privileged_erp = principal is not None and principal.role in {
            "finance",
            "procurement",
            "admin",
        }
        observation = erp.last_observation
        if observation and not privileged_erp:
            observation = {
                "disposition": observation.get("disposition"),
                "observed_at": observation.get("observed_at"),
            }
        erp_view = {
            "state": erp.state,
            "remote_order_name": erp.remote_order_name,
            "attempts": erp.attempts,
            "observation": observation,
            "observed_at": erp.observed_at.isoformat() if erp.observed_at else None,
        }
        if privileged_erp:
            erp_view.update(
                {
                    "intent_id": str(erp.id),
                    "external_intent_id": erp.external_intent_id,
                    "remote_order_id": erp.remote_order_id,
                    "last_error": erp.last_error,
                }
            )
    events = (
        db.execute(
            select(AuditEvent)
            .where(
                AuditEvent.organization_id == procurement.organization_id,
                AuditEvent.resource_type == "procurement",
                AuditEvent.resource_id == str(procurement.id),
            )
            .order_by(AuditEvent.occurred_at)
        )
        .scalars()
        .all()
    )

    actions: list[str] = []
    if principal is not None:
        if (
            principal.role == "requester"
            and principal.user_id == procurement.requester_id
            and procurement.status == "draft"
        ):
            actions = ["edit", "submit", "cancel"]
        elif (
            principal.role == "manager"
            and principal.department_id == procurement.department_id
            and procurement.status == "pending_manager"
            and principal.user_id != procurement.requester_id
        ):
            actions = ["approve", "reject"]
        elif (
            principal.role == "finance"
            and procurement.status == "pending_finance"
            and principal.user_id != procurement.requester_id
        ):
            manager = next((item for item in approvals if item.stage == "manager"), None)
            if manager is not None and manager.actor_user_id != principal.user_id:
                actions = ["approve", "reject"]
        elif principal.role in {"finance", "procurement"} and procurement.status in {
            "erp_pending",
            "erp_unavailable",
            "erp_unknown",
            "erp_mismatch",
            "erp_failed",
        }:
            actions = ["reconcile"]
            if principal.role == "procurement":
                actions.append("retry")
        elif principal.role == "admin" and procurement.status == "policy_review":
            actions = ["policy_review"]
        elif principal.role == "procurement" and procurement.status == "erp_verified":
            actions = ["close"]

    return {
        "id": str(procurement.id),
        "request_number": procurement.request_number,
        "department": {
            "id": str(department.id) if department else None,
            "code": department.code if department else None,
            "name": department.name if department else None,
        },
        "requester": {
            "id": str(requester.id),
            "email": requester.email,
            "name": requester.display_name,
        },
        "supplier": {
            "id": str(supplier.id),
            "reference": supplier.external_ref,
            "name": supplier.name,
            "odoo_partner_id": supplier.odoo_partner_id,
        },
        "reason": procurement.reason,
        "currency_code": procurement.currency_code,
        "status": procurement.status,
        "version": procurement.version,
        "policy_version": procurement.policy_version,
        "amount_untaxed": str(procurement.amount_untaxed),
        "amount_tax": str(procurement.amount_tax),
        "amount_total": str(procurement.amount_total),
        "lines": [
            {
                "id": str(line.id),
                "line_number": line.line_number,
                "sku": line.sku,
                "product_name": line.product_name,
                "quantity": str(line.quantity),
                "unit_price": str(line.unit_price),
                "tax_rate": str(line.tax_rate),
                "amount_untaxed": str(line.amount_untaxed),
                "amount_tax": str(line.amount_tax),
                "amount_total": str(line.amount_total),
                "currency_code": procurement.currency_code,
            }
            for line in procurement.lines
        ],
        "policy_review": (
            {
                "decision": policy_review.decision,
                "actor": policy_review.actor.display_name,
                "reason": policy_review.reason,
                "policy_version": policy_review.policy_version,
                "decided_at": policy_review.decided_at.isoformat(),
            }
            if policy_review
            else None
        ),
        "approvals": [
            {
                "stage": approval.stage,
                "actor": approval.actor.display_name,
                "actor_id": str(approval.actor_user_id),
                "decision": approval.decision,
                "reason": approval.reason,
                "request_version": approval.request_version,
                "decided_at": approval.decided_at.isoformat(),
            }
            for approval in approvals
        ],
        "erp": erp_view,
        "audit_events": [
            {
                "action": event.action,
                "actor_user_id": str(event.actor_user_id) if event.actor_user_id else None,
                "before": event.before_json,
                "after": event.after_json,
                "metadata": event.metadata_json,
                "occurred_at": event.occurred_at.isoformat(),
            }
            for event in events
        ],
        "created_at": procurement.created_at.isoformat(),
        "updated_at": procurement.updated_at.isoformat(),
        "closed_at": procurement.closed_at.isoformat() if procurement.closed_at else None,
        "allowed_actions": actions,
    }


def visible_procurements(db: Session, principal: Principal) -> list[Procurement]:
    query = select(Procurement).where(Procurement.organization_id == principal.organization_id)
    if principal.role == "requester":
        query = query.where(Procurement.requester_id == principal.user_id)
    elif principal.role == "manager":
        query = query.where(Procurement.department_id == principal.department_id)
    elif principal.role not in {"finance", "procurement", "admin"}:
        return []
    return list(db.execute(query.order_by(Procurement.created_at.desc())).scalars().all())


def find_visible_procurement(
    db: Session, principal: Principal, procurement_id: UUID
) -> Procurement | None:
    query = select(Procurement).where(
        Procurement.id == procurement_id,
        Procurement.organization_id == principal.organization_id,
    )
    if principal.role == "requester":
        query = query.where(Procurement.requester_id == principal.user_id)
    elif principal.role == "manager":
        query = query.where(Procurement.department_id == principal.department_id)
    elif principal.role not in {"finance", "procurement", "admin"}:
        return None
    return db.execute(query).scalar_one_or_none()
