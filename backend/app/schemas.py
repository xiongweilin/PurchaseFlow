from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DemoSessionIn(BaseModel):
    role: Literal["requester", "manager", "finance", "procurement", "admin"]
    department_code: str | None = None
    email: str | None = None


class DemoSessionOut(BaseModel):
    user_id: UUID
    display_name: str
    role: str
    department_code: str | None
    expires_in_seconds: int


class ProcurementLineIn(BaseModel):
    sku: str = Field(min_length=1, max_length=80)
    quantity: Decimal = Field(gt=Decimal("0"), max_digits=12, decimal_places=2)
    unit_price: Decimal = Field(ge=Decimal("0"), max_digits=12, decimal_places=2)


class ProcurementBody(BaseModel):
    department_code: str = Field(min_length=1, max_length=40)
    supplier_ref: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=5, max_length=1000)
    currency_code: Literal["CNY"] = "CNY"
    lines: list[ProcurementLineIn] = Field(min_length=1, max_length=3)


class UpdateProcurementIn(ProcurementBody):
    expected_version: int = Field(ge=1)


class SubmitBody(BaseModel):
    expected_version: int = Field(ge=1)


class DecisionBody(BaseModel):
    decision: Literal["approve", "reject"]
    expected_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=1000)


class IntakeBody(BaseModel):
    external_event_id: str = Field(min_length=1, max_length=200)
    requester_email: str = Field(min_length=3, max_length=254)
    department_code: str = Field(min_length=1, max_length=40)
    supplier_ref: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=5, max_length=1000)
    lines: list[ProcurementLineIn] = Field(min_length=1, max_length=3)


class ApprovalOut(BaseModel):
    stage: str
    actor_name: str
    decision: str
    reason: str | None
    decided_at: str


class ProcurementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    request_number: str
    department_name: str
    requester_name: str
    supplier_name: str
    reason: str
    currency_code: str
    status: str
    version: int
    policy_version: int | None
    amount_untaxed: Decimal
    amount_tax: Decimal
    amount_total: Decimal
    lines: list[dict]
    approvals: list[dict]
    erp: dict | None
    created_at: str


class DemoIdentityOut(BaseModel):
    user_id: UUID
    display_name: str
    role: str
    department_code: str | None
    department_name: str | None


class PolicyUpdateIn(BaseModel):
    expected_version: int = Field(ge=1)
    manager_limit: Decimal = Field(ge=Decimal("0"), max_digits=12, decimal_places=2)
    policy_review_limit: Decimal = Field(gt=Decimal("0"), max_digits=12, decimal_places=2)
    tax_inclusive: bool = True


class PolicyReviewBody(BaseModel):
    decision: Literal["approve", "reject"]
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=5, max_length=1000)
