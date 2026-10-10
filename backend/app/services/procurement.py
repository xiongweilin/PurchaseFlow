from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.auth import Principal, require_role
from app.domain import (
    Conflict,
    NotFound,
    PermissionDenied,
    ValidationFailure,
    canonical_hash,
    money,
)
from app.models import (
    Approval,
    Department,
    ERPIntent,
    Organization,
    OutboxEvent,
    PolicyConfig,
    PolicyReviewDecision,
    Procurement,
    ProcurementLine,
    ProductMapping,
    SupplierMapping,
)
from app.schemas import ProcurementBody


def _department(db: Session, organization_id: UUID, code: str) -> Department:
    row = db.execute(
        select(Department).where(
            Department.organization_id == organization_id,
            Department.code == code,
        )
    ).scalar_one_or_none()
    if row is None:
        raise ValidationFailure("The selected department is not configured.")
    return row


def _supplier(db: Session, organization_id: UUID, reference: str) -> SupplierMapping:
    row = db.execute(
        select(SupplierMapping).where(
            SupplierMapping.organization_id == organization_id,
            SupplierMapping.external_ref == reference,
            SupplierMapping.active.is_(True),
        )
    ).scalar_one_or_none()
    if row is None or row.validated_at is None:
        raise ValidationFailure("The supplier is not mapped to a validated Odoo supplier.")
    return row


def _product(db: Session, organization_id: UUID, sku: str) -> ProductMapping:
    row = db.execute(
        select(ProductMapping).where(
            ProductMapping.organization_id == organization_id,
            ProductMapping.sku == sku,
            ProductMapping.active.is_(True),
        )
    ).scalar_one_or_none()
    if row is None or row.validated_at is None:
        raise ValidationFailure(f"Product {sku!r} is not mapped to a validated Odoo product.")
    return row


