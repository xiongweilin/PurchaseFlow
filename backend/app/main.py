from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.auth import (
    Principal,
    create_demo_session,
    extract_bearer,
    require_demo_mode,
    require_role,
    resolve_demo_principal,
    resolve_service_principal,
)
from app.config import settings
from app.db import get_db
from app.domain import (
    AuthenticationError,
    DomainError,
    NotFound,
    ValidationFailure,
)
from app.idempotency import claim
from app.models import (
    DemoSession,
    Department,
    Membership,
    Organization,
    PolicyConfig,
    Procurement,
    ProductMapping,
    SupplierMapping,
    User,
)
from app.odoo import OdooJSON2Client
from app.schemas import (
    DecisionBody,
    DemoSessionIn,
    IntakeBody,
    PolicyReviewBody,
    PolicyUpdateIn,
    ProcurementBody,
    SubmitBody,
    UpdateProcurementIn,
)
from app.serializers import find_visible_procurement, procurement_view, visible_procurements
from app.services.erp import authorize_manual_retry, reconcile_manually
from app.services.procurement import (
    cancel,
    close,
    create_draft,
    decide,
    decide_policy_review,
    submit,
    update_draft,
    update_policy,
)

app = FastAPI(title="PurchaseFlow API", version="0.1.0")
DB = Annotated[Session, Depends(get_db)]


@app.exception_handler(DomainError)
async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message, "details": exc.details},
    )


def current_principal(request: Request, db: DB) -> Principal:
    token = request.cookies.get("purchaseflow_session")
    if not token:
        raise AuthenticationError()
    return resolve_demo_principal(db, token)


def automation_principal(request: Request, db: DB) -> Principal:
    principal = resolve_service_principal(db, extract_bearer(request))
    require_role(principal, "automation")
    return principal


PrincipalDep = Annotated[Principal, Depends(current_principal)]
AutomationDep = Annotated[Principal, Depends(automation_principal)]


@app.get("/health")
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def readiness(db: DB) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ready"}


@app.get("/api/demo/identities")
def demo_identities(db: DB) -> list[dict]:
    require_demo_mode()
    rows = db.execute(
        select(Membership, User, Department)
        .join(User, User.id == Membership.user_id)
        .outerjoin(Department, Department.id == Membership.department_id)
        .join(Organization, Organization.id == Membership.organization_id)
        .where(Organization.code == "demo-office", User.active.is_(True))
        .order_by(Membership.role, Department.code, User.email)
    ).all()
    return [
        {
            "email": user.email,
            "name": user.display_name,
            "role": membership.role,
            "department_code": department.code if department else None,
            "department_name": department.name if department else None,
        }
        for membership, user, department in rows
        if membership.role not in {"automation"}
    ]


@app.post("/api/demo/sessions")
def start_demo_session(body: DemoSessionIn, response: Response, db: DB) -> dict:
    require_demo_mode()
    if body.role == "admin":
        # 管理员可以管理演示配置，但不获得审批权限。
        pass
    query = (
        select(Membership, User, Department)
        .join(User, User.id == Membership.user_id)
        .outerjoin(Department, Department.id == Membership.department_id)
        .join(Organization, Organization.id == Membership.organization_id)
        .where(
            Organization.code == "demo-office",
            Membership.role == body.role,
            User.active.is_(True),
        )
    )
    if body.email:
        query = query.where(User.email == body.email)
    if body.department_code:
        query = query.where(Department.code == body.department_code)
    rows = db.execute(query.order_by(User.email)).all()
    if not rows:
        raise NotFound("No active demo identity matches the selected role and department.")
    membership, user, department = rows[0]
    organization = db.get(Organization, membership.organization_id)
    if organization is None:
        raise NotFound("Demo organization is not initialized.")
    row, token = create_demo_session(
        db,
        role=membership.role,
        department_id=membership.department_id,
        user_id=user.id,
        organization_id=organization.id,
    )
    db.commit()
    response.set_cookie(
        key="purchaseflow_session",
        value=token,
        httponly=True,
        secure=False,
        samesite="strict",
        max_age=settings.session_ttl_seconds,
        path="/",
    )
    return {
        "user_id": str(user.id),
        "display_name": user.display_name,
        "email": user.email,
        "role": membership.role,
        "department_code": department.code if department else None,
        "department_name": department.name if department else None,
        "expires_in_seconds": settings.session_ttl_seconds,
    }


