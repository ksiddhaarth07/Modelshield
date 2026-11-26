"""ModelShield Lambda entry point.

Routes (API Gateway HTTP API v2 payload):

* ``POST /triage`` - Cognito JWT auth, rate-limit, validate, Bedrock triage, persist, EMF
* ``GET  /health`` - public liveness probe (minimal non-sensitive info only)
* ``GET  /stats``  - admin-only, tenant-isolated aggregate stats from DynamoDB

The handler uses only the Python standard library and runtime ``boto3`` so
``arm64`` deployments stay Docker-free with zero native wheels.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from auth import (
    AuthContext,
    AuthenticationError,
    AuthorizationError,
    authenticate_event,
    authorize_stats,
    authorize_triage,
    enforce_no_body_identity_spoofing,
)
from bedrock_client import NOVA_LITE, NOVA_PRO, BedrockClient, BedrockInvocationError
from metrics import emit_triage_metrics
from prompts import SYSTEM_PROMPT, build_user_prompt
from rate_limit import RateLimitExceeded, RateLimiter
from router import AdaptiveRouter, RouteOutcome, build_router
from schemas import (
    ModelResponseError,
    ValidationError,
    apply_security_safeguards,
    detect_prompt_injection,
    parse_model_response,
    sanitize_log_value,
    validate_triage_request,
)
from storage import StorageError, get_stats, save_triage

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
LOGGER = logging.getLogger()
LOGGER.setLevel(LOG_LEVEL)
if not LOGGER.handlers:
    logging.basicConfig(level=LOG_LEVEL)

MAX_RAW_BODY_BYTES = 32_768
MAX_BODY_BYTES = 16_384

_SECURITY_HEADERS = {
    "Content-Type": "application/json",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": "default-src 'none'",
    "Referrer-Policy": "no-referrer",
}

_BEDROCK_CLIENT: Optional[BedrockClient] = None
_ROUTER: Optional[AdaptiveRouter] = None
_RATE_LIMITER: Optional[RateLimiter] = None


class PayloadTooLargeError(ValueError):
    """Raised when an HTTP request body exceeds configured byte limits."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _env(name: str, default: str) -> str:
    return os.environ.get(name) or default


def _allowed_origins() -> List[str]:
    raw = os.environ.get("ALLOWED_ORIGINS", "")
    return [origin.strip() for origin in raw.split(",") if origin.strip() and origin.strip() != "*"]


def _request_origin(event: Optional[Dict[str, Any]]) -> str:
    if not isinstance(event, dict):
        return ""
    headers = event.get("headers") or {}
    if not isinstance(headers, dict):
        return ""
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == "origin" and isinstance(value, str):
            return value.strip()
    return ""


