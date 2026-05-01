"""JXAAdapter behavior with osascript mocked.

We patch `asyncio.create_subprocess_exec` to feed canned outputs and
assert: success path, retry, timeout, parse errors, DT-not-running.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from istefox_dt_mcp_adapter.errors import (
    AutomationPermissionError,
    DTNotRunningError,
    JXAError,
    JXAParseError,
    JXATimeoutError,
)
from istefox_dt_mcp_adapter.jxa import JXAAdapter


def _mock_proc(*, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    proc.kill = AsyncMock()
    return proc


@pytest.mark.asyncio
async def test_inline_returns_parsed_json() -> None:
    adapter = JXAAdapter(pool_size=1, timeout_s=2.0, max_retries=1)
    with patch(
        "asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=_mock_proc(stdout=b'"hello"\n')),
    ):
        result = await adapter._jxa_inline("'hello'")
    assert result == "hello"


@pytest.mark.asyncio
async def test_returncode_nonzero_raises_jxa_error() -> None:
    adapter = JXAAdapter(pool_size=1, timeout_s=2.0, max_retries=1)
    with (
        patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=_mock_proc(stderr=b"boom", returncode=1)),
        ),
        pytest.raises(JXAError),
    ):
        await adapter._jxa_inline("bad")


@pytest.mark.asyncio
async def test_app_isnt_running_raises_dt_not_running() -> None:
    adapter = JXAAdapter(pool_size=1, timeout_s=2.0, max_retries=1)
    with (
        patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(
                return_value=_mock_proc(
                    stderr=b"Application isn't running", returncode=1
                )
            ),
        ),
        pytest.raises(DTNotRunningError),
    ):
        await adapter._jxa_inline("anything")


@pytest.mark.asyncio
async def test_minus_1743_raises_automation_permission_error() -> None:
    adapter = JXAAdapter(pool_size=1, timeout_s=2.0, max_retries=1)
    stderr = b"execution error: Error: Si e' verificato un errore. (-1743)"
    with (
        patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=_mock_proc(stderr=stderr, returncode=1)),
        ),
        pytest.raises(AutomationPermissionError),
    ):
        await adapter._jxa_inline("expr")


@pytest.mark.asyncio
async def test_invalid_json_raises_parse_error() -> None:
    adapter = JXAAdapter(pool_size=1, timeout_s=2.0, max_retries=1)
    with (
        patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=_mock_proc(stdout=b"not json")),
        ),
        pytest.raises(JXAParseError),
    ):
        await adapter._jxa_inline("expr")


@pytest.mark.asyncio
async def test_timeout_raises_jxa_timeout() -> None:
    adapter = JXAAdapter(pool_size=1, timeout_s=0.05, max_retries=1)

    async def slow_communicate():
        import asyncio

        await asyncio.sleep(1)
        return (b"", b"")

    proc = AsyncMock()
    proc.communicate = slow_communicate
    proc.returncode = 0
    proc.kill = lambda: None

    with (
        patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=proc),
        ),
        pytest.raises(JXATimeoutError),
    ):
        await adapter._jxa_inline("expr")


@pytest.mark.asyncio
async def test_retry_on_transient_then_success() -> None:
    adapter = JXAAdapter(pool_size=1, timeout_s=2.0, max_retries=3)
    failing = _mock_proc(stderr=b"transient", returncode=1)
    ok = _mock_proc(stdout=b"42\n")
    seq = [failing, failing, ok]

    async def factory(*args, **kwargs):
        return seq.pop(0)

    with patch("asyncio.create_subprocess_exec", new=factory):
        result = (
            await adapter._run_script("list_databases.js") if False else None
        )  # noop guard — actual exercised below

    # Use _exec_osascript via inline path which is what _jxa_inline uses
    seq2 = [failing, failing, ok]

    async def factory2(*args, **kwargs):
        return seq2.pop(0)

    # _jxa_inline does NOT retry — only _run_script does. So instead
    # exercise _run_script with a real script name.
    seq3 = [failing, failing, ok]

    async def factory3(*args, **kwargs):
        return seq3.pop(0)

    with patch("asyncio.create_subprocess_exec", new=factory3):
        result = await adapter._run_script("list_databases.js")
    assert result == 42


@pytest.mark.asyncio
async def test_find_related_drops_seed_record() -> None:
    """Defense in depth: even if the JXA layer leaks the seed record
    into the results, the Python adapter must filter it out."""
    seed_uuid = "AAAA-BBBB-CCCC"
    raw = (
        b"["
        b'{"uuid":"AAAA-BBBB-CCCC","name":"seed","similarity":null,'
        b'"location":"/","reference_url":"x-d://AAAA-BBBB-CCCC"},'
        b'{"uuid":"OTHER-1","name":"other-1","similarity":null,'
        b'"location":"/","reference_url":"x-d://OTHER-1"}'
        b"]\n"
    )
    adapter = JXAAdapter(pool_size=1, timeout_s=2.0, max_retries=1, cache=None)
    with patch(
        "asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=_mock_proc(stdout=raw)),
    ):
        results = await adapter.find_related(seed_uuid, k=10)

    assert len(results) == 1
    assert results[0].uuid == "OTHER-1"
    assert all(r.uuid != seed_uuid for r in results)
