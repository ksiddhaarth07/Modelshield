"""DynamoDB persistence for triage records and the live ``/stats`` rollup.

Writes are deliberately fail-open: a transient DynamoDB problem must never
turn a successful (and already billed) Bedrock triage into a 5xx for the
customer. The failure is logged and surfaced as ``persisted=false``.
"""

from __future__ import annotations

import logging
import os
import time
from decimal import Decimal
from typing import Any, Callable, Dict, Iterable, List, Optional

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import BotoCoreError, ClientError

from schemas import CATEGORIES, SEVERITIES, sanitize_log_value

LOGGER = logging.getLogger(__name__)

MAX_SCAN_PAGES = 50
DEFAULT_TICKET_TTL_SECONDS = 30 * 24 * 60 * 60
_TABLE_CACHE: Dict[str, Any] = {}


class StorageError(RuntimeError):
    """Raised when a read that callers depend on cannot be served."""


def _table(table: Optional[Any] = None) -> Any:
    if table is not None:
        return table

    name = os.environ.get("TICKETS_TABLE")
    if not name:
        raise StorageError("TICKETS_TABLE is not configured")

    if name not in _TABLE_CACHE:
        _TABLE_CACHE[name] = boto3.resource("dynamodb").Table(name)
    return _TABLE_CACHE[name]


def _to_ddb(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_ddb(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_ddb(v) for v in value]
    return value


def _ticket_ttl_seconds() -> int:
    raw = os.environ.get("TICKET_TTL_SECONDS", "").strip()
    if not raw:
        return DEFAULT_TICKET_TTL_SECONDS
    try:
        return max(60, int(raw))
    except ValueError:
        return DEFAULT_TICKET_TTL_SECONDS


def save_triage(
    record: Dict[str, Any],
    table: Optional[Any] = None,
    clock: Callable[[], float] = time.time,
) -> bool:
    """Persist one tenant-scoped triage record with TTL retention."""

    try:
        item = dict(record)
        if "expires_at" not in item:
            item["expires_at"] = int(clock()) + _ticket_ttl_seconds()
        _table(table).put_item(Item=_to_ddb(item))
        return True
    except (ClientError, BotoCoreError, ValueError, TypeError) as exc:
        LOGGER.warning(
            "tickets_write_failed ticket_id=%s error=%s",
            sanitize_log_value(record.get("ticket_id")),
            type(exc).__name__,
        )
        return False


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _percentile(values: List[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((percentile / 100.0) * (len(ordered) - 1)))
    return ordered[max(0, min(len(ordered) - 1, index))]


def _scan_items(table: Any, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    index_name = os.environ.get("TICKETS_TENANT_INDEX", "").strip()
    if tenant_id and index_name and hasattr(table, "query"):
        query_kwargs: Dict[str, Any] = {
            "IndexName": index_name,
            "KeyConditionExpression": Key("tenant_id").eq(tenant_id),
            "ProjectionExpression": "ticket_id, tenant_id, severity, category, telemetry, created_at",
        }
        for _ in range(MAX_SCAN_PAGES):
            response = table.query(**query_kwargs)
            for item in response.get("Items", []) or []:
                if item.get("tenant_id") == tenant_id:
                    items.append(item)
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            query_kwargs["ExclusiveStartKey"] = last_key
        return items

    kwargs: Dict[str, Any] = {
        "ProjectionExpression": "ticket_id, tenant_id, severity, category, telemetry, created_at"
    }
    if tenant_id:
        kwargs["FilterExpression"] = Attr("tenant_id").eq(tenant_id)
    for _ in range(MAX_SCAN_PAGES):
        response = table.scan(**kwargs)
        for item in response.get("Items", []) or []:
            if tenant_id and item.get("tenant_id") != tenant_id:
                continue
            items.append(item)
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        kwargs["ExclusiveStartKey"] = last_key
    return items


def _aggregate(items: Iterable[Dict[str, Any]], stack_version: str) -> Dict[str, Any]:
    severity_counts = {key: 0 for key in SEVERITIES}
    category_counts = {key: 0 for key in CATEGORIES}
    latencies: List[float] = []
    total_cost = 0.0
    frontier_tokens = 0
    cache_hits = 0
    escalations = 0
    fallbacks = 0
    created: List[str] = []
    total = 0

    for item in items:
        total += 1
        severity = str(item.get("severity", ""))
        category = str(item.get("category", ""))
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1

        telemetry = item.get("telemetry") or {}
        if isinstance(telemetry, dict):
            latencies.append(_as_float(telemetry.get("latency_ms")))
            total_cost += _as_float(telemetry.get("estimated_cost_usd"))
            frontier_tokens += int(_as_float(telemetry.get("frontier_tokens_used")))
            cache_hits += 1 if telemetry.get("cache_hit") else 0
            escalations += 1 if telemetry.get("escalated") else 0
            fallbacks += 1 if telemetry.get("fallback_triggered") else 0

        if item.get("created_at"):
            created.append(str(item["created_at"]))

    return {
        "stack_version": stack_version,
        "total_tickets": total,
        "by_severity": severity_counts,
        "by_category": category_counts,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
        "p95_latency_ms": round(_percentile(latencies, 95), 1),
        "total_cost_usd": round(total_cost, 6),
        "avg_cost_usd": round(total_cost / total, 8) if total else 0.0,
        "cache_hits": cache_hits,
        "escalations": escalations,
        "fallbacks": fallbacks,
        "frontier_tokens": frontier_tokens,
        "last_ticket_at": max(created) if created else None,
    }


def get_stats(
    tenant_id: Optional[str] = None, table: Optional[Any] = None
) -> Dict[str, Any]:
    """Return a tenant-isolated aggregate view of stored triages for ``GET /stats``."""

    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise StorageError("tenant scope is required for statistics")

    scoped_tenant = tenant_id.strip()
    try:
        items = _scan_items(_table(table), tenant_id=scoped_tenant)
    except (ClientError, BotoCoreError) as exc:
        raise StorageError("ticket statistics are temporarily unavailable") from exc

    stats = _aggregate(items, os.environ.get("STACK_VERSION", "unknown"))
    stats["tenant_id"] = scoped_tenant
    return stats
