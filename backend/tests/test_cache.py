"""Tests for normalised cache keys and fail-open TTL behaviour."""

import pytest

from cache import ResponseCache, build_cache_key

BASE_SUBJECT = "Elevated API latency in eu-west-1"
BASE_BODY = (
    "Since 2026-11-20T04:12:00Z, API p95 latency in eu-west-1 has climbed above 4 seconds "
    "for roughly 18% of requests."
)


def test_key_ignores_ticket_ids_timestamps_case_and_whitespace():
    variants = [
        (BASE_SUBJECT, BASE_BODY),
        (BASE_SUBJECT.upper(), BASE_BODY.replace("2026-11-20T04:12:00Z", "2026-11-21T09:31:00Z")),
        (BASE_SUBJECT, "  " + BASE_BODY.replace(" ", "   ") + "  "),
        ("tkt-999 " + BASE_SUBJECT, BASE_BODY.replace("2026-11-20T04:12:00Z", "2026-11-22T11:05:00Z")),
    ]
    keys = {build_cache_key(subject, body) for subject, body in variants}
    assert len(keys) == 1
    assert len(next(iter(keys))) == 64


def test_different_content_produces_different_keys():
    assert build_cache_key("Login fails", "Cannot sign in at all.") != build_cache_key(
        "Invoice missing", "The May invoice is missing."
    )


def test_uuid_is_ignored():
    first = build_cache_key("Sync error", "Request 9f1c2d3e-4a5b-6c7d-8e9f-0a1b2c3d4e5f failed.")
    second = build_cache_key("Sync error", "Request 11112222-3333-4444-5555-666677778888 failed.")
    assert first == second


class FakeTable:
    def __init__(self, item=None, get_error=None, put_error=None):
        self.item = item
        self.get_error = get_error
        self.put_error = put_error
        self.puts = []

    def get_item(self, Key):
        if self.get_error:
            raise self.get_error
        return {"Item": self.item} if self.item else {}

    def put_item(self, Item):
        if self.put_error:
            raise self.put_error
        self.item = Item
        self.puts.append(Item)


def test_live_entry_is_returned():
    table = FakeTable(item={"cache_key": "k", "payload": {"severity": "P4"}, "expires_at": 1100})
    cache = ResponseCache(table=table, clock=lambda: 1000)
    assert cache.get("k") == {"severity": "P4"}


def test_expired_entry_is_a_miss():
    table = FakeTable(item={"cache_key": "k", "payload": {"severity": "P4"}, "expires_at": 999})
    cache = ResponseCache(table=table, clock=lambda: 1000)
    assert cache.get("k") is None


def test_read_error_fails_open():
    cache = ResponseCache(table=FakeTable(get_error=RuntimeError("ddb down")), clock=lambda: 1000)
    assert cache.get("k") is None


def test_put_writes_ttl_and_returns_true():
    table = FakeTable()
    cache = ResponseCache(table=table, clock=lambda: 1000, ttl_seconds=86400)
    assert cache.put("k", {"severity": "P3"}) is True
    assert table.puts[0]["expires_at"] == 87400
    assert table.puts[0]["payload"] == {"severity": "P3"}


def test_write_error_fails_open():
    cache = ResponseCache(table=FakeTable(put_error=RuntimeError("ddb down")))
    assert cache.put("k", {"severity": "P3"}) is False


def test_missing_table_name_fails_open():
    cache = ResponseCache(table_name=None)
    cache._table_name = None
    assert cache.get("k") is None
    assert cache.put("k", {"severity": "P3"}) is False
