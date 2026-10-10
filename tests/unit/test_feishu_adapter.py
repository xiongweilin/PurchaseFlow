import hashlib

import pytest

from app.feishu_adapter import (
    FeishuAdapterError,
    map_feishu_form_fields,
    verify_feishu_callback,
    verify_feishu_signature,
)

TOKEN = "synthetic-verification-token"
FIELD_MAP = {
    "requester_email": "employee_email",
    "department_code": "department",
    "supplier_ref": "supplier",
    "reason": "business_reason",
    "lines": "line_items",
}
FORM_VALUES = {
    "employee_email": "requester.ops@demo.local",
    "department": "OPS",
    "supplier": "PF-VENDOR-OFFICE",
    "business_reason": "Synthetic Feishu event for offline adapter verification.",
    "line_items": [{"sku": "PF-OFFICE-SET", "quantity": "1", "unit_price": "1200.00"}],
}


def test_feishu_url_verification_returns_only_the_verified_challenge() -> None:
    assert verify_feishu_callback(
        {"type": "url_verification", "token": TOKEN, "challenge": "demo-challenge"},
        verification_token=TOKEN,
    ) == {"challenge": "demo-challenge"}


def test_feishu_event_token_and_stable_event_id_are_required() -> None:
    payload = {
        "schema": "2.0",
        "header": {"event_id": "evt-demo-001", "token": TOKEN},
        "event": {},
    }
    assert verify_feishu_callback(payload, verification_token=TOKEN) == {"event_id": "evt-demo-001"}
    with pytest.raises(FeishuAdapterError, match="Verification Token"):
        verify_feishu_callback(payload, verification_token="wrong-token")


def test_feishu_v1_callbacks_are_rejected_until_a_v1_adapter_is_defined() -> None:
    with pytest.raises(FeishuAdapterError, match="v2.0"):
        verify_feishu_callback({"token": TOKEN, "uuid": "legacy"}, verification_token=TOKEN)


def test_feishu_field_ids_map_to_the_existing_idempotent_intake_contract() -> None:
    result = map_feishu_form_fields(
        event_id="evt-demo-001",
        form_values=FORM_VALUES,
        field_map=FIELD_MAP,
    )
    assert result == {
        "external_event_id": "evt-demo-001",
        "requester_email": "requester.ops@demo.local",
        "department_code": "OPS",
        "supplier_ref": "PF-VENDOR-OFFICE",
        "reason": "Synthetic Feishu event for offline adapter verification.",
        "lines": [{"sku": "PF-OFFICE-SET", "quantity": "1", "unit_price": "1200.00"}],
    }


def test_feishu_replay_preserves_the_same_event_id_for_api_idempotency() -> None:
    first = map_feishu_form_fields(event_id="evt-demo-001", form_values=FORM_VALUES, field_map=FIELD_MAP)
    replay = map_feishu_form_fields(event_id="evt-demo-001", form_values=FORM_VALUES, field_map=FIELD_MAP)
    assert replay["external_event_id"] == first["external_event_id"]


def test_feishu_rejects_incomplete_field_mapping_and_invalid_lines() -> None:
    with pytest.raises(FeishuAdapterError, match="incomplete"):
        map_feishu_form_fields(event_id="evt-demo-001", form_values=FORM_VALUES, field_map={})
    invalid_values = {**FORM_VALUES, "line_items": []}
    with pytest.raises(FeishuAdapterError, match="one to three"):
        map_feishu_form_fields(event_id="evt-demo-001", form_values=invalid_values, field_map=FIELD_MAP)


def test_feishu_encrypt_key_signature_checks_raw_body_and_freshness() -> None:
    timestamp = "1760000000"
    nonce = "synthetic-nonce"
    encrypt_key = "synthetic-encrypt-key"
    raw_body = b'{"schema":"2.0","header":{"event_id":"evt-demo-001"}}'
    signature = hashlib.sha256(
        f"{timestamp}{nonce}{encrypt_key}".encode() + raw_body
    ).hexdigest()
    assert verify_feishu_signature(
        timestamp=timestamp,
        nonce=nonce,
        encrypt_key=encrypt_key,
        raw_body=raw_body,
        signature=signature,
        now=1760000001,
    )
    assert not verify_feishu_signature(
        timestamp=timestamp,
        nonce=nonce,
        encrypt_key=encrypt_key,
        raw_body=raw_body + b" ",
        signature=signature,
        now=1760000001,
    )
    assert not verify_feishu_signature(
        timestamp=timestamp,
        nonce=nonce,
        encrypt_key=encrypt_key,
        raw_body=raw_body,
        signature=signature,
        now=1760000400,
    )
