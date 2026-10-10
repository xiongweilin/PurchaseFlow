from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain import Conflict, canonical_hash
from app.models import IdempotencyRecord


@dataclass(frozen=True)
class IdempotencyResult:
    record: IdempotencyRecord | None
    replay: dict[str, Any] | None


def claim(
    db: Session,
    *,
    organization_id: UUID,
    scope: str,
    key: str,
    request: Any,
) -> IdempotencyResult:
    if not key or len(key) > 200:
        raise Conflict("Idempotency-Key must be present and no longer than 200 characters.")
    request_hash = canonical_hash(request)
    existing = db.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.organization_id == organization_id,
            IdempotencyRecord.scope == scope,
            IdempotencyRecord.key == key,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_hash != request_hash:
            raise Conflict(
                "Idempotency-Key was already used with different request content."
            ) from None
        if existing.response_json is None:
            raise Conflict(
                "The prior request has no committed response; reconcile its state."
            ) from None
        return IdempotencyResult(record=None, replay=dict(existing.response_json))

    record = IdempotencyRecord(
        organization_id=organization_id,
        scope=scope,
        key=key,
        request_hash=request_hash,
        response_json=None,
    )
    try:
        with db.begin_nested():
            db.add(record)
            db.flush()
    except IntegrityError:
        winner = db.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.organization_id == organization_id,
                IdempotencyRecord.scope == scope,
                IdempotencyRecord.key == key,
            )
        ).scalar_one_or_none()
        if winner is None:
            raise Conflict("Idempotency race could not be resolved.") from None
        if winner.request_hash != request_hash:
            raise Conflict(
                "Idempotency-Key was already used with different request content."
            ) from None
        if winner.response_json is None:
            raise Conflict(
                "The prior request has no committed response; reconcile its state."
            ) from None
        return IdempotencyResult(record=None, replay=dict(winner.response_json))
    return IdempotencyResult(record=record, replay=None)
