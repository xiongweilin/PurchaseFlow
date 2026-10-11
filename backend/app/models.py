from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> uuid.UUID:
    return uuid.uuid4()


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="CNY")
    odoo_company_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    odoo_currency_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_department_org_code"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", "role", name="uq_membership_org_user_role"),
        CheckConstraint(
            "role IN ('requester','manager','finance','procurement','admin','automation')",
            name="ck_membership_role",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("departments.id", ondelete="CASCADE")
    )


class DemoSession(Base):
    __tablename__ = "demo_sessions"
    __table_args__ = (Index("ix_demo_session_expires", "expires_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    department_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("departments.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ServiceCredential(Base):
    __tablename__ = "service_credentials"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PolicyConfig(Base):
    __tablename__ = "policy_configs"
    __table_args__ = (
        UniqueConstraint("organization_id", name="uq_policy_org"),
        CheckConstraint("manager_limit >= 0", name="ck_policy_manager_limit"),
        CheckConstraint("policy_review_limit > manager_limit", name="ck_policy_review_limit"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    manager_limit: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    policy_review_limit: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax_inclusive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SupplierMapping(Base):
    __tablename__ = "supplier_mappings"
    __table_args__ = (
        UniqueConstraint("organization_id", "external_ref", name="uq_supplier_org_ref"),
        UniqueConstraint("organization_id", "odoo_partner_id", name="uq_supplier_odoo_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    external_ref: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    odoo_partner_id: Mapped[int] = mapped_column(Integer, nullable=False)
    mapping_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProductMapping(Base):
    __tablename__ = "product_mappings"
    __table_args__ = (
        UniqueConstraint("organization_id", "sku", name="uq_product_org_sku"),
        UniqueConstraint("organization_id", "odoo_product_id", name="uq_product_odoo_id"),
        CheckConstraint("unit_price >= 0", name="ck_product_unit_price"),
        CheckConstraint("tax_rate >= 0", name="ck_product_tax_rate"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    sku: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    odoo_product_id: Mapped[int] = mapped_column(Integer, nullable=False)
    odoo_uom_id: Mapped[int] = mapped_column(Integer, nullable=False)
    odoo_tax_id: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="CNY")
    mapping_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Procurement(Base):
    __tablename__ = "procurements"
    __table_args__ = (
        UniqueConstraint("organization_id", "request_number", name="uq_procurement_org_number"),
        CheckConstraint(
            "status IN ('draft','pending_manager','pending_finance','policy_review','rejected',"
            "'cancelled','approved','erp_pending','erp_unknown','erp_mismatch','erp_unavailable','erp_failed','erp_verified','closed')",
            name="ck_procurement_status",
        ),
        CheckConstraint("version >= 1", name="ck_procurement_version"),
        Index("ix_procurement_org_status_created", "organization_id", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    request_number: Mapped[str] = mapped_column(String(40), nullable=False)
    requester_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    department_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("departments.id"), nullable=False
    )
    supplier_mapping_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("supplier_mappings.id"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="CNY")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    policy_version: Mapped[int | None] = mapped_column(Integer)
    amount_untaxed: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    amount_tax: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    amount_total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    submitted_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requester: Mapped[User] = relationship(foreign_keys=[requester_id])
    supplier: Mapped[SupplierMapping] = relationship()
    lines: Mapped[list[ProcurementLine]] = relationship(
        cascade="all, delete-orphan", order_by="ProcurementLine.line_number"
    )
    approvals: Mapped[list[Approval]] = relationship(cascade="all, delete-orphan")


class ProcurementLine(Base):
    __tablename__ = "procurement_lines"
    __table_args__ = (
        UniqueConstraint("procurement_id", "line_number", name="uq_procurement_line_number"),
        CheckConstraint("quantity > 0", name="ck_procurement_line_quantity"),
        CheckConstraint("unit_price >= 0", name="ck_procurement_line_price"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    procurement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("procurements.id", ondelete="CASCADE"), nullable=False
    )
    product_mapping_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_mappings.id"), nullable=False
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    sku: Mapped[str] = mapped_column(String(80), nullable=False)
    product_name: Mapped[str] = mapped_column(String(160), nullable=False)
    odoo_product_id: Mapped[int] = mapped_column(Integer, nullable=False)
    odoo_uom_id: Mapped[int] = mapped_column(Integer, nullable=False)
    odoo_tax_id: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    amount_untaxed: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    amount_tax: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    amount_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    mapping_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        UniqueConstraint("procurement_id", "stage", name="uq_approval_request_stage"),
        CheckConstraint("stage IN ('manager','finance')", name="ck_approval_stage"),
        CheckConstraint("decision IN ('approved','rejected')", name="ck_approval_decision"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    procurement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("procurements.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(1000))
    request_version: Mapped[int] = mapped_column(Integer, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actor: Mapped[User] = relationship()


class ERPIntent(Base):
    __tablename__ = "erp_intents"
    __table_args__ = (
        UniqueConstraint("procurement_id", name="uq_erp_intent_procurement"),
        UniqueConstraint("external_intent_id", name="uq_erp_intent_external_id"),
        CheckConstraint(
            "state IN ('pending','dispatching','unavailable','unknown','verified','mismatch','failed','blocked')",
            name="ck_erp_intent_state",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    procurement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("procurements.id", ondelete="CASCADE"), nullable=False
    )
    external_intent_id: Mapped[str] = mapped_column(String(80), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    remote_order_id: Mapped[int | None] = mapped_column(Integer)
    remote_order_name: Mapped[str | None] = mapped_column(String(80))
    last_error: Mapped[str | None] = mapped_column(String(2000))
    last_observation: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("topic", "aggregate_id", name="uq_outbox_topic_aggregate"),
        CheckConstraint(
            "status IN ('pending','processing','done','dead')",
            name="ck_outbox_status",
        ),
        Index("ix_outbox_ready", "status", "available_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    topic: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_org_resource", "organization_id", "resource_type", "resource_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE")
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(100), nullable=False)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("organization_id", "scope", "key", name="uq_idempotency_org_scope_key"),
        Index("ix_idempotency_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String(120), nullable=False)
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PolicyReviewDecision(Base):
    __tablename__ = "policy_review_decisions"
    __table_args__ = (
        UniqueConstraint("procurement_id", name="uq_policy_review_procurement"),
        CheckConstraint("decision IN ('approved','rejected')", name="ck_policy_review_decision"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    procurement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("procurements.id", ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    request_version: Mapped[int] = mapped_column(Integer, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actor: Mapped[User] = relationship()
