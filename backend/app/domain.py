from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

CENT = Decimal("0.01")
ROLE_NAMES = {"requester", "manager", "finance", "procurement", "admin", "automation"}


class DomainError(Exception):
    def __init__(self, message: str, status_code: int = 400, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class AuthenticationError(DomainError):
    def __init__(self, message: str = "authentication required"):
        super().__init__(message, 401)


class PermissionDenied(DomainError):
    def __init__(self, message: str = "permission denied"):
        super().__init__(message, 403)


class NotFound(DomainError):
    def __init__(self, message: str = "not found"):
        super().__init__(message, 404)


class Conflict(DomainError):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, 409, details)


class ValidationFailure(DomainError):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, 422, details)


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def canonical_hash(value: Any) -> str:
    import hashlib
    import json

    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
