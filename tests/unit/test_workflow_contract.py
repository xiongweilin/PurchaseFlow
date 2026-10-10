from __future__ import annotations

import json
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[2] / "n8n" / "workflows"


def _workflow(filename: str) -> dict:
    return json.loads((WORKFLOWS / filename).read_text(encoding="utf-8"))


def _node(workflow: dict, name: str) -> dict:
    return next(node for node in workflow["nodes"] if node["name"] == name)


def test_intake_workflow_is_authenticated_and_uses_api_idempotency() -> None:
    workflow = _workflow("purchaseflow-intake.json")
    webhook = _node(workflow, "Authenticated Intake")
    request = _node(workflow, "Submit idempotent request")
    response = _node(workflow, "Return API response")

    assert workflow["active"] is False  # Provisioning imports, binds credentials, then publishes.
    assert webhook["type"] == "n8n-nodes-base.webhook"
    assert webhook["webhookId"]
    assert webhook["parameters"]["httpMethod"] == "POST"
    assert webhook["parameters"]["path"] == "purchaseflow/intake"
    assert webhook["parameters"]["authentication"] == "headerAuth"
    assert webhook["parameters"]["responseMode"] == "responseNode"
    assert request["parameters"]["url"] == "http://api:8000/api/integrations/procurements"
    assert request["parameters"]["nodeCredentialType"] == "httpHeaderAuth"
    assert request["parameters"]["headerParameters"]["parameters"][0] == {
        "name": "Idempotency-Key",
        "value": "={{ $json.body.external_event_id }}",
    }
    request_response = request["parameters"]["options"]["response"]["response"]
    assert request_response == {
        "responseFormat": "json",
        "fullResponse": True,
        "neverError": True,
    }
    assert response["type"] == "n8n-nodes-base.respondToWebhook"
    assert response["parameters"]["respondWith"] == "json"
    assert response["parameters"]["responseBody"] == "={{ $json.body }}"
    assert response["parameters"]["options"]["responseCode"] == "={{ $json.statusCode }}"


def test_digest_workflow_has_schedule_manual_webhook_and_internal_mail() -> None:
    workflow = _workflow("procurement-daily-summary.json")
    schedule = _node(workflow, "Weekdays at 09:00")
    webhook = _node(workflow, "Request digest via webhook")
    summary = _node(workflow, "Read sanitized workflow summary")
    email = _node(workflow, "Send local-only Mailpit digest")
    interval = schedule["parameters"]["rule"]["interval"][0]

    assert workflow["active"] is False
    assert schedule["type"] == "n8n-nodes-base.scheduleTrigger"
    assert interval["field"] == "weeks"
    assert interval["triggerAtDay"] == [1, 2, 3, 4, 5]
    assert interval["triggerAtHour"] == 9
    assert interval["triggerAtMinute"] == 0
    assert webhook["webhookId"]
    assert webhook["parameters"]["path"] == "purchaseflow/summary"
    assert webhook["parameters"]["authentication"] == "headerAuth"
    assert summary["parameters"]["url"] == "http://api:8000/api/integrations/summary"
    assert email["type"] == "n8n-nodes-base.emailSend"
    assert "@demo.local" in email["parameters"]["toEmail"]


def test_workflow_exports_contain_no_erp_write_endpoint_or_secret() -> None:
    for path in WORKFLOWS.glob("*.json"):
        content = path.read_text(encoding="utf-8").lower()
        assert "/json/2/purchase.order/create" not in content
        assert '"api_key"' not in content
        assert '"password"' not in content
