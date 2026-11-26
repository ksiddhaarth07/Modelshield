"""Router tests: cache hit, gate, lite, escalation, fallback and fail-open."""

import json

import pytest

from bedrock_client import (
    NOVA_LITE,
    NOVA_PRO,
    BedrockInvocationError,
    Invocation,
    calculate_cost,
)
from cache import build_cache_key
from router import AdaptiveRouter, RouteOutcome

ROUTINE = {
    "ticket_id": "tkt-001",
    "subject": "Reset password link",
    "body": "I cannot sign in because my reset link expired. Could you send a new one?",
}

COMPLEX = {
    "ticket_id": "tkt-077",
    "subject": "Payment webhook 503 storm after regional failover",
    "body": "Since the failover, payment webhooks return 503 for multiple enterprise tenants.",
}

LONG_TICKET = {
    "ticket_id": "tkt-long",
    "subject": "Detailed investigation request",
    "body": "x" * 950,
}


def triage_json(severity="P4", category="how_to", confidence=0.9):
    return json.dumps(
        {
            "severity": severity,
            "category": category,
            "confidence": confidence,
            "summary": "Short summary.",
            "draft_reply": "We are looking into this and will follow up.",
        }
    )


def invocation(text, model, input_tokens=100, output_tokens=50):
    return Invocation(
        text=text,
        model_id=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=100,
        estimated_cost_usd=calculate_cost(model, input_tokens, output_tokens),
        stop_reason="end_turn",
    )


class FakeClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def converse(self, system_prompt, user_prompt, **kwargs):
        self.calls.append(user_prompt)
        if not self.responses:
            raise AssertionError("unexpected model call")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeCache:
    def __init__(self, items=None, fail=False):
        self.items = dict(items or {})
        self.fail = fail
        self.puts = []

    def get(self, key):
        if self.fail:
            raise RuntimeError("cache down")
        return self.items.get(key)

    def put(self, key, payload):
        if self.fail:
            raise RuntimeError("cache down")
        self.puts.append((key, payload))
        self.items[key] = payload
        return True


def make_router(lite, pro, cache=None):
    return AdaptiveRouter(
        pro_client=pro,
        lite_client=lite,
        cache=cache or FakeCache(),
        confidence_threshold=0.85,
    )


def test_cache_hit_returns_without_any_model_call():
    cached = {"severity": "P4", "category": "how_to", "confidence": 0.9, "summary": "s", "draft_reply": "d"}
    key = build_cache_key(ROUTINE["subject"], ROUTINE["body"])
    router = make_router(FakeClient(), FakeClient(), FakeCache({key: cached}))

    outcome = router.route(ROUTINE)

    assert outcome.triage == cached
    assert outcome.telemetry["route_decision"] == "cache_hit"
    assert outcome.telemetry["cache_hit"] is True
    assert outcome.telemetry["estimated_cost_usd"] == 0.0
    assert outcome.telemetry["frontier_tokens_used"] == 0


def test_invalid_cached_payload_is_treated_as_miss():
    key = build_cache_key(ROUTINE["subject"], ROUTINE["body"])
    lite = FakeClient(invocation(triage_json(), NOVA_LITE))
    router = make_router(lite, FakeClient(), FakeCache({key: {"severity": "P9"}}))

    outcome = router.route(ROUTINE)

    assert outcome.telemetry["route_decision"] == "nova_lite"
    assert len(lite.calls) == 1


def test_two_keywords_route_straight_to_pro():
    pro = FakeClient(invocation(triage_json("P1", "incident", 0.97), NOVA_PRO))
    lite = FakeClient()
    router = make_router(lite, pro)

    outcome = router.route(COMPLEX)

    assert outcome.telemetry["route_decision"] == "direct_pro"
    assert outcome.telemetry["frontier_tokens_used"] == 150
    assert lite.calls == []
    assert len(pro.calls) == 1


def test_long_ticket_routes_straight_to_pro():
    pro = FakeClient(invocation(triage_json("P3", "bug", 0.9), NOVA_PRO))
    lite = FakeClient()
    router = make_router(lite, pro)

    assert router.route(LONG_TICKET).telemetry["route_decision"] == "direct_pro"
    assert lite.calls == []


