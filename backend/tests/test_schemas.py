"""Contract tests for request validation and model-output parsing."""

import json

import pytest

from schemas import (
    ModelResponseError,
    ValidationError,
    parse_model_response,
    validate_triage_request,
)

VALID_TICKET = {
    "ticket_id": "tkt-042",
    "subject": "Checkout webhooks timing out after regional failover",
    "body": "Multiple enterprise tenants report 503 errors on payment confirmation webhooks.",
}

VALID_MODEL_OUTPUT = {
    "severity": "P1",
    "category": "incident",
    "confidence": 0.96,
    "summary": "Regional failover causing 503 timeouts on enterprise payment webhooks.",
    "draft_reply": "We have escalated this P1 payment webhook outage to our on-call SRE team.",
}


def test_valid_request_is_accepted_and_stripped():
    result = validate_triage_request(
        {"ticket_id": "  tkt-042  ", "subject": "  Login broken  ", "body": "  I cannot sign in at all.  "}
    )
    assert result == {
        "ticket_id": "tkt-042",
        "subject": "Login broken",
        "body": "I cannot sign in at all.",
    }


@pytest.mark.parametrize(
    "payload, message",
    [
        ("not-an-object", "must be a JSON object"),
        ({}, "ticket_id"),
        ({**VALID_TICKET, "ticket_id": ""}, "ticket_id"),
        ({**VALID_TICKET, "ticket_id": 42}, "ticket_id"),
        ({**VALID_TICKET, "subject": "ab"}, "at least 3"),
        ({**VALID_TICKET, "subject": None}, "subject"),
        ({**VALID_TICKET, "body": "too short"}, "at least 10"),
        ({**VALID_TICKET, "body": "x" * 8001}, "at most 8000"),
    ],
)
def test_invalid_requests_are_rejected(payload, message):
    with pytest.raises(ValidationError) as exc:
        validate_triage_request(payload)
    assert message in str(exc.value)


def test_control_characters_are_rejected():
    with pytest.raises(ValidationError, match="control characters"):
        validate_triage_request({**VALID_TICKET, "subject": "bad\x00subject"})


def test_clean_model_output_parses():
    parsed = parse_model_response(json.dumps(VALID_MODEL_OUTPUT))
    assert parsed["severity"] == "P1"
    assert parsed["category"] == "incident"
    assert parsed["confidence"] == 0.96
    assert parsed["summary"].startswith("Regional failover")


def test_markdown_fenced_output_parses():
    text = "```json\n" + json.dumps(VALID_MODEL_OUTPUT) + "\n```"
    assert parse_model_response(text)["category"] == "incident"


def test_output_surrounded_by_prose_parses():
    text = "Here is the triage:\n" + json.dumps(VALID_MODEL_OUTPUT) + "\nHope that helps."
    assert parse_model_response(text)["severity"] == "P1"


def test_lowercase_severity_and_category_are_normalised():
    text = json.dumps({**VALID_MODEL_OUTPUT, "severity": "p2", "category": "SECURITY"})
    parsed = parse_model_response(text)
    assert parsed["severity"] == "P2"
    assert parsed["category"] == "security"


@pytest.mark.parametrize("alias, expected", [("How-To", "how_to"), ("question", "how_to"), ("outage", "incident")])
def test_category_aliases_resolve(alias, expected):
    text = json.dumps({**VALID_MODEL_OUTPUT, "category": alias})
    assert parse_model_response(text)["category"] == expected


def test_invalid_severity_is_rejected():
    with pytest.raises(ModelResponseError, match="severity"):
        parse_model_response(json.dumps({**VALID_MODEL_OUTPUT, "severity": "P0"}))


def test_invalid_category_is_rejected():
    with pytest.raises(ModelResponseError, match="category"):
        parse_model_response(json.dumps({**VALID_MODEL_OUTPUT, "category": "nonsense"}))


def test_missing_narrative_fields_are_rejected():
    with pytest.raises(ModelResponseError, match="summary"):
        parse_model_response(json.dumps({k: v for k, v in VALID_MODEL_OUTPUT.items() if k != "summary"}))
    with pytest.raises(ModelResponseError, match="draft_reply"):
        parse_model_response(
            json.dumps({k: v for k, v in VALID_MODEL_OUTPUT.items() if k != "draft_reply"})
        )


def test_confidence_is_clamped_and_defaulted():
    high = parse_model_response(json.dumps({**VALID_MODEL_OUTPUT, "confidence": 7}))
    low = parse_model_response(json.dumps({**VALID_MODEL_OUTPUT, "confidence": -3}))
    missing = parse_model_response(
        json.dumps({k: v for k, v in VALID_MODEL_OUTPUT.items() if k != "confidence"})
    )
    nan = parse_model_response(json.dumps({**VALID_MODEL_OUTPUT, "confidence": "nan"}))
    assert high["confidence"] == 1.0
    assert low["confidence"] == 0.0
    assert missing["confidence"] == 0.0
    assert nan["confidence"] == 0.0


def test_non_json_output_is_rejected():
    with pytest.raises(ModelResponseError, match="no JSON object"):
        parse_model_response("I could not classify this ticket.")
    with pytest.raises(ModelResponseError, match="not valid JSON"):
        parse_model_response("{severity: P1}")


def test_empty_output_is_rejected():
    with pytest.raises(ModelResponseError, match="empty"):
        parse_model_response("   ")