def _response_headers(
    event: Optional[Dict[str, Any]] = None,
    *,
    include_content_type: bool = True,
    extra_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    headers = dict(_SECURITY_HEADERS)
    if not include_content_type:
        headers.pop("Content-Type", None)

    origin = _request_origin(event)
    allowed = _allowed_origins()
    if origin and origin in allowed:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
        headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
        headers["Vary"] = "Origin"

    if extra_headers:
        headers.update(extra_headers)
    return headers


def _json_response(
    status_code: int,
    payload: Dict[str, Any],
    event: Optional[Dict[str, Any]] = None,
    extra_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": _response_headers(event, include_content_type=True, extra_headers=extra_headers),
        "body": json.dumps(payload, separators=(",", ":"), default=str),
    }


def _empty_response(status_code: int, event: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": _response_headers(event, include_content_type=False),
        "body": "",
    }


def _route(event: Dict[str, Any]) -> Tuple[str, str]:
    request_context = event.get("requestContext") or {}
    http = request_context.get("http") or {}
    method = str(http.get("method") or event.get("httpMethod") or "GET").upper()
    path = str(event.get("rawPath") or event.get("path") or "/")
    if len(path) > 1:
        path = path.rstrip("/")
    return method, path


def _request_id(event: Dict[str, Any]) -> str:
    request_context = event.get("requestContext") or {}
    raw = request_context.get("requestId") if isinstance(request_context, dict) else None
    return sanitize_log_value(raw or uuid.uuid4(), max_len=64)


def _parse_body(event: Dict[str, Any]) -> Dict[str, Any]:
    body = event.get("body")
    if body is None:
        raise ValidationError("request body is required")
    if not isinstance(body, str):
        raise ValidationError("request body must be text")

    if len(body.encode("utf-8", errors="replace")) > MAX_RAW_BODY_BYTES:
        raise PayloadTooLargeError("request body exceeds maximum allowed size")

    if event.get("isBase64Encoded"):
        try:
            decoded_bytes = base64.b64decode(body, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValidationError("request body is not valid base64 text") from exc
        if len(decoded_bytes) > MAX_BODY_BYTES:
            raise PayloadTooLargeError("request body exceeds maximum allowed size")
        try:
            body = decoded_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationError("request body is not valid UTF-8 text") from exc
    elif len(body.encode("utf-8")) > MAX_BODY_BYTES:
        raise PayloadTooLargeError("request body exceeds maximum allowed size")

    if not body.strip():
        raise ValidationError("request body is required")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValidationError("request body must be valid JSON") from exc

    if not isinstance(payload, dict):
        raise ValidationError("request body must be a JSON object")
    return payload


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _memory_mb(context: Optional[Any]) -> int:
    if context is not None:
        configured = getattr(context, "memory_limit_in_mb", None)
        if configured:
            try:
                return int(configured)
            except (TypeError, ValueError):
                pass
    try:
        return int(_env("AWS_LAMBDA_FUNCTION_MEMORY_SIZE", "512"))
    except ValueError:
        return 512


def _heavy_model_id() -> str:
    return _env("HEAVY_MODEL_ID", _env("MODEL_ID", NOVA_PRO))


def _light_model_id() -> str:
    return _env("LIGHT_MODEL_ID", NOVA_LITE)


def _bedrock_client() -> BedrockClient:
    global _BEDROCK_CLIENT
    if _BEDROCK_CLIENT is None:
        _BEDROCK_CLIENT = BedrockClient(model_id=_heavy_model_id())
    return _BEDROCK_CLIENT


def _is_v2() -> bool:
    return _env("STACK_VERSION", "v1") == "v2"


def _get_router() -> AdaptiveRouter:
    global _ROUTER
    if _ROUTER is None:
        _ROUTER = build_router()
    return _ROUTER


def _get_rate_limiter() -> RateLimiter:
    global _RATE_LIMITER
    if _RATE_LIMITER is None:
        _RATE_LIMITER = RateLimiter()
    return _RATE_LIMITER


def _run_triage(ticket: Dict[str, str], tenant_id: str = "default") -> RouteOutcome:
    """v1 uses one Pro call with prompt/schema guardrails; v2 uses adaptive routing."""

    if _is_v2():
        return _get_router().route(ticket, tenant_id=tenant_id)

    prompt_injected = detect_prompt_injection(ticket)
    invocation = _bedrock_client().converse(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=build_user_prompt(ticket),
    )
    triage = apply_security_safeguards(
        parse_model_response(invocation.text),
        ticket,
        prompt_injection_detected=prompt_injected,
    )
    return RouteOutcome(
        triage=triage,
        telemetry={
            "route_decision": "single_heavy",
            "model_id": invocation.model_id,
            "cache_hit": False,
            "escalated": False,
            "fallback_triggered": False,
            "input_tokens": invocation.input_tokens,
            "output_tokens": invocation.output_tokens,
            "frontier_tokens_used": invocation.input_tokens + invocation.output_tokens,
            "estimated_cost_usd": round(invocation.estimated_cost_usd, 10),
        },
    )


def _authenticate(event: Dict[str, Any]) -> Tuple[Optional[AuthContext], Optional[Dict[str, Any]]]:
    request_id = _request_id(event)
    try:
        return authenticate_event(event), None
    except AuthenticationError as exc:
        LOGGER.warning("auth_failed request_id=%s reason=%s", request_id, sanitize_log_value(str(exc)))
        return None, _json_response(
            401,
            {"error": "unauthorized", "message": "Authentication required.", "request_id": request_id},
            event,
        )


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------
def _health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "modelshield",
        "stack_version": _env("STACK_VERSION", "v1"),
        "timestamp": _utc_now(),
    }


def _handle_stats(event: Dict[str, Any]) -> Dict[str, Any]:
    request_id = _request_id(event)
    ctx, auth_err = _authenticate(event)
    if auth_err is not None or ctx is None:
        return auth_err  # type: ignore[return-value]

    try:
        authorize_stats(ctx)
    except AuthorizationError:
        LOGGER.warning(
            "stats_forbidden request_id=%s tenant=%s",
            request_id,
            sanitize_log_value(ctx.tenant_id),
        )
        return _json_response(
            403,
            {"error": "forbidden", "message": "Administrator privileges required.", "request_id": request_id},
            event,
        )

    try:
        _get_rate_limiter().check_and_consume(ctx.tenant_id, ctx.sub)
    except RateLimitExceeded as exc:
        return _json_response(
            429,
            {"error": "rate_limit_exceeded", "message": "Rate limit exceeded.", "request_id": request_id},
            event,
            extra_headers={"Retry-After": str(exc.retry_after)},
        )

    try:
        stats = get_stats(tenant_id=ctx.tenant_id)
    except StorageError:
        LOGGER.warning("stats_unavailable request_id=%s", request_id)
        return _json_response(
            503,
            {"error": "stats_unavailable", "message": "ticket statistics are temporarily unavailable"},
            event,
        )
    return _json_response(200, stats, event)


def _handle_triage(event: Dict[str, Any], context: Optional[Any]) -> Dict[str, Any]:
    request_id = _request_id(event)
    ctx, auth_err = _authenticate(event)
    if auth_err is not None or ctx is None:
        return auth_err  # type: ignore[return-value]

    try:
        authorize_triage(ctx)
    except AuthorizationError:
        LOGGER.warning(
            "triage_forbidden request_id=%s tenant=%s",
            request_id,
            sanitize_log_value(ctx.tenant_id),
        )
        return _json_response(
            403,
            {"error": "forbidden", "message": "Insufficient permissions for triage.", "request_id": request_id},
            event,
        )

    try:
        raw_payload = _parse_body(event)
        enforce_no_body_identity_spoofing(raw_payload, ctx)
        ticket = validate_triage_request(raw_payload)
    except PayloadTooLargeError:
        LOGGER.info("triage_payload_too_large request_id=%s", request_id)
        return _json_response(
            413,
            {
                "error": "payload_too_large",
                "message": "Request body exceeds maximum allowed size.",
                "request_id": request_id,
            },
            event,
        )
    except AuthorizationError:
        LOGGER.warning(
            "triage_identity_spoof_rejected request_id=%s tenant=%s",
            request_id,
            sanitize_log_value(ctx.tenant_id),
        )
        return _json_response(
            403,
            {
                "error": "forbidden",
                "message": "Cross-tenant or body identity overrides are not permitted.",
                "request_id": request_id,
            },
            event,
        )
    except ValidationError as exc:
        LOGGER.info(
            "triage_rejected request_id=%s reason=%s",
            request_id,
            sanitize_log_value(str(exc)),
        )
        return _json_response(
            400,
            {"error": "invalid_request", "message": str(exc), "request_id": request_id},
            event,
        )

    try:
        _get_rate_limiter().check_and_consume(ctx.tenant_id, ctx.sub)
    except RateLimitExceeded as exc:
        LOGGER.warning(
            "rate_limit_exceeded request_id=%s tenant=%s scope=%s",
            request_id,
            sanitize_log_value(ctx.tenant_id),
            exc.scope,
        )
        return _json_response(
            429,
            {
                "error": "rate_limit_exceeded",
                "message": "Too many requests. Please retry later.",
                "request_id": request_id,
            },
            event,
            extra_headers={"Retry-After": str(exc.retry_after)},
        )

    started = time.perf_counter()
    safe_ticket_id = sanitize_log_value(ticket["ticket_id"])
    try:
        outcome = _run_triage(ticket, tenant_id=ctx.tenant_id)
    except BedrockInvocationError as exc:
        LOGGER.error(
            "bedrock_failed request_id=%s ticket_id=%s error=%s",
            request_id,
            safe_ticket_id,
            type(exc).__name__,
        )
        return _json_response(
            502,
            {
                "error": "model_invocation_failed",
                "message": "triage model is temporarily unavailable; retry shortly",
                "request_id": request_id,
            },
            event,
        )
    except ModelResponseError as exc:
        LOGGER.error(
            "model_output_invalid request_id=%s ticket_id=%s reason=%s",
            request_id,
            safe_ticket_id,
            sanitize_log_value(str(exc)),
        )
        return _json_response(
            502,
            {
                "error": "model_response_invalid",
                "message": "triage model returned an invalid response",
                "request_id": request_id,
            },
            event,
        )

    triage = outcome.triage
    routing = outcome.telemetry

    elapsed_ms = max(1, int(round((time.perf_counter() - started) * 1000)))
    memory_mb = _memory_mb(context)
    gb_seconds = round((memory_mb / 1024.0) * (elapsed_ms / 1000.0), 4)

    telemetry = {
        "stack_version": _env("STACK_VERSION", "v1"),
        "route_decision": routing["route_decision"],
        "model_id": routing["model_id"],
        "cache_hit": bool(routing["cache_hit"]),
        "escalated": bool(routing["escalated"]),
        "fallback_triggered": bool(routing["fallback_triggered"]),
        "input_tokens": int(routing["input_tokens"]),
        "output_tokens": int(routing["output_tokens"]),
        "frontier_tokens_used": int(routing["frontier_tokens_used"]),
        "estimated_cost_usd": routing["estimated_cost_usd"],
        "latency_ms": elapsed_ms,
        "lambda_memory_mb": memory_mb,
        "lambda_gb_seconds": gb_seconds,
        "architecture": _env("ARCHITECTURE", "x86_64"),
    }

    body: Dict[str, Any] = {
        "ticket_id": ticket["ticket_id"],
        "severity": triage["severity"],
        "category": triage["category"],
        "confidence": triage["confidence"],
        "requires_human_review": bool(triage.get("requires_human_review", False)),
        "summary": triage["summary"],
        "draft_reply": triage["draft_reply"],
        "telemetry": telemetry,
    }
    if triage.get("security_flags"):
        body["security_flags"] = list(triage["security_flags"])

    record = dict(body)
    record["tenant_id"] = ctx.tenant_id
    record["created_at"] = _utc_now()
    record["request_id"] = request_id

    persisted = False
    try:
        persisted = save_triage(record)
    except Exception:  # defensive: persistence must never mask a paid triage
        LOGGER.exception("tickets_write_unexpected ticket_id=%s", safe_ticket_id)

    try:
        emit_triage_metrics(
            stack_version=telemetry["stack_version"],
            model_id=telemetry["model_id"],
            route_decision=telemetry["route_decision"],
            estimated_cost_usd=telemetry["estimated_cost_usd"],
            latency_ms=telemetry["latency_ms"],
            lambda_gb_seconds=telemetry["lambda_gb_seconds"],
            frontier_tokens=telemetry["frontier_tokens_used"],
            cache_hit=telemetry["cache_hit"],
            escalated=telemetry["escalated"],
            fallback_triggered=telemetry["fallback_triggered"],
        )
    except Exception:
        LOGGER.exception("emf_emit_failed ticket_id=%s", safe_ticket_id)

    LOGGER.info(
        "triage_complete request_id=%s tenant=%s ticket_id=%s severity=%s category=%s "
        "confidence=%.2f human_review=%s cost_usd=%.8f latency_ms=%s persisted=%s",
        request_id,
        sanitize_log_value(ctx.tenant_id),
        safe_ticket_id,
        triage["severity"],
        triage["category"],
        triage["confidence"],
        body["requires_human_review"],
        telemetry["estimated_cost_usd"],
        elapsed_ms,
        persisted,
    )
    return _json_response(200, body, event)


def _dispatch(event: Dict[str, Any], context: Optional[Any]) -> Dict[str, Any]:
    method, path = _route(event)

    if method == "OPTIONS":
        return _empty_response(204, event)
    if path == "/health" and method == "GET":
        return _json_response(200, _health(), event)
    if path == "/stats" and method == "GET":
        return _handle_stats(event)
    if path == "/triage" and method == "POST":
        return _handle_triage(event, context)
    return _json_response(404, {"error": "not_found", "message": "route not found"}, event)


def lambda_handler(event: Dict[str, Any], context: Optional[Any] = None) -> Dict[str, Any]:
    """AWS Lambda entry point. Never raises: every failure becomes JSON."""

    try:
        return _dispatch(event, context)
    except Exception:
        request_id = _request_id(event)
        LOGGER.exception("unhandled_exception request_id=%s", request_id)
        return _json_response(500, {"error": "internal_error", "request_id": request_id}, event)