@app.delete("/api/demo/sessions")
def end_demo_session(request: Request, response: Response, db: DB) -> dict[str, bool]:
    token = request.cookies.get("purchaseflow_session")
    if token:
        row = db.execute(
            select(DemoSession).where(
                DemoSession.token_hash == __import__("hashlib").sha256(token.encode()).hexdigest()
            )
        ).scalar_one_or_none()
        if row:
            db.delete(row)
            db.commit()
    response.delete_cookie("purchaseflow_session", path="/", samesite="strict")
    return {"signed_out": True}


@app.get("/api/me")
def me(principal: PrincipalDep, db: DB) -> dict:
    if principal.user_id is None:
        raise AuthenticationError()
    user = db.get(User, principal.user_id)
    if user is None or not user.active:
        raise AuthenticationError()
    department = db.get(Department, principal.department_id) if principal.department_id else None
    return {
        "user_id": str(user.id),
        "email": user.email,
        "name": user.display_name,
        "role": principal.role,
        "department_code": department.code if department else None,
        "department_name": department.name if department else None,
    }


@app.get("/api/overview")
def overview(principal: PrincipalDep, db: DB) -> dict:
    requests = visible_procurements(db, principal)
    counts: dict[str, int] = {}
    for item in requests:
        counts[item.status] = counts.get(item.status, 0) + 1
    attention = [
        procurement_view(db, item, principal)
        for item in requests
        if item.status
        in {"pending_manager", "pending_finance", "erp_unknown", "erp_mismatch", "erp_failed"}
    ][:20]
    return {"total": len(requests), "by_status": counts, "attention": attention}


@app.get("/api/procurements")
def list_procurements(principal: PrincipalDep, db: DB) -> list[dict]:
    return [procurement_view(db, item, principal) for item in visible_procurements(db, principal)]


