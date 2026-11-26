"""Per-user and per-tenant rate limiting to prevent API abuse and Bedrock cost exhaustion."""

from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

import boto3
from botocore.exceptions import BotoCoreError, ClientError


class RateLimitExceeded(Exception):
    """Raised when a user or tenant exceeds the configured request quota."""

    def __init__(self, scope: str, limit: int, retry_after: int) -> None:
        self.scope = scope
        self.limit = limit
        self.retry_after = max(1, int(retry_after))
        super().__init__(f"{scope} rate limit exceeded ({limit} requests per window).")


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    user_remaining: int
    tenant_remaining: int
    retry_after: int = 0


def _bucket_key(prefix: str, identifier: str, window_id: int) -> str:
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:32]
    return f"rl:{prefix}:{digest}:{window_id}"


class InMemoryRateLimitStore:
    """Thread-safe container-local sliding/fixed window counter."""

    def __init__(self, max_keys: int = 4096) -> None:
        self._lock = threading.Lock()
        self._counts: Dict[str, Tuple[int, int]] = {}  # key -> (count, expires_at)
        self._max_keys = max_keys

    def increment_and_check(
        self, key: str, limit: int, expires_at: int, now: int
    ) -> Tuple[bool, int]:
        with self._lock:
            if len(self._counts) >= self._max_keys:
                self._prune(now)
            current, current_exp = self._counts.get(key, (0, expires_at))
            if current_exp <= now:
                current = 0
                current_exp = expires_at
            if current >= limit:
                return False, 0
            new_count = current + 1
            self._counts[key] = (new_count, current_exp)
            return True, max(0, limit - new_count)

    def _prune(self, now: int) -> None:
        expired = [k for k, (_, exp) in self._counts.items() if exp <= now]
        for k in expired:
            del self._counts[k]
        if len(self._counts) >= self._max_keys:
            # Drop oldest arbitrary entries if still full to bound memory.
            for k in list(self._counts.keys())[: len(self._counts) // 2]:
                del self._counts[k]

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()


class DynamoDBRateLimitStore:
    """Atomic DynamoDB counter store with TTL expiration."""

    def __init__(self, table_name: Optional[str] = None, table: Optional[Any] = None) -> None:
        self._table_name = (
            table_name
            if table_name is not None
            else (os.environ.get("RATE_LIMIT_TABLE") or os.environ.get("RESPONSE_CACHE_TABLE"))
        )
        self._table = table
        self._fallback = InMemoryRateLimitStore()

    def _resolve_table(self) -> Optional[Any]:
        if self._table is not None:
            return self._table
        if not self._table_name:
            return None
        self._table = boto3.resource("dynamodb").Table(self._table_name)
        return self._table

    def increment_and_check(
        self, key: str, limit: int, expires_at: int, now: int
    ) -> Tuple[bool, int]:
        table = self._resolve_table()
        if table is None:
            return self._fallback.increment_and_check(key, limit, expires_at, now)

        try:
            resp = table.update_item(
                Key={"cache_key": key},
                UpdateExpression="SET #ttl = if_not_exists(#ttl, :ttl) ADD #cnt :one",
                ConditionExpression="attribute_not_exists(#cnt) OR #cnt < :limit",
                ExpressionAttributeNames={"#cnt": "request_count", "#ttl": "expires_at"},
                ExpressionAttributeValues={
                    ":one": 1,
                    ":limit": int(limit),
                    ":ttl": int(expires_at),
                },
                ReturnValues="UPDATED_NEW",
            )
            new_count = int(resp.get("Attributes", {}).get("request_count", 1))
            return True, max(0, limit - new_count)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code == "ConditionalCheckFailedException":
                return False, 0
            # Fail safe to container-local limiter rather than failing open to Bedrock.
            return self._fallback.increment_and_check(key, limit, expires_at, now)
        except (BotoCoreError, OSError):
            return self._fallback.increment_and_check(key, limit, expires_at, now)


def _positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        val = int(raw)
        return max(1, val)
    except ValueError:
        return default


class RateLimiter:
    """Enforces independent per-user and per-tenant quotas from verified identity."""

    def __init__(
        self,
        store: Optional[Any] = None,
        *,
        user_limit: Optional[int] = None,
        tenant_limit: Optional[int] = None,
        window_seconds: Optional[int] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._user_limit = user_limit
        self._tenant_limit = tenant_limit
        self._window_seconds = window_seconds
        self._clock = clock

    def check_and_consume(self, tenant_id: str, user_id: str) -> RateLimitDecision:
        if not tenant_id or not user_id:
            raise ValueError("Verified tenant_id and user_id are required for rate limiting.")

        window_seconds = (
            self._window_seconds
            if self._window_seconds is not None
            else _positive_int_env("RATE_LIMIT_WINDOW_SECONDS", 60)
        )
        user_limit = (
            self._user_limit
            if self._user_limit is not None
            else _positive_int_env("USER_RATE_LIMIT_PER_MINUTE", 30)
        )
        tenant_limit = (
            self._tenant_limit
            if self._tenant_limit is not None
            else _positive_int_env("TENANT_RATE_LIMIT_PER_MINUTE", 120)
        )

        now = int(self._clock())
        window_id = now // window_seconds
        window_end = (window_id + 1) * window_seconds
        retry_after = max(1, window_end - now)
        expires_at = window_end + window_seconds

        store = self._store if self._store is not None else DynamoDBRateLimitStore()

        # Check tenant limit first to prevent multi-user exhaustion within a tenant.
        tenant_key = _bucket_key("tenant", tenant_id, window_id)
        tenant_ok, tenant_remaining = store.increment_and_check(
            tenant_key, tenant_limit, expires_at, now
        )
        if not tenant_ok:
            raise RateLimitExceeded("tenant", tenant_limit, retry_after)

        user_key = _bucket_key("user", f"{tenant_id}:{user_id}", window_id)
        user_ok, user_remaining = store.increment_and_check(
            user_key, user_limit, expires_at, now
        )
        if not user_ok:
            raise RateLimitExceeded("user", user_limit, retry_after)

        return RateLimitDecision(
            allowed=True,
            user_remaining=user_remaining,
            tenant_remaining=tenant_remaining,
        )
