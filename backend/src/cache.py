"""Normalised-key TTL cache for repeat triage requests (v2 only).

Design rules:

* The key is a SHA-256 of the ticket text after removing the noise that makes
  two copies of the same incident look different: ticket IDs, UUIDs, ISO-8601
  timestamps, casing and whitespace.
* Every operation is **fail-open**. A cache outage degrades ModelShield to
  v1 behaviour (a full model call) and never to a 5xx. Cache failures are
  logged, not raised.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, Optional

import boto3

LOGGER = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 24 * 60 * 60

# Order matters: timestamps contain digits that the ticket-ID pattern could
# otherwise partially consume, so strip structured tokens first.
_ISO_TIMESTAMP = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:z|[+-]\d{2}:?\d{2})?\b",
    re.IGNORECASE,
)
_UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_TICKET_ID = re.compile(
    r"\b(?:tkt|inc|case|ticket|req)[-_ ]?\d{2,}\b",
    re.IGNORECASE,
)
_WHITESPACE = re.compile(r"\s+")


class CacheUnavailable(RuntimeError):
    """Raised internally when the cache table is not configured."""


def build_cache_key(subject: str, body: str) -> str:
    """Return a stable SHA-256 key for a ticket, ignoring volatile noise."""

    if not isinstance(subject, str) or not isinstance(body, str):
        raise TypeError("subject and body must be strings")

    text = f"{subject}\n{body}".lower()
    text = _ISO_TIMESTAMP.sub(" ", text)
    text = _UUID.sub(" ", text)
    text = _TICKET_ID.sub(" ", text)
    text = _WHITESPACE.sub(" ", text).strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _to_ddb(value: Any) -> Any:
    """Convert Python floats to Decimal recursively so boto3 DynamoDB accepts them."""

    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_ddb(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_ddb(v) for v in value]
    return value


def _from_ddb(value: Any) -> Any:
    """Restore Decimal values returned by boto3 DynamoDB back to int/float."""

    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, dict):
        return {k: _from_ddb(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_ddb(v) for v in value]
    return value


class ResponseCache:
    """DynamoDB TTL cache with fail-open reads and writes."""

    def __init__(
        self,
        table: Optional[Any] = None,
        table_name: Optional[str] = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._table_obj = table
        self._table_name = table_name or os.environ.get("RESPONSE_CACHE_TABLE")
        self._ttl_seconds = ttl_seconds
        self._clock = clock

    def _get_table(self) -> Any:
        if self._table_obj is not None:
            return self._table_obj
        if not self._table_name:
            raise CacheUnavailable("RESPONSE_CACHE_TABLE is not configured")
        self._table_obj = boto3.resource("dynamodb").Table(self._table_name)
        return self._table_obj

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Return a live payload, or ``None`` for a miss, expiry or any error."""

        try:
            response = self._get_table().get_item(Key={"cache_key": key})
        except Exception as exc:  # fail-open by contract
            LOGGER.warning("cache_read_failed key=%s error=%s", key[:12], type(exc).__name__)
            return None

        item = response.get("Item") if isinstance(response, dict) else None
        if not item:
            return None

        try:
            expired = int(item.get("expires_at", 0)) <= int(self._clock())
        except (TypeError, ValueError):
            expired = True
        if expired:
            return None

        payload = item.get("payload")
        restored = _from_ddb(payload) if isinstance(payload, dict) else None
        return restored if isinstance(restored, dict) else None

    def put(self, key: str, payload: Dict[str, Any]) -> bool:
        """Write through with a 24 h TTL. Returns ``False`` on any error."""

        try:
            now = int(self._clock())
            self._get_table().put_item(
                Item={
                    "cache_key": key,
                    "payload": _to_ddb(payload),
                    "expires_at": now + self._ttl_seconds,
                    "created_at": _utc_now_iso(),
                }
            )
            return True
        except Exception as exc:  # fail-open by contract
            LOGGER.warning("cache_write_failed key=%s error=%s", key[:12], type(exc).__name__)
            return False