@app.post("/api/procurements")
def create_procurement(
    body: ProcurementBody,
    principal: PrincipalDep,
    db: DB,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict:
    key_claim = None
    if idempotency_key:
        key_claim = claim(
            db,
            organization_id=principal.organization_id,
            scope=f"procurement.create:{principal.user_id}",
            key=idempotency_key,
            request=body.model_dump(mode="json"),
        )
        if key_claim.replay:
            procurement_id = UUID(key_claim.replay["procurement_id"])
            procurement = find_visible_procurement(db, principal, procurement_id)
            if procurement is None:
                raise NotFound("Idempotent request points to a request that is no longer visible.")
            return procurement_view(db, procurement, principal)
    procurement = create_draft(db, principal, body)
    db.flush()
    if key_claim and key_claim.record:
        key_claim.record.response_json = {"procurement_id": str(procurement.id)}
    db.commit()
    return procurement_view(db, procurement, principal)


@app.get("/api/procurements/{procurement_id}")
def get_procurement(procurement_id: UUID, principal: PrincipalDep, db: DB) -> dict:
    procurement = find_visible_procurement(db, principal, procurement_id)
    if procurement is None:
        raise NotFound("Procurement request was not found.")
    return procurement_view(db, procurement, principal)


@app.patch("/api/procurements/{procurement_id}")
def edit_procurement(
    procurement_id: UUID,
    body: UpdateProcurementIn,
    principal: PrincipalDep,
    db: DB,
) -> dict:
    procurement = update_draft(
        db,
        principal,
        procurement_id,
        body,
        expected_version=body.expected_version,
    )
    db.commit()
    return procurement_view(db, procurement, principal)


@app.post("/api/procurements/{procurement_id}/submit")
def submit_procurement(
    procurement_id: UUID,
    body: SubmitBody,
    principal: PrincipalDep,
    db: DB,
) -> dict:
    procurement = submit(db, principal, procurement_id, body.expected_version)
    db.commit()
    return procurement_view(db, procurement, principal)


@app.post("/api/procurements/{procurement_id}/decision")
def decide_procurement(
    procurement_id: UUID,
    body: DecisionBody,
    principal: PrincipalDep,
    db: DB,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict:
    key_claim = claim(
        db,
        organization_id=principal.organization_id,
        scope=f"procurement.decision:{procurement_id}",
        key=idempotency_key,
        request=body.model_dump(mode="json"),
    )
    if key_claim.replay:
        procurement = find_visible_procurement(db, principal, procurement_id)
        if procurement is None:
            raise NotFound("Procurement request was not found.")
        return procurement_view(db, procurement, principal)
    procurement = decide(
        db,
        principal,
        procurement_id,
        decision=body.decision,
        expected_version=body.expected_version,
        reason=body.reason,
    )
    if key_claim.record:
        key_claim.record.response_json = {"procurement_id": str(procurement.id)}
    db.commit()
    return procurement_view(db, procurement, principal)


@app.post("/api/procurements/{procurement_id}/cancel")
def cancel_procurement(
    procurement_id: UUID,
    body: SubmitBody,
    principal: PrincipalDep,
    db: DB,
) -> dict:
    procurement = cancel(db, principal, procurement_id, body.expected_version)
    db.commit()
    return procurement_view(db, procurement, principal)


@app.post("/api/procurements/{procurement_id}/close")
def close_procurement(
    procurement_id: UUID,
    body: SubmitBody,
    principal: PrincipalDep,
    db: DB,
) -> dict:
    procurement = close(db, principal, procurement_id, body.expected_version)
    db.commit()
    return procurement_view(db, procurement, principal)


@app.post("/api/procurements/{procurement_id}/reconcile")
def reconcile_erp(procurement_id: UUID, principal: PrincipalDep, db: DB) -> dict:
    client = OdooJSON2Client()
    try:
        procurement = reconcile_manually(db, principal, procurement_id, client)
    finally:
        client.close()
    return procurement_view(db, procurement, principal)


@app.post("/api/procurements/{procurement_id}/retry")
def retry_erp(procurement_id: UUID, principal: PrincipalDep, db: DB) -> dict:
    client = OdooJSON2Client()
    try:
        procurement = authorize_manual_retry(db, principal, procurement_id, client)
    finally:
        client.close()
    return procurement_view(db, procurement, principal)


@app.post("/api/integrations/procurements")
def create_from_automation(
    body: IntakeBody,
    principal: AutomationDep,
    request: Request,
    db: DB,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict:
    if idempotency_key != body.external_event_id:
        raise ValidationFailure("Idempotency-Key must match external_event_id.")
    key_claim = claim(
        db,
        organization_id=principal.organization_id,
        scope="automation.procurement-intake",
        key=idempotency_key,
        request=body.model_dump(mode="json"),
    )
    if key_claim.replay:
        procurement_id = UUID(key_claim.replay["procurement_id"])
        item = db.execute(
            select(Procurement).where(
                Procurement.id == procurement_id,
                Procurement.organization_id == principal.organization_id,
            )
        ).scalar_one_or_none()
        if item is None:
            raise NotFound("The replayed intake request no longer exists.")
        return procurement_view(db, item, principal)

    department = db.execute(
        select(Department).where(
            Department.organization_id == principal.organization_id,
            Department.code == body.department_code,
        )
    ).scalar_one_or_none()
    if department is None:
        raise ValidationFailure("Unknown department.")
    requester = db.execute(
        select(User)
        .join(Membership, Membership.user_id == User.id)
        .where(
            User.email == body.requester_email,
            User.active.is_(True),
            Membership.organization_id == principal.organization_id,
            Membership.role == "requester",
            Membership.department_id == department.id,
        )
    ).scalar_one_or_none()
    if requester is None:
        raise ValidationFailure("The external requester must map to an active requester identity.")
    delegated = Principal(
        user_id=requester.id,
        organization_id=principal.organization_id,
        role="requester",
        department_id=department.id,
    )
    request_body = ProcurementBody(
        department_code=body.department_code,
        supplier_ref=body.supplier_ref,
        reason=body.reason,
        currency_code="CNY",
        lines=body.lines,
    )
    item = create_draft(db, delegated, request_body)
    db.flush()
    item = submit(db, delegated, item.id, item.version)
    if key_claim.record:
        key_claim.record.response_json = {"procurement_id": str(item.id)}
    db.commit()
    return procurement_view(db, item, principal)


@app.get("/api/integrations/summary")
def automation_summary(principal: AutomationDep, db: DB) -> dict:
    counts = dict(
        db.execute(
            select(Procurement.status, func.count(Procurement.id))
            .where(Procurement.organization_id == principal.organization_id)
            .group_by(Procurement.status)
        ).all()
    )
    attention = (
        db.execute(
            select(Procurement)
            .where(
                Procurement.organization_id == principal.organization_id,
                Procurement.status.in_(
                    [
                        "pending_manager",
                        "pending_finance",
                        "erp_unknown",
                        "erp_mismatch",
                        "erp_failed",
                    ]
                ),
            )
            .order_by(Procurement.created_at)
            .limit(100)
        )
        .scalars()
        .all()
    )
    return {
        "counts": counts,
        "attention": [
            {
                "request_number": item.request_number,
                "status": item.status,
                "amount_total": str(item.amount_total),
                "currency_code": item.currency_code,
                "created_at": item.created_at.isoformat(),
            }
            for item in attention
        ],
    }


@app.get("/api/catalog")
def catalog(principal: PrincipalDep, db: DB) -> dict:
    require_role(principal, "requester", "manager", "finance", "procurement", "admin")
    suppliers = (
        db.execute(
            select(SupplierMapping)
            .where(
                SupplierMapping.organization_id == principal.organization_id,
                SupplierMapping.active.is_(True),
            )
            .order_by(SupplierMapping.name)
        )
        .scalars()
        .all()
    )
    products = (
        db.execute(
            select(ProductMapping)
            .where(
                ProductMapping.organization_id == principal.organization_id,
                ProductMapping.active.is_(True),
            )
            .order_by(ProductMapping.name)
        )
        .scalars()
        .all()
    )
    return {
        "currency_code": "CNY",
        "suppliers": [{"reference": row.external_ref, "name": row.name} for row in suppliers],
        "products": [
            {
                "sku": row.sku,
                "name": row.name,
                "unit_price": str(row.unit_price),
                "tax_rate": str(row.tax_rate),
                "currency_code": row.currency_code,
            }
            for row in products
        ],
    }


@app.get("/api/admin/policy")
def get_policy(principal: PrincipalDep, db: DB) -> dict:
    require_role(principal, "admin")
    policy = db.execute(
        select(PolicyConfig).where(PolicyConfig.organization_id == principal.organization_id)
    ).scalar_one_or_none()
    if policy is None:
        raise NotFound("Approval policy is not configured.")
    return {
        "version": policy.version,
        "manager_limit": str(policy.manager_limit),
        "policy_review_limit": str(policy.policy_review_limit),
        "tax_inclusive": policy.tax_inclusive,
        "currency_code": "CNY",
    }


@app.put("/api/admin/policy")
def put_policy(body: PolicyUpdateIn, principal: PrincipalDep, db: DB) -> dict:
    policy = update_policy(
        db,
        principal,
        expected_version=body.expected_version,
        manager_limit=body.manager_limit,
        policy_review_limit=body.policy_review_limit,
        tax_inclusive=body.tax_inclusive,
    )
    db.commit()
    return {
        "version": policy.version,
        "manager_limit": str(policy.manager_limit),
        "policy_review_limit": str(policy.policy_review_limit),
        "tax_inclusive": policy.tax_inclusive,
        "currency_code": "CNY",
    }


@app.post("/api/procurements/{procurement_id}/policy-review")
def review_policy_exception(
    procurement_id: UUID,
    body: PolicyReviewBody,
    principal: PrincipalDep,
    db: DB,
) -> dict:
    procurement = decide_policy_review(
        db,
        principal,
        procurement_id,
        decision=body.decision,
        expected_version=body.expected_version,
        reason=body.reason,
    )
    db.commit()
    return procurement_view(db, procurement, principal)


@app.get("/api/admin/mappings")
def list_mappings(principal: PrincipalDep, db: DB) -> dict:
    require_role(principal, "admin")
    suppliers = (
        db.execute(
            select(SupplierMapping).where(
                SupplierMapping.organization_id == principal.organization_id
            )
        )
        .scalars()
        .all()
    )
    products = (
        db.execute(
            select(ProductMapping).where(
                ProductMapping.organization_id == principal.organization_id
            )
        )
        .scalars()
        .all()
    )
    return {
        "suppliers": [
            {
                "reference": row.external_ref,
                "name": row.name,
                "odoo_partner_id": row.odoo_partner_id,
                "version": row.mapping_version,
                "active": row.active,
            }
            for row in suppliers
        ],
        "products": [
            {
                "sku": row.sku,
                "name": row.name,
                "odoo_product_id": row.odoo_product_id,
                "odoo_uom_id": row.odoo_uom_id,
                "odoo_tax_id": row.odoo_tax_id,
                "unit_price": str(row.unit_price),
                "tax_rate": str(row.tax_rate),
                "currency_code": row.currency_code,
                "version": row.mapping_version,
                "active": row.active,
            }
            for row in products
        ],
    }
