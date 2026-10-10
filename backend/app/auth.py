from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.domain import AuthenticationError, PermissionDenied
from app.models import DemoSession, Membership, ServiceCredential, User


@dataclass(frozen=True)
class Principal:
    user_id: UUID | None
    organization_id: UUID
    role: str
    department_id: UUID | None = None
    service_credential_id: UUID | None = None


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def create_demo_session(
    db: Session,
    *,
    role: str,
    department_id: UUID | None,
    user_id: UUID,
    organization_id: UUID,
) -> tuple[DemoSession, str]:
    token = new_token()
    row = DemoSession(
        token_hash=token_hash(token),
        user_id=user_id,
        organization_id=organization_id,
        role=role,
        department_id=department_id,
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.session_ttl_seconds),
    )
    db.add(row)
    db.flush()
    return row, token


def resolve_demo_principal(db: Session, token: str) -> Principal:
    row = db.execute(
        select(DemoSession).where(DemoSession.token_hash == token_hash(token))
    ).scalar_one_or_none()
    if row is None:
        raise AuthenticationError("demo session is invalid or expired")
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= datetime.now(UTC):
        db.delete(row)
        db.flush()
        raise AuthenticationError("demo session is invalid or expired")
    user = db.get(User, row.user_id)
    if user is None or not user.active:
        raise AuthenticationError("demo user is inactive")
    membership = db.execute(
        select(Membership).where(
            Membership.organization_id == row.organization_id,
            Membership.user_id == row.user_id,
            Membership.role == row.role,
            Membership.department_id.is_(None)
            if row.department_id is None
            else Membership.department_id == row.department_id,
        )
    ).scalar_one_or_none()
    if membership is None:
        raise AuthenticationError("demo membership is no longer active")
    return Principal(
        user_id=row.user_id,
        organization_id=row.organization_id,
        role=row.role,
        department_id=row.department_id,
    )


def resolve_service_principal(db: Session, bearer_token: str | None) -> Principal:
    if not bearer_token:
        raise AuthenticationError("service bearer token is required")
    credential = db.execute(
        select(ServiceCredential).where(
            ServiceCredential.token_hash == token_hash(bearer_token),
            ServiceCredential.active.is_(True),
        )
    ).scalar_one_or_none()
    if credential is None:
        raise AuthenticationError("service bearer token is invalid")
    return Principal(
        user_id=None,
        organization_id=credential.organization_id,
        role="automation",
        service_credential_id=credential.id,
    )


def require_role(principal: Principal, *roles: str) -> None:
    if principal.role not in roles:
        raise PermissionDenied(f"action requires one of roles: {', '.join(roles)}")


def require_demo_mode() -> None:
    if not settings.demo_mode or settings.environment != "demo":
        raise PermissionDenied("demo role switching is disabled outside the demo environment")


def extract_bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()
