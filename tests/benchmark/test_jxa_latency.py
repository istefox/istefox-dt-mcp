"""JXA bridge latency baseline (mocked subprocess, runs in CI).

These benchmarks measure the bridge overhead with osascript stubbed
out — they answer "how much latency does our async/cache/retry layer
add on top of an instant subprocess?" Real-DT latency is measured
separately by `scripts/smoke_e2e.py`.

Run only on demand: `uv run pytest tests/benchmark --benchmark-only`.
The default test session (`pytest tests/unit`) skips this directory.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from istefox_dt_mcp_adapter.cache import SQLiteCache
from istefox_dt_mcp_adapter.jxa import JXAAdapter


def _mock_proc(stdout: bytes):
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, b""))
    proc.returncode = 0
    proc.kill = AsyncMock()
    return proc


@pytest.mark.benchmark(group="bridge")
def test_inline_call_overhead(benchmark) -> None:
    """How long does `_jxa_inline` take with an instant subprocess."""
    adapter = JXAAdapter(pool_size=1, timeout_s=2.0, max_retries=1)

    async def call() -> object:
        with patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=_mock_proc(b'"x"')),
        ):
            return await adapter._jxa_inline("'x'")

    def run():
        return asyncio.run(call())

    result = benchmark(run)
    assert result == "x"


@pytest.mark.benchmark(group="bridge")
def test_script_call_overhead(benchmark) -> None:
    """Same but going through `_run_script` (file path resolution + retry)."""
    adapter = JXAAdapter(pool_size=1, timeout_s=2.0, max_retries=1)
    payload = json.dumps([{"uuid": "u", "name": "n", "path": "/p", "is_open": True}])

    async def call() -> object:
        with patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=_mock_proc(payload.encode())),
        ):
            return await adapter._run_script("list_databases.js")

    def run():
        return asyncio.run(call())

    result = benchmark(run)
    assert isinstance(result, list)


@pytest.mark.benchmark(group="cache")
def test_cache_hit_latency(benchmark, tmp_path) -> None:
    """Cache read latency (per-record read / write payload roundtrip)."""
    cache = SQLiteCache(tmp_path / "c.sqlite", default_ttl_s=60.0)
    payload = {"uuid": "u", "name": "n", "tags": ["a", "b"], "size_bytes": 1024}
    cache.set("k", payload)
    result = benchmark(cache.get, "k")
    assert result == payload


@pytest.mark.benchmark(group="cache")
def test_cache_miss_latency(benchmark, tmp_path) -> None:
    cache = SQLiteCache(tmp_path / "c.sqlite", default_ttl_s=60.0)
    result = benchmark(cache.get, "missing")
    assert result is None
