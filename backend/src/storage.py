"""DynamoDB persistence for triage records and the live ``/stats`` rollup.

Writes are deliberately fail-open: a transient DynamoDB problem must never
turn a successful (and already billed) Bedrock triage into a 5xx for the
customer. The failure is logged and surfaced as ``persisted=false``.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Iterable, List, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from schemas import CATEGORIES, SEVERITIES

LOGGER = logging.getLogger(__name__)

MAX_SCAN_PAGES = 50
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


def save_triage(record: Dict[str, Any], table: Optional[Any] = None) -> bool:
    """Persist one triage record. Returns ``False`` on a swallowed write error."""

    try:
        _table(table).put_item(Item=record)
        return True
    except (ClientError, BotoCoreError, ValueError, TypeError) as exc:
        LOGGER.warning(
            "tickets_write_failed ticket_id=%s error=%s",
            record.get("ticket_id"),
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


def _scan_items(table: Any) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    kwargs: Dict[str, Any] = {
        "ProjectionExpression": "ticket_id, severity, category, telemetry, created_at"
    }
    for _ in range(MAX_SCAN_PAGES):
        response = table.scan(**kwargs)
        items.extend(response.get("Items", []) or [])
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


def get_stats(table: Optional[Any] = None) -> Dict[str, Any]:
    """Return an aggregate view of every stored triage for ``GET /stats``."""

    try:
        items = _scan_items(_table(table))
    except (ClientError, BotoCoreError) as exc:
        raise StorageError("ticket statistics are temporarily unavailable") from exc

    return _aggregate(items, os.environ.get("STACK_VERSION", "unknown"))
