"""ModelShield Lambda entry point.

Routes (API Gateway HTTP API v2 payload):

* ``POST /triage`` - validate, invoke Bedrock, persist, emit EMF, respond
* ``GET  /health`` - cheap liveness probe (no downstream calls)
* ``GET  /stats``  - aggregate view of everything stored in DynamoDB

The handler is intentionally framework-free: the Lambda ``python3.13`` runtime
already ships ``boto3``, and a zero-dependency bundle is what lets the v2
stack build for Graviton without a Docker daemon.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from bedrock_client import BedrockClient, BedrockInvocationError
from metrics import emit_triage_metrics
from prompts import SYSTEM_PROMPT, build_user_prompt
from schemas import (
    ModelResponseError,
    ValidationError,
    parse_model_response,
    validate_triage_request,
)
from storage import StorageError, get_stats, save_triage

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
LOGGER = logging.getLogger()
LOGGER.setLevel(LOG_LEVEL)
if not LOGGER.handlers:
    logging.basicConfig(level=LOG_LEVEL)

_CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Cache-Control": "no-store",
}

_BEDROCK_CLIENT: Optional[BedrockClient] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _env(name: str, default: str) -> str:
    return os.environ.get(name) or default


def _json_response(status_code: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": dict(_CORS_HEADERS),
        "body": json.dumps(payload, separators=(",", ":"), default=str),
    }


def _empty_response(status_code: int) -> Dict[str, Any]:
    headers = {key: value for key, value in _CORS_HEADERS.items() if key != "Content-Type"}
    return {"statusCode": status_code, "headers": headers, "body": ""}


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
    return str(request_context.get("requestId") or uuid.uuid4())


def _parse_body(event: Dict[str, Any]) -> Dict[str, Any]:
    body = event.get("body")
    if body is None:
        raise ValidationError("request body is required")

    if event.get("isBase64Encoded"):
        try:
            body = base64.b64decode(body).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValidationError("request body is not valid base64 text") from exc

    if not isinstance(body, str) or not body.strip():
        raise ValidationError("request body is required")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"request body is not valid JSON: {exc.msg}") from exc

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


def _bedrock_client() -> BedrockClient:
    global _BEDROCK_CLIENT
    if _BEDROCK_CLIENT is None:
        _BEDROCK_CLIENT = BedrockClient(model_id=_env("MODEL_ID", "us.amazon.nova-pro-v1:0"))
    return _BEDROCK_CLIENT


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------
def _health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "modelshield",
        "stack_version": _env("STACK_VERSION", "v1"),
        "model_id": _env("MODEL_ID", "us.amazon.nova-pro-v1:0"),
        "architecture": _env("ARCHITECTURE", "x86_64"),
        "region": _env("AWS_REGION", _env("AWS_DEFAULT_REGION", "us-east-1")),
        "tickets_table": _env("TICKETS_TABLE", ""),
        "timestamp": _utc_now(),
    }


def _handle_stats() -> Dict[str, Any]:
    try:
        stats = get_stats()
    except StorageError as exc:
        LOGGER.warning("stats_unavailable error=%s", type(exc).__name__)
        return _json_response(503, {"error": "stats_unavailable", "message": str(exc)})
    return _json_response(200, stats)


def _handle_triage(event: Dict[str, Any], context: Optional[Any]) -> Dict[str, Any]:
    request_id = _request_id(event)

    try:
        ticket = validate_triage_request(_parse_body(event))
    except ValidationError as exc:
        LOGGER.info("triage_rejected request_id=%s reason=%s", request_id, str(exc))
        return _json_response(
            400, {"error": "invalid_request", "message": str(exc), "request_id": request_id}
        )

    started = time.perf_counter()
    try:
        invocation = _bedrock_client().converse(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=build_user_prompt(ticket),
        )
    except BedrockInvocationError as exc:
        LOGGER.error(
            "bedrock_failed request_id=%s ticket_id=%s error=%s",
            request_id,
            ticket["ticket_id"],
            type(exc).__name__,
        )
        return _json_response(
            502,
            {
                "error": "model_invocation_failed",
                "message": "triage model is temporarily unavailable; retry shortly",
                "request_id": request_id,
            },
        )

    try:
        triage = parse_model_response(invocation.text)
    except ModelResponseError as exc:
        LOGGER.error(
            "model_output_invalid request_id=%s ticket_id=%s reason=%s",
            request_id,
            ticket["ticket_id"],
            str(exc),
        )
        return _json_response(
            502,
            {
                "error": "model_response_invalid",
                "message": "triage model returned an invalid response",
                "request_id": request_id,
            },
        )

    elapsed_ms = max(1, int(round((time.perf_counter() - started) * 1000)))
    memory_mb = _memory_mb(context)
    gb_seconds = round((memory_mb / 1024.0) * (elapsed_ms / 1000.0), 4)

    telemetry = {
        "stack_version": _env("STACK_VERSION", "v1"),
        "route_decision": "single_heavy",
        "model_id": invocation.model_id,
        "cache_hit": False,
        "escalated": False,
        "fallback_triggered": False,
        "input_tokens": invocation.input_tokens,
        "output_tokens": invocation.output_tokens,
        "frontier_tokens_used": invocation.input_tokens + invocation.output_tokens,
        "estimated_cost_usd": round(invocation.estimated_cost_usd, 10),
        "latency_ms": elapsed_ms,
        "lambda_memory_mb": memory_mb,
        "lambda_gb_seconds": gb_seconds,
        "architecture": _env("ARCHITECTURE", "x86_64"),
    }

    body = {
        "ticket_id": ticket["ticket_id"],
        "severity": triage["severity"],
        "category": triage["category"],
        "confidence": triage["confidence"],
        "summary": triage["summary"],
        "draft_reply": triage["draft_reply"],
        "telemetry": telemetry,
    }

    record = dict(body)
    record["created_at"] = _utc_now()
    record["request_id"] = request_id

    persisted = False
    try:
        persisted = save_triage(record)
    except Exception:  # defensive: persistence must never mask a paid triage
        LOGGER.exception("tickets_write_unexpected ticket_id=%s", ticket["ticket_id"])

    try:
        emit_triage_metrics(
            stack_version=telemetry["stack_version"],
            model_id=telemetry["model_id"],
            route_decision=telemetry["route_decision"],
            estimated_cost_usd=telemetry["estimated_cost_usd"],
            latency_ms=telemetry["latency_ms"],
            lambda_gb_seconds=telemetry["lambda_gb_seconds"],
            frontier_tokens=telemetry["frontier_tokens_used"],
            cache_hit=False,
            escalated=False,
            fallback_triggered=False,
        )
    except Exception:
        LOGGER.exception("emf_emit_failed ticket_id=%s", ticket["ticket_id"])

    LOGGER.info(
        "triage_complete request_id=%s ticket_id=%s severity=%s category=%s "
        "confidence=%.2f cost_usd=%.8f latency_ms=%s persisted=%s",
        request_id,
        ticket["ticket_id"],
        triage["severity"],
        triage["category"],
        triage["confidence"],
        telemetry["estimated_cost_usd"],
        elapsed_ms,
        persisted,
    )
    return _json_response(200, body)


def _dispatch(event: Dict[str, Any], context: Optional[Any]) -> Dict[str, Any]:
    method, path = _route(event)

    if method == "OPTIONS":
        return _empty_response(204)
    if path == "/health" and method == "GET":
        return _json_response(200, _health())
    if path == "/stats" and method == "GET":
        return _handle_stats()
    if path == "/triage" and method == "POST":
        return _handle_triage(event, context)
    return _json_response(
        404, {"error": "not_found", "message": f"no route for {method} {path}"}
    )


def lambda_handler(event: Dict[str, Any], context: Optional[Any] = None) -> Dict[str, Any]:
    """AWS Lambda entry point. Never raises: every failure becomes JSON."""

    try:
        return _dispatch(event, context)
    except Exception:
        LOGGER.exception("unhandled_exception request_id=%s", _request_id(event))
        return _json_response(500, {"error": "internal_error", "request_id": _request_id(event)})