def _line_values(body: ProcurementBody, mappings: list[ProductMapping]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for number, (source, mapping) in enumerate(zip(body.lines, mappings, strict=True), start=1):
        quantity = Decimal(source.quantity)
        unit_price = Decimal(source.unit_price)
        if quantity <= 0 or unit_price < 0:
            raise ValidationFailure("Quantity must be positive and unit price cannot be negative.")
        subtotal = money(quantity * unit_price)
        tax = money(subtotal * mapping.tax_rate / Decimal("100"))
        values.append(
            {
                "line_number": number,
                "product_mapping_id": mapping.id,
                "sku": mapping.sku,
                "product_name": mapping.name,
                "odoo_product_id": mapping.odoo_product_id,
                "odoo_uom_id": mapping.odoo_uom_id,
                "odoo_tax_id": mapping.odoo_tax_id,
                "quantity": quantity,
                "unit_price": unit_price,
                "tax_rate": mapping.tax_rate,
                "amount_untaxed": subtotal,
                "amount_tax": tax,
                "amount_total": subtotal + tax,
                "mapping_version": mapping.mapping_version,
            }
        )
    return values


def _replace_lines(procurement: Procurement, values: list[dict[str, Any]]) -> None:
    procurement.lines = [ProcurementLine(**value) for value in values]
    procurement.amount_untaxed = money(
        sum((line["amount_untaxed"] for line in values), Decimal("0"))
    )
    procurement.amount_tax = money(sum((line["amount_tax"] for line in values), Decimal("0")))
    procurement.amount_total = procurement.amount_untaxed + procurement.amount_tax


def create_draft(db: Session, principal: Principal, body: ProcurementBody) -> Procurement:
    require_role(principal, "requester")
    department = _department(db, principal.organization_id, body.department_code)
    if principal.department_id != department.id:
        raise PermissionDenied("A requester may create a request only for their own department.")
    supplier = _supplier(db, principal.organization_id, body.supplier_ref)
    if body.currency_code != "CNY":
        raise ValidationFailure("This demo accepts CNY purchases only.")
    mappings = [_product(db, principal.organization_id, line.sku) for line in body.lines]
    if any(mapping.currency_code != body.currency_code for mapping in mappings):
        raise ValidationFailure("Product currency does not match the request currency.")

    procurement = Procurement(
        organization_id=principal.organization_id,
        request_number=f"PR-{datetime.now(UTC):%Y%m}-{uuid.uuid4().hex[:8].upper()}",
        requester_id=principal.user_id,
        department_id=department.id,
        supplier_mapping_id=supplier.id,
        reason=body.reason.strip(),
        currency_code=body.currency_code,
        status="draft",
        version=1,
    )
    _replace_lines(procurement, _line_values(body, mappings))
    db.add(procurement)
    db.flush()
    record_audit(
        db,
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        action="procurement.created",
        resource_type="procurement",
        resource_id=str(procurement.id),
        after={"status": procurement.status, "version": procurement.version},
    )
    return procurement


def update_draft(
    db: Session,
    principal: Principal,
    procurement_id: UUID,
    body: ProcurementBody,
    expected_version: int,
) -> Procurement:
    require_role(principal, "requester")
    procurement = db.execute(
        select(Procurement)
        .where(
            Procurement.id == procurement_id,
            Procurement.organization_id == principal.organization_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if procurement is None:
        raise NotFound("Procurement request was not found.")
    if procurement.requester_id != principal.user_id:
        raise PermissionDenied("Only the requester can edit this draft.")
    if procurement.status != "draft":
        raise Conflict(
            "Submitted procurement fields are frozen; create a new request to change them."
        )
    if procurement.version != expected_version:
        raise Conflict("The draft changed; refresh before editing.")
    department = _department(db, principal.organization_id, body.department_code)
    if department.id != principal.department_id:
        raise PermissionDenied("A requester may edit only requests in their own department.")
    supplier = _supplier(db, principal.organization_id, body.supplier_ref)
    mappings = [_product(db, principal.organization_id, line.sku) for line in body.lines]
    if body.currency_code != "CNY":
        raise ValidationFailure("This demo accepts CNY purchases only.")
    before = {"version": procurement.version, "reason": procurement.reason}
    procurement.department_id = department.id
    procurement.supplier_mapping_id = supplier.id
    procurement.reason = body.reason.strip()
    procurement.currency_code = body.currency_code
    _replace_lines(procurement, _line_values(body, mappings))
    procurement.version += 1
    db.flush()
    record_audit(
        db,
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        action="procurement.draft_updated",
        resource_type="procurement",
        resource_id=str(procurement.id),
        before=before,
        after={"version": procurement.version, "reason": procurement.reason},
    )
    return procurement


def _submitted_snapshot(
    db: Session, procurement: Procurement, policy: PolicyConfig, organization: Organization
) -> dict[str, Any]:
    supplier = db.get(SupplierMapping, procurement.supplier_mapping_id)
    if supplier is None or not supplier.active or supplier.validated_at is None:
        raise ValidationFailure("The supplier mapping is not currently validated.")
    if organization.odoo_company_id is None or organization.odoo_currency_id is None:
        raise ValidationFailure("Odoo company and currency mappings are incomplete.")
    return {
        "procurement_id": str(procurement.id),
        "request_number": procurement.request_number,
        "request_version": procurement.version + 1,
        "organization_id": str(procurement.organization_id),
        "department_id": str(procurement.department_id),
        "supplier_mapping_id": str(procurement.supplier_mapping_id),
        "supplier_mapping_version": supplier.mapping_version,
        "supplier_external_ref": supplier.external_ref,
        "supplier_name": supplier.name,
        "odoo_partner_id": supplier.odoo_partner_id,
        "odoo_company_id": organization.odoo_company_id,
        "odoo_currency_id": organization.odoo_currency_id,
        "currency_code": procurement.currency_code,
        "reason": procurement.reason,
        "policy_version": policy.version,
        "manager_limit": str(policy.manager_limit),
        "policy_review_limit": str(policy.policy_review_limit),
        "tax_inclusive": policy.tax_inclusive,
        "amount_untaxed": str(procurement.amount_untaxed),
        "amount_tax": str(procurement.amount_tax),
        "amount_total": str(procurement.amount_total),
        "lines": [
            {
                "line_number": line.line_number,
                "sku": line.sku,
                "product_name": line.product_name,
                "odoo_product_id": line.odoo_product_id,
                "odoo_uom_id": line.odoo_uom_id,
                "odoo_tax_id": line.odoo_tax_id,
                "quantity": str(line.quantity),
                "unit_price": str(line.unit_price),
                "tax_rate": str(line.tax_rate),
                "amount_untaxed": str(line.amount_untaxed),
                "amount_tax": str(line.amount_tax),
                "amount_total": str(line.amount_total),
                "mapping_version": line.mapping_version,
            }
            for line in procurement.lines
        ],
    }


def submit(
    db: Session,
    principal: Principal,
    procurement_id: UUID,
    expected_version: int,
) -> Procurement:
    require_role(principal, "requester")
    procurement = db.execute(
        select(Procurement)
        .where(
            Procurement.id == procurement_id,
            Procurement.organization_id == principal.organization_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if procurement is None:
        raise NotFound("Procurement request was not found.")
    if procurement.requester_id != principal.user_id:
        raise PermissionDenied("Only the requester can submit this request.")
    if procurement.status != "draft":
        raise Conflict("Only a draft request can be submitted.")
    if procurement.version != expected_version:
        raise Conflict("The draft changed; refresh before submitting.")
    policy = db.execute(
        select(PolicyConfig).where(PolicyConfig.organization_id == principal.organization_id)
    ).scalar_one_or_none()
    if policy is None:
        raise ValidationFailure("Approval policy is not configured.")
    mappings = [_product(db, principal.organization_id, line.sku) for line in procurement.lines]
    if any(
        mapping.mapping_version != line.mapping_version
        for mapping, line in zip(mappings, procurement.lines, strict=True)
    ):
        raise Conflict("A product mapping changed; review and resubmit the draft.")
    supplier = db.get(SupplierMapping, procurement.supplier_mapping_id)
    if supplier is None or not supplier.active or supplier.validated_at is None:
        raise ValidationFailure("The supplier mapping is no longer valid.")
    old_status = procurement.status
    procurement.policy_version = policy.version
    organization = db.get(Organization, procurement.organization_id)
    if organization is None:
        raise ValidationFailure("The organization is not configured.")
    procurement.submitted_snapshot = _submitted_snapshot(db, procurement, policy, organization)
    procurement.submitted_at = datetime.now(UTC)
    procurement.version += 1
    if procurement.amount_total > policy.policy_review_limit:
        procurement.status = "policy_review"
    else:
        procurement.status = "pending_manager"
    db.flush()
    record_audit(
        db,
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        action="procurement.submitted",
        resource_type="procurement",
        resource_id=str(procurement.id),
        before={"status": old_status, "version": expected_version},
        after={
            "status": procurement.status,
            "version": procurement.version,
            "policy_version": policy.version,
            "amount_total": str(procurement.amount_total),
        },
    )
    return procurement


def _create_erp_intent(db: Session, procurement: Procurement) -> ERPIntent:
    if procurement.submitted_snapshot is None or procurement.policy_version is None:
        raise Conflict("An ERP effect requires a submitted and versioned request.")
    existing = db.execute(
        select(ERPIntent).where(ERPIntent.procurement_id == procurement.id)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    external_intent_id = f"PF-{uuid.uuid4().hex}"
    snapshot = dict(procurement.submitted_snapshot)
    snapshot["erp_intent_id"] = external_intent_id
    request_hash = canonical_hash(snapshot)
    intent = ERPIntent(
        procurement_id=procurement.id,
        external_intent_id=external_intent_id,
        request_hash=request_hash,
        expected_snapshot=snapshot,
        state="pending",
    )
    db.add(intent)
    db.flush()
    db.add(
        OutboxEvent(
            topic="erp.create_draft",
            aggregate_id=str(intent.id),
            payload_json={"erp_intent_id": str(intent.id)},
            status="pending",
        )
    )
    procurement.status = "approved"
    record_audit(
        db,
        organization_id=procurement.organization_id,
        actor_user_id=None,
        action="erp.intent_created",
        resource_type="procurement",
        resource_id=str(procurement.id),
        after={"intent_id": str(intent.id), "external_intent_id": external_intent_id},
    )
    return intent


def decide(
    db: Session,
    principal: Principal,
    procurement_id: UUID,
    *,
    decision: str,
    expected_version: int,
    reason: str | None = None,
) -> Procurement:
    if decision not in {"approve", "reject"}:
        raise ValidationFailure("Decision must be approve or reject.")
    procurement = db.execute(
        select(Procurement)
        .where(
            Procurement.id == procurement_id,
            Procurement.organization_id == principal.organization_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if procurement is None:
        raise NotFound("Procurement request was not found.")
    if procurement.version != expected_version:
        raise Conflict("The request changed; refresh before deciding.")
    if principal.user_id == procurement.requester_id:
        raise PermissionDenied("An applicant cannot approve their own request.")
    if decision == "reject" and not (reason and reason.strip()):
        raise ValidationFailure("A rejection requires a reason.")

    if procurement.status == "pending_manager":
        require_role(principal, "manager")
        if principal.department_id != procurement.department_id:
            raise PermissionDenied("Managers may decide only requests in their department.")
        stage = "manager"
    elif procurement.status == "pending_finance":
        require_role(principal, "finance")
        manager_approval = db.execute(
            select(Approval).where(
                Approval.procurement_id == procurement.id,
                Approval.stage == "manager",
                Approval.decision == "approved",
            )
        ).scalar_one_or_none()
        if manager_approval is None:
            raise Conflict("Finance review requires a recorded manager approval.")
        if manager_approval.actor_user_id == principal.user_id:
            raise PermissionDenied("The manager cannot also approve the same request as Finance.")
        stage = "finance"
    else:
        raise Conflict("The procurement request is not waiting for this approval stage.")

    if procurement.submitted_snapshot is None:
        raise Conflict("The submitted policy snapshot is missing.")
    manager_limit = Decimal(procurement.submitted_snapshot["manager_limit"])
    approval = Approval(
        procurement_id=procurement.id,
        stage=stage,
        actor_user_id=principal.user_id,
        decision="approved" if decision == "approve" else "rejected",
        reason=reason.strip() if reason else None,
        request_version=procurement.version,
    )
    db.add(approval)
    before_status = procurement.status
    if decision == "reject":
        procurement.status = "rejected"
    elif stage == "manager" and procurement.amount_total <= manager_limit:
        procurement.status = "approved"
        _create_erp_intent(db, procurement)
    elif stage == "manager":
        procurement.status = "pending_finance"
    else:
        procurement.status = "approved"
        _create_erp_intent(db, procurement)
    procurement.version += 1
    db.flush()
    record_audit(
        db,
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        action=f"procurement.{stage}_{decision}",
        resource_type="procurement",
        resource_id=str(procurement.id),
        before={"status": before_status, "version": expected_version},
        after={"status": procurement.status, "version": procurement.version},
        metadata={"reason": reason} if reason else None,
    )
    return procurement


def cancel(
    db: Session, principal: Principal, procurement_id: UUID, expected_version: int
) -> Procurement:
    require_role(principal, "requester")
    procurement = db.execute(
        select(Procurement)
        .where(
            Procurement.id == procurement_id,
            Procurement.organization_id == principal.organization_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if procurement is None:
        raise NotFound("Procurement request was not found.")
    if procurement.requester_id != principal.user_id:
        raise PermissionDenied("Only the requester can cancel this request.")
    if procurement.version != expected_version:
        raise Conflict("The request changed; refresh before cancelling.")
    if procurement.status not in {"draft", "pending_manager"}:
        raise Conflict("A request can only be cancelled before any approval is recorded.")
    if procurement.approvals:
        raise Conflict("A request cannot be cancelled after an approval decision.")
    previous = procurement.status
    procurement.status = "cancelled"
    procurement.version += 1
    db.flush()
    record_audit(
        db,
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        action="procurement.cancelled",
        resource_type="procurement",
        resource_id=str(procurement.id),
        before={"status": previous},
        after={"status": procurement.status, "version": procurement.version},
    )
    return procurement


def close(
    db: Session, principal: Principal, procurement_id: UUID, expected_version: int
) -> Procurement:
    require_role(principal, "procurement")
    procurement = db.execute(
        select(Procurement)
        .where(
            Procurement.id == procurement_id,
            Procurement.organization_id == principal.organization_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if procurement is None:
        raise NotFound("Procurement request was not found.")
    if procurement.version != expected_version:
        raise Conflict("The request changed; refresh before closing.")
    if procurement.status != "erp_verified":
        raise Conflict("Only a request with verified Odoo facts can be closed.")
    procurement.status = "closed"
    procurement.closed_at = datetime.now(UTC)
    procurement.version += 1
    db.flush()
    record_audit(
        db,
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        action="procurement.closed",
        resource_type="procurement",
        resource_id=str(procurement.id),
        before={"status": "erp_verified"},
        after={"status": "closed", "version": procurement.version},
    )
    return procurement


def update_policy(
    db: Session,
    principal: Principal,
    *,
    expected_version: int,
    manager_limit: Decimal,
    policy_review_limit: Decimal,
    tax_inclusive: bool,
) -> PolicyConfig:
    require_role(principal, "admin")
    if manager_limit < 0 or policy_review_limit <= manager_limit:
        raise ValidationFailure(
            "Policy review limit must be greater than the non-negative manager limit."
        )
    policy = db.execute(
        select(PolicyConfig)
        .where(PolicyConfig.organization_id == principal.organization_id)
        .with_for_update()
    ).scalar_one_or_none()
    if policy is None:
        raise NotFound("Approval policy is not configured.")
    if policy.version != expected_version:
        raise Conflict("The approval policy changed; refresh before updating.")
    before = {
        "version": policy.version,
        "manager_limit": str(policy.manager_limit),
        "policy_review_limit": str(policy.policy_review_limit),
        "tax_inclusive": policy.tax_inclusive,
    }
    policy.manager_limit = money(manager_limit)
    policy.policy_review_limit = money(policy_review_limit)
    policy.tax_inclusive = tax_inclusive
    policy.version += 1
    db.flush()
    record_audit(
        db,
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        action="policy.updated",
        resource_type="policy",
        resource_id=str(policy.id),
        before=before,
        after={
            "version": policy.version,
            "manager_limit": str(policy.manager_limit),
            "policy_review_limit": str(policy.policy_review_limit),
            "tax_inclusive": policy.tax_inclusive,
            "effective_for": "future_submissions",
        },
    )
    return policy


def decide_policy_review(
    db: Session,
    principal: Principal,
    procurement_id: UUID,
    *,
    decision: str,
    expected_version: int,
    reason: str,
) -> Procurement:
    require_role(principal, "admin")
    if decision not in {"approve", "reject"} or not reason.strip():
        raise ValidationFailure("A policy review decision and documented reason are required.")
    procurement = db.execute(
        select(Procurement)
        .where(
            Procurement.id == procurement_id,
            Procurement.organization_id == principal.organization_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if procurement is None:
        raise NotFound("Procurement request was not found.")
    if procurement.status != "policy_review":
        raise Conflict("The request is not waiting for a policy review.")
    if procurement.version != expected_version:
        raise Conflict("The request changed; refresh before the policy decision.")
    if principal.user_id == procurement.requester_id:
        raise PermissionDenied("A requester cannot approve their own policy exception.")
    if procurement.policy_version is None:
        raise Conflict("The request has no bound policy version.")
    current_policy = db.execute(
        select(PolicyConfig).where(PolicyConfig.organization_id == principal.organization_id)
    ).scalar_one()
    review = PolicyReviewDecision(
        procurement_id=procurement.id,
        actor_user_id=principal.user_id,
        decision="approved" if decision == "approve" else "rejected",
        reason=reason.strip(),
        policy_version=procurement.policy_version,
        request_version=procurement.version,
    )
    db.add(review)
    previous = procurement.status
    procurement.status = "pending_manager" if decision == "approve" else "rejected"
    procurement.version += 1
    db.flush()
    record_audit(
        db,
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        action=f"policy.review_{decision}",
        resource_type="procurement",
        resource_id=str(procurement.id),
        before={"status": previous, "policy_version": procurement.policy_version},
        after={
            "status": procurement.status,
            "version": procurement.version,
            "review_policy_version": current_policy.version,
        },
        metadata={
            "reason": reason.strip(),
            "approval_stages_still_required": decision == "approve",
        },
    )
    return procurement
