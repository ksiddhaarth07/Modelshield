"""Strict request validation, prompt-injection safeguards, and defensive parsing.

The Lambda boundary is untrusted: API Gateway forwards whatever the caller
sends. Everything in this module is stdlib-only so it runs unchanged on the
``python3.13`` managed runtime with zero deployment packaging.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Dict, List, Mapping

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
_LOG_CONTROL_CHARS = re.compile(r"(?:\x1b\[[0-9;]*[A-Za-z]|[\x00-\x1f\x7f])")
_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)

_PROMPT_INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(?:all\s+|any\s+)?(?:previous|prior|above)\s+instructions?\b", re.I),
    re.compile(r"\bdisregard\s+(?:all\s+|any\s+)?(?:previous|prior|system)\s+(?:instructions?|rules?)\b", re.I),
    re.compile(r"\b(?:reveal|print|output|show|leak|dump)\s+(?:the\s+|your\s+)?(?:system\s+prompt|hidden\s+instructions?|developer\s+prompt)\b", re.I),
    re.compile(r"\byou\s+are\s+now\s+(?:in\s+developer\s+mode|dan|unrestricted|a\s+different)\b", re.I),
    re.compile(r"\b(?:override|force|set)\s+(?:severity|classification)\s*(?:to|=|:)\s*p[1-4]\b", re.I),
    re.compile(r"</?\s*untrusted_ticket_(?:body|subject|id)\s*>", re.I),
    re.compile(r"^\s*(?:system|developer|assistant)\s*:\s*(?:ignore|override|output)\b", re.I | re.M),
)

_CRITICAL_P1_SECURITY_PATTERNS = (
    re.compile(r"\bransomware\b", re.I),
    re.compile(r"\bactive\s+(?:data\s+)?breach\b", re.I),
    re.compile(r"\bprivilege\s+escalation\b", re.I),
    re.compile(r"\bunauthorized\s+admin(?:istrator)?\s+access\b", re.I),
    re.compile(r"\bproduction\s+(?:api\s+)?(?:key|token|secret|credential)s?\s+(?:was\s+|were\s+)?(?:leaked|pushed|exposed|committed)\s+to\s+(?:a\s+)?public\b", re.I),
    re.compile(r"\bexfiltrat(?:ing|ed|ion)\s+(?:customer|tenant|production)\s+data\b", re.I),
    re.compile(r"\bmass\s+account\s+takeover\b", re.I),
    re.compile(r"\bdata\s+exfiltration\b", re.I),
)

_OUTPUT_LEAK_PATTERNS = (
    re.compile(r"SEVERITY\s*-\s*first match wins", re.I),
    re.compile(r"UNTRUSTED INPUT\s*&\s*SECURITY RULES", re.I),
    re.compile(r"BOUNDARY RULINGS:", re.I),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN\s+(?:RSA\s+|EC\s+|OPENSSH\s+)?PRIVATE\s+KEY-----"),
    re.compile(r"\baws_secret_access_key\b", re.I),
    re.compile(r"\bRESPONSE_CACHE_TABLE\b|\bTICKETS_TABLE\b"),
    re.compile(r"<\s*/?\s*script\b", re.I),
)

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


def sanitize_log_value(value: Any, max_len: int = 128) -> str:
    """Strip CR/LF/tabs/ANSI escapes so untrusted values cannot inject log lines."""

    if value is None:
        return "-"
    cleaned = _LOG_CONTROL_CHARS.sub(" ", str(value))
    cleaned = " ".join(cleaned.split())
    return cleaned[:max_len] or "-"


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


def detect_prompt_injection(ticket: Mapping[str, str]) -> bool:
    """Detect common prompt-injection or instruction-override phrases in ticket input."""

    text = f"{ticket.get('subject', '')}\n{ticket.get('body', '')}"
    return any(pattern.search(text) for pattern in _PROMPT_INJECTION_PATTERNS)


def detect_critical_p1_security(ticket: Mapping[str, str]) -> bool:
    """Deterministic check for high-confidence active P1 security incidents."""

    text = f"{ticket.get('subject', '')}\n{ticket.get('body', '')}"
    return any(pattern.search(text) for pattern in _CRITICAL_P1_SECURITY_PATTERNS)


def apply_security_safeguards(
    triage: Dict[str, Any],
    ticket: Mapping[str, str],
    *,
    prompt_injection_detected: Optional[bool] = None,
) -> Dict[str, Any]:
    """Enforce deterministic P1 security guardrails and human-review requirements."""

    result = dict(triage)
    if prompt_injection_detected is None:
        prompt_injection_detected = detect_prompt_injection(ticket)
    critical_security = detect_critical_p1_security(ticket)

    flags: List[str] = []
    if prompt_injection_detected:
        flags.append("prompt_injection_detected")
        # Never allow an untrusted injection payload to self-classify as low-priority how-to.
        if result.get("severity") == "P4" and result.get("category") == "how_to":
            result["severity"] = "P2"
            result["category"] = "security"
            result["confidence"] = min(float(result.get("confidence", 0.5)), 0.5)

    if critical_security:
        flags.append("deterministic_p1_security_guardrail")
        result["severity"] = "P1"
        if result.get("category") not in ("security", "incident"):
            result["category"] = "security"

    requires_review = bool(
        result.get("severity") == "P1"
        or result.get("category") == "security"
        or prompt_injection_detected
        or critical_security
        or float(result.get("confidence", 0.0)) < 0.70
    )
    if requires_review:
        flags.append("human_review_required")

    result["requires_human_review"] = requires_review
    if flags:
        result["security_flags"] = flags
    return result


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


def _required_safe_text(obj: Dict[str, Any], field: str, max_len: int) -> str:
    value = obj.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ModelResponseError(f"model response is missing '{field}'")
    cleaned = _CONTROL_CHARS.sub(" ", value).strip()[:max_len]
    if not cleaned:
        raise ModelResponseError(f"model response is missing '{field}'")
    if any(pattern.search(cleaned) for pattern in _OUTPUT_LEAK_PATTERNS):
        raise ModelResponseError("model output violated output safety policy")
    return cleaned


def parse_model_response(text: Any) -> Dict[str, Any]:
    """Parse and validate the triage JSON returned by Bedrock.

    Strictly validates enum fields, bounds text fields, and blocks model outputs
    that attempt to leak system instructions, secrets, or infrastructure names.
    """

    if not isinstance(text, str) or not text.strip():
        raise ModelResponseError("model returned an empty response")

    raw = _extract_json_object(text)
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ModelResponseError("model output is not valid JSON") from exc

    if not isinstance(obj, dict):
        raise ModelResponseError("model output must be a JSON object")

    severity = str(obj.get("severity", "")).strip().upper()
    if severity not in SEVERITIES:
        raise ModelResponseError(
            f"model severity '{sanitize_log_value(severity, 32)}' is not one of {', '.join(SEVERITIES)}"
        )

    category_raw = str(obj.get("category", "")).strip().lower()
    category_key = category_raw.replace(" ", "_").replace("-", "_")
    category = _CATEGORY_ALIASES.get(category_key, category_key)
    if category not in CATEGORIES:
        raise ModelResponseError(
            f"model category '{sanitize_log_value(category_raw, 32)}' is not one of {', '.join(CATEGORIES)}"
        )

    return {
        "severity": severity,
        "category": category,
        "confidence": _coerce_confidence(obj.get("confidence")),
        "summary": _required_safe_text(obj, "summary", MAX_SUMMARY_LEN),
        "draft_reply": _required_safe_text(obj, "draft_reply", MAX_REPLY_LEN),
    }
