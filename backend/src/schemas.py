"""Strict request validation and defensive parsing of model output.

The Lambda boundary is untrusted: API Gateway forwards whatever the caller
sends. Everything in this module is stdlib-only so it runs unchanged on the
``python3.13`` managed runtime with zero deployment packaging.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Dict

SEVERITIES = ("P1", "P2", "P3", "P4")
CATEGORIES = ("incident", "security", "billing", "account", "how_to", "bug")

MIN_SUBJECT_LEN = 3
MAX_SUBJECT_LEN = 300
MIN_BODY_LEN = 10
MAX_BODY_LEN = 8000
MAX_TICKET_ID_LEN = 128
MAX_SUMMARY_LEN = 500
MAX_REPLY_LEN = 2000

# Printable text plus tabs/newlines only - blocks log-injection control chars.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)

_CATEGORY_ALIASES = {
    "how-to": "how_to",
    "howto": "how_to",
    "question": "how_to",
    "documentation": "how_to",
    "technical": "bug",
    "defect": "bug",
    "outage": "incident",
    "security_incident": "security",
    "billing_issue": "billing",
    "account_issue": "account",
    "access": "account",
}


class ValidationError(ValueError):
    """Raised when a request violates the public API contract."""


class ModelResponseError(ValidationError):
    """Raised when model output cannot be coerced into the triage contract."""


def _clean_text(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"'{field}' must be a string")
    if _CONTROL_CHARS.search(value):
        raise ValidationError(f"'{field}' contains control characters")
    cleaned = value.strip()
    if not cleaned:
        raise ValidationError(f"'{field}' must not be empty")
    return cleaned


def _bounded(value: Any, field: str, min_len: int, max_len: int) -> str:
    cleaned = _clean_text(value, field)
    if len(cleaned) < min_len:
        raise ValidationError(f"'{field}' must be at least {min_len} characters")
    if len(cleaned) > max_len:
        raise ValidationError(f"'{field}' must be at most {max_len} characters")
    return cleaned


def validate_triage_request(payload: Any) -> Dict[str, str]:
    """Validate and normalise ``POST /triage`` input.

    Returns a dict with stripped ``ticket_id``, ``subject`` and ``body``.
    Raises :class:`ValidationError` with a caller-safe message otherwise.
    """

    if not isinstance(payload, dict):
        raise ValidationError("request body must be a JSON object")

    ticket_id = _bounded(payload.get("ticket_id"), "ticket_id", 1, MAX_TICKET_ID_LEN)
    subject = _bounded(payload.get("subject"), "subject", MIN_SUBJECT_LEN, MAX_SUBJECT_LEN)
    body = _bounded(payload.get("body"), "body", MIN_BODY_LEN, MAX_BODY_LEN)
    return {"ticket_id": ticket_id, "subject": subject, "body": body}


def _extract_json_object(text: str) -> str:
    """Pull a JSON object out of a model response, tolerating markdown fences."""

    stripped = text.strip()
    fenced = _JSON_FENCE.search(stripped)
    if fenced:
        stripped = fenced.group(1).strip()

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ModelResponseError("model output contained no JSON object")
    return stripped[start : end + 1]


def _coerce_confidence(value: Any) -> float:
    if value is None or isinstance(value, bool):
        return 0.0
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(confidence):
        return 0.0
    return round(min(1.0, max(0.0, confidence)), 4)


def _required_text(obj: Dict[str, Any], field: str, max_len: int) -> str:
    value = obj.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ModelResponseError(f"model response is missing '{field}'")
    return value.strip()[:max_len]


def parse_model_response(text: Any) -> Dict[str, Any]:
    """Parse and validate the triage JSON returned by Bedrock.

    Deliberately strict on the two fields that drive automated routing
    (``severity`` and ``category``) and forgiving on cosmetic issues such as
    surrounding prose or code fences.
    """

    if not isinstance(text, str) or not text.strip():
        raise ModelResponseError("model returned an empty response")

    raw = _extract_json_object(text)
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ModelResponseError(f"model output is not valid JSON: {exc.msg}") from exc

    if not isinstance(obj, dict):
        raise ModelResponseError("model output must be a JSON object")

    severity = str(obj.get("severity", "")).strip().upper()
    if severity not in SEVERITIES:
        raise ModelResponseError(
            f"model severity '{severity}' is not one of {', '.join(SEVERITIES)}"
        )

    category_raw = str(obj.get("category", "")).strip().lower()
    category_key = category_raw.replace(" ", "_").replace("-", "_")
    category = _CATEGORY_ALIASES.get(category_key, category_key)
    if category not in CATEGORIES:
        raise ModelResponseError(
            f"model category '{category_raw}' is not one of {', '.join(CATEGORIES)}"
        )

    return {
        "severity": severity,
        "category": category,
        "confidence": _coerce_confidence(obj.get("confidence")),
        "summary": _required_text(obj, "summary", MAX_SUMMARY_LEN),
        "draft_reply": _required_text(obj, "draft_reply", MAX_REPLY_LEN),
    }
