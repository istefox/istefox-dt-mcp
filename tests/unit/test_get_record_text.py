"""JXAAdapter.get_record_text behavior."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from istefox_dt_mcp_adapter.cache import SQLiteCache
from istefox_dt_mcp_adapter.errors import RecordNotFoundError
from istefox_dt_mcp_adapter.jxa import JXAAdapter


def _mock_proc(*, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    proc.kill = AsyncMock()
    return proc


@pytest.mark.asyncio
async def test_get_record_text_returns_text() -> None:
    adapter = JXAAdapter(pool_size=1, timeout_s=2.0, max_retries=1)
    payload = json.dumps({"uuid": "abc", "text": "hello world"}).encode()
    with patch(
        "asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=_mock_proc(stdout=payload + b"\n")),
    ):
        text = await adapter.get_record_text("abc", max_chars=100)
    assert text == "hello world"


@pytest.mark.asyncio
async def test_get_record_text_record_not_found() -> None:
    adapter = JXAAdapter(pool_size=1, timeout_s=2.0, max_retries=1)
    payload = json.dumps({"error": "RECORD_NOT_FOUND"}).encode()
    with (
        patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=_mock_proc(stdout=payload + b"\n")),
        ),
        pytest.raises(RecordNotFoundError),
    ):
        await adapter.get_record_text("missing")


@pytest.mark.asyncio
async def test_get_record_text_empty_text_for_no_text_records() -> None:
    adapter = JXAAdapter(pool_size=1, timeout_s=2.0, max_retries=1)
    payload = json.dumps({"uuid": "img", "text": ""}).encode()
    with patch(
        "asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=_mock_proc(stdout=payload + b"\n")),
    ):
        text = await adapter.get_record_text("img")
    assert text == ""


@pytest.mark.asyncio
async def test_get_record_text_uses_cache(tmp_path) -> None:
    cache = SQLiteCache(tmp_path / "c.sqlite", default_ttl_s=60.0)
    adapter = JXAAdapter(pool_size=1, timeout_s=2.0, max_retries=1, cache=cache)
    payload = json.dumps({"uuid": "u", "text": "cached"}).encode()
    call_count = {"n": 0}

    async def factory(*args, **kwargs):
        call_count["n"] += 1
        return _mock_proc(stdout=payload + b"\n")

    with patch("asyncio.create_subprocess_exec", new=factory):
        a = await adapter.get_record_text("u", max_chars=100)
        b = await adapter.get_record_text("u", max_chars=100)

    assert a == b == "cached"
    assert call_count["n"] == 1  # second call served from cache
