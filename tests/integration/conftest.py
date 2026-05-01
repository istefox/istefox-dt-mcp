"""Fixtures for Tier 3 integration tests against a real DEVONthink 4.

These tests are skipped by default. Run with `pytest -m integration`
and ensure DEVONthink is running with at least one open database.
"""

from __future__ import annotations

import subprocess
from collections.abc import AsyncIterator

import pytest
from istefox_dt_mcp_adapter.jxa import JXAAdapter

# Probe timeout: a healthy `osascript` round-trip is well under 1s; we
# allow 2s for slow boots / Apple Events permission dialog.
_DT_PROBE_TIMEOUT_S = 2.0


def _probe_devonthink() -> tuple[bool, str | None]:
    """Best-effort sync probe.

    Returns `(reachable, skip_reason)` where:
    - `reachable=True, skip_reason=None`: DT is running AND we have
      AppleEvents permission to talk to it.
    - `reachable=False, skip_reason=<msg>`: actionable message
      explaining why we can't proceed.

    We use a sync subprocess (not asyncio) because the autouse fixture
    runs at setup time before an event loop is guaranteed to exist.
    """
    # Probe in two phases inside one osascript call:
    # 1. running() — does NOT require AppleEvents permission, so we can
    #    distinguish "DT not running" from "DT up but no permission".
    # 2. databases().length — DOES require permission. We use it to
    #    catch -1743 here instead of letting every test ERROR.
    # `version()` would not work for (2): it returns OK without
    # permission, so it cannot detect a missing entitlement.
    try:
        proc = subprocess.run(
            [
                "osascript",
                "-l",
                "JavaScript",
                "-e",
                (
                    "var app = Application('DEVONthink'); "
                    "if (!app.running()) { 'NOT_RUNNING'; } "
                    "else { JSON.stringify(app.databases().length); }"
                ),
            ],
            capture_output=True,
            timeout=_DT_PROBE_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return (
            False,
            "DEVONthink probe timed out — DT may be unresponsive, restart it",
        )
    except FileNotFoundError:
        return False, "osascript not found — are you on macOS?"

    stderr = proc.stderr.decode("utf-8", errors="replace")
    # AppleEvents permission denied = DT exists but the host terminal
    # has no Automation entitlement. Surfacing this as a skip with an
    # actionable hint is friendlier than letting every test ERROR.
    if "(-1743)" in stderr or "Not authorized" in stderr:
        return (
            False,
            "AppleEvents permission denied for DEVONthink — grant it in "
            "System Settings -> Privacy & Security -> Automation",
        )
    if "Application isn't running" in stderr:
        return (
            False,
            "DEVONthink not running — start it before running integration tests",
        )
    if proc.returncode != 0:
        return (
            False,
            f"DEVONthink probe failed (rc={proc.returncode}): {stderr.strip()[:200]}",
        )

    stdout = proc.stdout.decode("utf-8", errors="replace").strip()
    if stdout == "NOT_RUNNING":
        return (
            False,
            "DEVONthink not running — start it before running integration tests",
        )
    # Non-empty stdout means we got a version string back -> reachable.
    if not stdout:
        return False, "DEVONthink probe returned empty output"
    return True, None


@pytest.fixture(autouse=True)
def dt_running() -> None:
    """Autouse guard: skip the integration module if DT can't be reached.

    Using autouse means individual tests don't need to opt in. The
    skip reason is always actionable (start DT, grant permission, ...).
    """
    reachable, reason = _probe_devonthink()
    if not reachable:
        assert reason is not None
        pytest.skip(reason)


@pytest.fixture
async def real_adapter() -> AsyncIterator[JXAAdapter]:
    """A JXAAdapter wired against the real DEVONthink (no cache).

    cache=None so each test sees fresh JXA round-trips (no stale
    state across tests); pool_size=2 keeps load light on the user's
    running DT; timeout=10s tolerates slow first-call warmup.
    """
    adapter = JXAAdapter(pool_size=2, timeout_s=10.0, max_retries=2, cache=None)
    yield adapter


@pytest.fixture
async def first_open_database(real_adapter: JXAAdapter) -> str:
    """Name of the first open database; skip if none open."""
    databases = await real_adapter.list_databases()
    open_dbs = [db for db in databases if db.is_open]
    if not open_dbs:
        pytest.skip("No open DEVONthink databases — open at least one DB and retry")
    # `str(...)` keeps mypy happy under strict mode (the schemas pkg
    # is treated as `Any` because of `ignore_missing_imports = true`).
    return str(open_dbs[0].name)
