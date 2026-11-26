"""Handler behaviour tests with a fake Bedrock client (zero AWS calls)."""

import json
from types import SimpleNamespace

import pytest

import handler
from bedrock_client import BedrockInvocationError, Invocation
from storage import StorageError

VALID_BODY = {
    "ticket_id": "tkt-042",
    "subject": "Checkout webhooks timing out after regional failover",
    "body": "Multiple enterprise tenants report 503 errors on payment confirmation webhooks.",
}

MODEL_TEXT = json.dumps(
    {
        "severity": "P1",
        "category": "incident",
        "confidence": 0.96,
        "summary": "Regional failover causing 503 timeouts on enterprise payment webhooks.",
        "draft_reply": "We have escalated this P1 payment webhook outage to our on-call SRE team.",
    }
)


def _event(method="POST", path="/triage", body=None):
    return {
        "version": "2.0",
        "rawPath": path,
        "requestContext": {"http": {"method": method, "path": path}, "requestId": "req-test-1"},
        "body": json.dumps(body) if body is not None else None,
        "isBase64Encoded": False,
    }


class FakeBedrock:
    def __init__(self, invocation=None, error=None):
        self.invocation = invocation
        self.error = error
        self.calls = []

    def converse(self, system_prompt, user_prompt, **kwargs):
        self.calls.append((system_prompt, user_prompt))
        if self.error:
            raise self.error
        return self.invocation


def _invocation():
    return Invocation(
        text=MODEL_TEXT,
        model_id="apac.amazon.nova-pro-v1:0",
        input_tokens=286,
        output_tokens=114,
        latency_ms=900,
        estimated_cost_usd=0.0005936,
        stop_reason="end_turn",
    )


@pytest.fixture
def wired(monkeypatch):
    fake = FakeBedrock(invocation=_invocation())
    persisted = {}
    metrics = {}

    monkeypatch.setattr(handler, "_BEDROCK_CLIENT", fake)
    monkeypatch.setattr(handler, "save_triage", lambda record: persisted.update(record) or True)
    monkeypatch.setattr(handler, "emit_triage_metrics", lambda **kwargs: metrics.update(kwargs))
    return SimpleNamespace(fake=fake, persisted=persisted, metrics=metrics)


def test_health_is_cheap_and_reports_stack_version(monkeypatch):
    monkeypatch.setenv("STACK_VERSION", "v1")
    response = handler.lambda_handler(_event("GET", "/health"), None)
    body = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert body["status"] == "ok"
    assert body["stack_version"] == "v1"
    assert body["model_id"] == "apac.amazon.nova-pro-v1:0"


def test_unknown_route_returns_404():
    response = handler.lambda_handler(_event("GET", "/nope"), None)
    assert response["statusCode"] == 404


def test_options_returns_204():
    response = handler.lambda_handler(_event("OPTIONS", "/triage"), None)
    assert response["statusCode"] == 204


def test_invalid_payload_returns_400_without_calling_bedrock(wired):
    response = handler.lambda_handler(_event("POST", "/triage", {"ticket_id": "tkt-1"}), None)
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"] == "invalid_request"
    assert wired.fake.calls == []


def test_triage_success_returns_contract_and_telemetry(wired):
    context = SimpleNamespace(memory_limit_in_mb=512)
    response = handler.lambda_handler(_event("POST", "/triage", VALID_BODY), context)
    body = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert body["ticket_id"] == "tkt-042"
    assert body["severity"] == "P1"
    assert body["category"] == "incident"
    assert body["confidence"] == 0.96

    telemetry = body["telemetry"]
    assert telemetry["stack_version"] == "v1"
    assert telemetry["route_decision"] == "single_heavy"
    assert telemetry["cache_hit"] is False
    assert telemetry["escalated"] is False
    assert telemetry["frontier_tokens_used"] == 400
    assert telemetry["estimated_cost_usd"] == 0.0005936
    assert telemetry["lambda_memory_mb"] == 512
    assert telemetry["lambda_gb_seconds"] > 0

    assert wired.fake.calls[0][0] == handler.SYSTEM_PROMPT
    assert "Checkout webhooks" in wired.fake.calls[0][1]
    assert wired.persisted["ticket_id"] == "tkt-042"
    assert wired.persisted["created_at"].endswith("Z")
    assert wired.metrics["frontier_tokens"] == 400
    assert wired.metrics["stack_version"] == "v1"