def test_routine_ticket_is_accepted_from_lite():
    lite = FakeClient(invocation(triage_json("P4", "how_to", 0.93), NOVA_LITE))
    pro = FakeClient()
    router = make_router(lite, pro)

    outcome = router.route(ROUTINE)

    assert outcome.telemetry["route_decision"] == "nova_lite"
    assert outcome.telemetry["frontier_tokens_used"] == 0
    assert outcome.telemetry["estimated_cost_usd"] == pytest.approx(
        calculate_cost(NOVA_LITE, 100, 50)
    )
    assert pro.calls == []


def test_low_confidence_escalates_and_bills_both_calls():
    lite = FakeClient(invocation(triage_json("P3", "how_to", 0.60), NOVA_LITE))
    pro = FakeClient(invocation(triage_json("P2", "bug", 0.95), NOVA_PRO))
    router = make_router(lite, pro)

    outcome = router.route(ROUTINE)

    assert outcome.telemetry["route_decision"] == "escalated_pro"
    assert outcome.telemetry["escalated"] is True
    assert outcome.telemetry["estimated_cost_usd"] == pytest.approx(
        calculate_cost(NOVA_LITE, 100, 50) + calculate_cost(NOVA_PRO, 100, 50)
    )
    assert outcome.telemetry["frontier_tokens_used"] == 150
    assert outcome.triage["severity"] == "P2"


def test_p1_always_escalates_even_at_high_confidence():
    lite = FakeClient(invocation(triage_json("P1", "incident", 0.99), NOVA_LITE))
    pro = FakeClient(invocation(triage_json("P1", "incident", 0.98), NOVA_PRO))
    router = make_router(lite, pro)

    outcome = router.route(ROUTINE)

    assert outcome.telemetry["route_decision"] == "escalated_pro"
    assert outcome.telemetry["escalated"] is True
    assert len(pro.calls) == 1


def test_confidence_at_threshold_does_not_escalate():
    lite = FakeClient(invocation(triage_json("P4", "how_to", 0.85), NOVA_LITE))
    router = make_router(lite, FakeClient())

    assert router.route(ROUTINE).telemetry["route_decision"] == "nova_lite"


def test_lite_error_falls_back_to_pro():
    lite = FakeClient(BedrockInvocationError("throttled"))
    pro = FakeClient(invocation(triage_json("P3", "how_to", 0.9), NOVA_PRO))
    router = make_router(lite, pro)

    outcome = router.route(ROUTINE)

    assert outcome.telemetry["route_decision"] == "fallback_pro"
    assert outcome.telemetry["fallback_triggered"] is True
    assert outcome.telemetry["estimated_cost_usd"] == pytest.approx(calculate_cost(NOVA_PRO, 100, 50))


def test_invalid_lite_json_falls_back_and_keeps_lite_cost():
    lite = FakeClient(invocation("not json", NOVA_LITE))
    pro = FakeClient(invocation(triage_json("P3", "how_to", 0.9), NOVA_PRO))
    router = make_router(lite, pro)

    outcome = router.route(ROUTINE)

    assert outcome.telemetry["route_decision"] == "fallback_pro"
    assert outcome.telemetry["estimated_cost_usd"] == pytest.approx(
        calculate_cost(NOVA_LITE, 100, 50) + calculate_cost(NOVA_PRO, 100, 50)
    )
    assert outcome.telemetry["frontier_tokens_used"] == 150


def test_write_through_happens_for_every_route():
    cache = FakeCache()
    lite = FakeClient(invocation(triage_json("P3", "billing", 0.92), NOVA_LITE))
    router = make_router(lite, FakeClient(), cache)

    router.route(ROUTINE)

    assert len(cache.puts) == 1
    assert cache.puts[0][0] == build_cache_key(ROUTINE["subject"], ROUTINE["body"])
    assert cache.puts[0][1]["severity"] == "P3"


def test_cache_outage_never_blocks_triage():
    lite = FakeClient(invocation(triage_json("P3", "billing", 0.92), NOVA_LITE))
    router = make_router(lite, FakeClient(), FakeCache(fail=True))

    outcome = router.route(ROUTINE)

    assert outcome.telemetry["route_decision"] == "nova_lite"


