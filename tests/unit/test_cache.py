"""Cache layer behavior."""

from __future__ import annotations

import time

from istefox_dt_mcp_adapter.cache import SQLiteCache


def test_set_and_get(cache: SQLiteCache) -> None:
    cache.set("foo", {"a": 1})
    assert cache.get("foo") == {"a": 1}


def test_get_missing_returns_none(cache: SQLiteCache) -> None:
    assert cache.get("missing") is None


def test_ttl_expiration(cache: SQLiteCache) -> None:
    cache.set("ephemeral", "value", ttl_s=0.05)
    assert cache.get("ephemeral") == "value"
    time.sleep(0.1)
    assert cache.get("ephemeral") is None


def test_invalidate(cache: SQLiteCache) -> None:
    cache.set("k", "v")
    cache.invalidate("k")
    assert cache.get("k") is None


def test_invalidate_prefix(cache: SQLiteCache) -> None:
    cache.set("record:1", "a")
    cache.set("record:2", "b")
    cache.set("other:1", "c")
    deleted = cache.invalidate_prefix("record:")
    assert deleted == 2
    assert cache.get("record:1") is None
    assert cache.get("other:1") == "c"


def test_purge_expired(cache: SQLiteCache) -> None:
    cache.set("a", 1, ttl_s=0.05)
    cache.set("b", 2, ttl_s=60)
    time.sleep(0.1)
    deleted = cache.purge_expired()
    assert deleted == 1
    assert cache.get("a") is None
    assert cache.get("b") == 2


def test_overwrite(cache: SQLiteCache) -> None:
    cache.set("k", "first")
    cache.set("k", "second")
    assert cache.get("k") == "second"
