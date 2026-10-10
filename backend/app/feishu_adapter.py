from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Mapping
from typing import Any


class FeishuAdapterError(ValueError):
    """Raised when a Feishu callback cannot be safely normalized."""


def verify_feishu_signature(
    *,
    timestamp: str,
    nonce: str,
    encrypt_key: str,
    raw_body: bytes,
    signature: str,
    now: float | None = None,
    max_age_seconds: int = 300,
) -> bool:
    """Verify the optional Feishu Encrypt Key signature and its freshness."""
    if not timestamp.isdigit() or not nonce or not encrypt_key or not signature:
        return False
    now_seconds = time.time() if now is None else now
    if abs(now_seconds - int(timestamp)) > max_age_seconds:
        return False
    signed_bytes = f"{timestamp}{nonce}{encrypt_key}".encode() + raw_body
    expected = hashlib.sha256(signed_bytes).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


def verify_feishu_callback(
    payload: Mapping[str, Any], *, verification_token: str
) -> dict[str, str]:
    """Verify a v2.0 callback token, or answer Feishu URL verification."""
    if not verification_token:
        raise FeishuAdapterError("Feishu Verification Token is not configured.")

    if payload.get("type") == "url_verification":
        token = payload.get("token")
        challenge = payload.get("challenge")
        if not isinstance(token, str) or not hmac.compare_digest(token, verification_token):
            raise FeishuAdapterError("Feishu URL verification token did not match.")
        if not isinstance(challenge, str) or not challenge:
            raise FeishuAdapterError("Feishu URL verification did not include a challenge.")
        return {"challenge": challenge}

    if payload.get("schema") != "2.0":
        raise FeishuAdapterError("Only Feishu v2.0 event callbacks are supported.")
    header = payload.get("header")
    if not isinstance(header, Mapping):
        raise FeishuAdapterError("Feishu v2.0 callback is missing its header.")
    token = header.get("token")
    event_id = header.get("event_id")
    if not isinstance(token, str) or not hmac.compare_digest(token, verification_token):
        raise FeishuAdapterError("Feishu event Verification Token did not match.")
    if not isinstance(event_id, str) or not event_id or len(event_id) > 200:
        raise FeishuAdapterError("Feishu event_id is missing or too long.")
    return {"event_id": event_id}


def map_feishu_form_fields(
    *,
    event_id: str,
    form_values: Mapping[str, Any],
    field_map: Mapping[str, str],
) -> dict[str, Any]:
    """Map tenant-specific Feishu form fields to the existing intake contract."""
    required_fields = (
        "requester_email",
        "department_code",
        "supplier_ref",
        "reason",
        "lines",
    )
    if not event_id or len(event_id) > 200:
        raise FeishuAdapterError("A stable Feishu event_id is required for idempotency.")
    missing_map = [name for name in required_fields if not field_map.get(name)]
    if missing_map:
        raise FeishuAdapterError(f"Feishu field map is incomplete: {', '.join(missing_map)}.")

    mapped: dict[str, Any] = {"external_event_id": event_id}
    for name in required_fields:
        source_name = field_map[name]
        if source_name not in form_values:
            raise FeishuAdapterError(f"Feishu form is missing mapped field {source_name!r}.")
        mapped[name] = form_values[source_name]

    requester_email = mapped["requester_email"]
    department_code = mapped["department_code"]
    supplier_ref = mapped["supplier_ref"]
    reason = mapped["reason"]
    lines = mapped["lines"]
    if not all(isinstance(value, str) and value.strip() for value in (
        requester_email,
        department_code,
        supplier_ref,
        reason,
    )):
        raise FeishuAdapterError("Feishu requester, department, supplier, and reason must be non-empty text.")
    for name in ("requester_email", "department_code", "supplier_ref", "reason"):
        mapped[name] = mapped[name].strip()
    if not isinstance(lines, list) or not 1 <= len(lines) <= 3:
        raise FeishuAdapterError("Feishu procurement intake must contain one to three lines.")
    normalized_lines: list[dict[str, Any]] = []
    for line in lines:
        if not isinstance(line, Mapping) or not all(
            isinstance(line.get(key), str | int | float)
            for key in ("sku", "quantity", "unit_price")
        ):
            raise FeishuAdapterError("Each Feishu line must map sku, quantity, and unit_price.")
        if not str(line["sku"]).strip():
            raise FeishuAdapterError("Feishu line sku cannot be empty.")
        normalized_lines.append(
            {
                "sku": str(line["sku"]).strip(),
                "quantity": line["quantity"],
                "unit_price": line["unit_price"],
            }
        )
    mapped["lines"] = normalized_lines
    return mapped
