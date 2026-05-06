"""Round-trip drift detection test against a live DEVONthink 4 instance.

Skip default — opt-in via the integration marker.

Requires (when un-stubbed):
- DT4 running
- fixtures-dt-mcp database open
- 3 records present in /Inbox of fixtures-dt-mcp

Currently a stub. Full body deferred to follow-up issue.
"""

from __future__ import annotations

import pytest

# Reuse the project's integration marker (registered in
# pyproject.toml [tool.pytest.ini_options].markers and auto-deselected
# via `-m 'not integration'` in addopts). Module-level marker matches
# the convention used in test_dt_smoke.py.
pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_bulk_apply_undo_drift_round_trip() -> None:
    """3-op batch: tag A, tag B, move C. Externally:
    - revert A's tag (should resolve to already_reverted)
    - add a foreign tag to B (should resolve to hostile_drift)
    - leave C untouched (should resolve to no_drift)

    Without --force: A skipped, B skipped, C reverted.
    With --force:    B also reverted, A still skipped (force does not
                     bypass already_reverted).

    Implementation deferred — see follow-up issue.
    """
    pytest.skip("integration test stub — needs conftest helpers (see follow-up issue)")