def test_bedrock_failure_returns_502(monkeypatch, wired):
    wired.fake.error = BedrockInvocationError("throttled")
    response = handler.lambda_handler(_event("POST", "/triage", VALID_BODY), None)
    assert response["statusCode"] == 502
    assert json.loads(response["body"])["error"] == "model_invocation_failed"
    assert wired.persisted == {}


def test_invalid_model_output_returns_502(monkeypatch):
    fake = FakeBedrock(invocation=Invocation("not json", "apac.amazon.nova-pro-v1:0", 1, 1, 10, 0.0, "end_turn"))
    monkeypatch.setattr(handler, "_BEDROCK_CLIENT", fake)
    monkeypatch.setattr(handler, "save_triage", lambda record: True)
    monkeypatch.setattr(handler, "emit_triage_metrics", lambda **kwargs: None)

    response = handler.lambda_handler(_event("POST", "/triage", VALID_BODY), None)
    assert response["statusCode"] == 502
    assert json.loads(response["body"])["error"] == "model_response_invalid"


def test_persistence_failure_does_not_fail_the_request(monkeypatch, wired):
    monkeypatch.setattr(handler, "save_triage", lambda record: False)
    response = handler.lambda_handler(_event("POST", "/triage", VALID_BODY), None)
    assert response["statusCode"] == 200


def test_stats_returns_aggregate(monkeypatch):
    canned = {"total_tickets": 3, "by_severity": {"P1": 1}, "stack_version": "v1"}
    monkeypatch.setattr(handler, "get_stats", lambda: canned)
    response = handler.lambda_handler(_event("GET", "/stats"), None)
    assert response["statusCode"] == 200
    assert json.loads(response["body"])["total_tickets"] == 3


def test_stats_storage_error_returns_503(monkeypatch):
    def boom():
        raise StorageError("unavailable")

    monkeypatch.setattr(handler, "get_stats", boom)
    response = handler.lambda_handler(_event("GET", "/stats"), None)
    assert response["statusCode"] == 503


def test_v2_delegates_to_adaptive_router(monkeypatch):
    from router import RouteOutcome

    class FakeRouter:
        def route(self, ticket):
            return RouteOutcome(
                triage={
                    "severity": "P4",
                    "category": "how_to",
                    "confidence": 0.91,
                    "summary": "Routine question.",
                    "draft_reply": "Here is the link you need.",
                },
                telemetry={
                    "route_decision": "nova_lite",
                    "model_id": "apac.amazon.nova-lite-v1:0",
                    "cache_hit": False,
                    "escalated": False,
                    "fallback_triggered": False,
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "frontier_tokens_used": 0,
                    "estimated_cost_usd": 0.0000105,
                },
            )

    monkeypatch.setenv("STACK_VERSION", "v2")
    monkeypatch.setattr(handler, "_ROUTER", FakeRouter())
    monkeypatch.setattr(handler, "save_triage", lambda record: True)
    monkeypatch.setattr(handler, "emit_triage_metrics", lambda **kwargs: None)

    response = handler.lambda_handler(_event("POST", "/triage", VALID_BODY), None)
    telemetry = json.loads(response["body"])["telemetry"]

    assert response["statusCode"] == 200
    assert telemetry["route_decision"] == "nova_lite"
    assert telemetry["frontier_tokens_used"] == 0
    assert telemetry["stack_version"] == "v2"


def test_base64_body_is_decoded(monkeypatch, wired):
    import base64

    event = _event("POST", "/triage")
    event["body"] = base64.b64encode(json.dumps(VALID_BODY).encode()).decode()
    event["isBase64Encoded"] = True
    response = handler.lambda_handler(event, None)
    assert response["statusCode"] == 200