def test_repeat_variants_share_one_cache_entry_end_to_end():
    cache = FakeCache()
    lite = FakeClient(invocation(triage_json("P3", "billing", 0.9), NOVA_LITE))
    router = make_router(lite, FakeClient(), cache)

    first = dict(ROUTINE)
    second = {
        "ticket_id": "tkt-999",
        "subject": ROUTINE["subject"].upper(),
        "body": "  " + ROUTINE["body"].replace(" ", "  ") + "  ",
    }

    first_outcome = router.route(first)
    second_outcome = router.route(second)

    assert first_outcome.telemetry["route_decision"] == "nova_lite"
    assert second_outcome.telemetry["route_decision"] == "cache_hit"
    assert len(lite.calls) == 1


def test_p2_incident_stays_on_lite_when_confident():
    lite = FakeClient(invocation(triage_json("P2", "incident", 0.95), NOVA_LITE))
    pro = FakeClient()
    router = make_router(lite, pro)

    outcome = router.route(ROUTINE)

    assert outcome.telemetry["route_decision"] == "nova_lite"
    assert outcome.telemetry["frontier_tokens_used"] == 0
    assert pro.calls == []


def test_p3_how_to_escalates():
    lite = FakeClient(invocation(triage_json("P3", "how_to", 0.95), NOVA_LITE))
    pro = FakeClient(invocation(triage_json("P3", "how_to", 0.97), NOVA_PRO))
    router = make_router(lite, pro)

    assert router.route(ROUTINE).telemetry["route_decision"] == "escalated_pro"


def test_p3_billing_stays_on_lite():
    lite = FakeClient(invocation(triage_json("P3", "billing", 0.95), NOVA_LITE))
    pro = FakeClient()
    router = make_router(lite, pro)

    outcome = router.route(ROUTINE)

    assert outcome.telemetry["route_decision"] == "nova_lite"
    assert pro.calls == []


def test_p1_is_never_cached():
    cache = FakeCache()
    lite = FakeClient(invocation(triage_json("P1", "incident", 0.95), NOVA_LITE))
    pro = FakeClient(invocation(triage_json("P1", "incident", 0.97), NOVA_PRO))
    router = make_router(lite, pro, cache)

    router.route(ROUTINE)

    assert cache.puts == []


def test_p1_cached_entry_is_bypassed_on_read():
    stale_p1 = {
        "severity": "P1",
        "category": "incident",
        "confidence": 0.99,
        "summary": "Stale cached P1.",
        "draft_reply": "Old reply.",
    }
    key = build_cache_key(ROUTINE["subject"], ROUTINE["body"])
    cache = FakeCache({key: stale_p1})
    lite = FakeClient(invocation(triage_json("P1", "incident", 0.96), NOVA_LITE))
    pro = FakeClient(invocation(triage_json("P1", "incident", 0.98), NOVA_PRO))
    router = make_router(lite, pro, cache)

    outcome = router.route(ROUTINE)

    assert outcome.telemetry["cache_hit"] is False
    assert outcome.telemetry["route_decision"] == "escalated_pro"
    assert len(lite.calls) == 1
    assert len(pro.calls) == 1
    assert cache.puts == []


def test_timeout_and_retry_budget_stays_under_20_seconds():
    from bedrock_client import _BOTO_CONFIG, BedrockClient
    from router import _LITE_CONFIG, _LITE_MAX_ATTEMPTS, _PRO_CONFIG, _PRO_MAX_ATTEMPTS

    default_client = BedrockClient(runtime_client=object())
    default_budget = (
        (_BOTO_CONFIG.connect_timeout + _BOTO_CONFIG.read_timeout) * default_client.max_attempts
        + max(0, default_client.max_attempts - 1) * 0.5
    )
    lite_budget = (_LITE_CONFIG.connect_timeout + _LITE_CONFIG.read_timeout) * _LITE_MAX_ATTEMPTS
    pro_budget = (_PRO_CONFIG.connect_timeout + _PRO_CONFIG.read_timeout) * _PRO_MAX_ATTEMPTS

    assert default_budget < 20.0
    assert lite_budget < 20.0
    assert lite_budget + pro_budget < 20.0


def test_build_router_respects_env_model_ids(monkeypatch):
    from router import build_router

    monkeypatch.setenv("HEAVY_MODEL_ID", "custom.pro-v1:0")
    monkeypatch.setenv("LIGHT_MODEL_ID", "custom.lite-v1:0")
    router = build_router()

    assert router._pro.model_id == "custom.pro-v1:0"
    assert router._lite.model_id == "custom.lite-v1:0"


def test_outcome_type_is_exposed_for_handler():
    assert RouteOutcome.__dataclass_fields__["triage"]
