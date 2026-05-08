"""Round-trip drift detection test against a live DEVONthink 4 instance.

Skip default — opt-in via the integration marker.

Requires:
- DT4 running with AppleEvents permission granted to the host terminal
- `fixtures-dt-mcp` database open
- ≥3 records in `/Inbox` of `fixtures-dt-mcp` (seed via
  `uv run python scripts/setup_test_database.py`)

Exercises the full 3-state drift detection added to `bulk_apply` undo
in PR #64. The test:

1. Applies 3 ops via the registered `bulk_apply` MCP tool: tag A, tag B,
   move C from `/Inbox` to `/Archive`.
2. Externally mutates state to simulate three drift scenarios:
   - A's test tag is removed (mimics user already reverted).
   - B receives an unrelated foreign tag (mimics hostile interference).
   - C is left untouched.
3. Runs `undo_audit` in `dry_run` with `force=False` and asserts each op
   resolves to the expected drift state and the inverse plan contains
   only C (the no-drift op).
4. Repeats the dry-run with `force=True` and asserts the inverse plan
   now also contains B; A is *still* skipped because `force` does not
   bypass `already_reverted` (it only overrides `hostile_drift`).

A try/finally guard restores DT state regardless of test outcome.
"""

from __future__ import annotations

import contextlib
import os
import uuid as _uuid
from typing import TYPE_CHECKING, Any

import pytest
from istefox_dt_mcp_adapter.errors import AdapterError
from istefox_dt_mcp_server.undo import undo_audit

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from istefox_dt_mcp_adapter.jxa import JXAAdapter
    from istefox_dt_mcp_server.deps import Deps

# Module-level marker: every test in this file is an integration test.
# Combined with `-m "not integration"` in addopts, default sessions
# skip these without requiring per-test decorators.
pytestmark = pytest.mark.integration


def _unique_tag(role: str) -> str:
    """Build a per-run, per-role tag that won't clash with anything."""
    return f"__bulk_drift_test_{role}_{_uuid.uuid4().hex[:8]}"


def _structured(tool_result: Any) -> dict[str, Any]:
    """Extract structured_content from a FastMCP ToolResult."""
    if not hasattr(tool_result, "structured_content"):
        raise AssertionError(f"ToolResult missing structured_content: {tool_result!r}")
    return dict(tool_result.structured_content)


async def _safe_remove_tag(adapter: JXAAdapter, record_uuid: str, tag: str) -> None:
    """Best-effort tag removal; swallow adapter errors during cleanup."""
    with contextlib.suppress(AdapterError):
        await adapter.remove_tag(record_uuid, tag, dry_run=False)


async def _safe_move(adapter: JXAAdapter, record_uuid: str, destination: str) -> None:
    """Best-effort move; swallow adapter errors during cleanup."""
    with contextlib.suppress(AdapterError):
        await adapter.move_record(record_uuid, destination, dry_run=False)


@pytest.mark.asyncio
async def test_bulk_apply_undo_drift_round_trip(
    real_adapter: JXAAdapter,
    live_deps: Deps,
    mcp_server: FastMCP,
    fixtures_db_inbox_records: list[Any],
) -> None:
    """3-op batch + 3 drift states + undo dry-run with and without --force."""
    rec_a, rec_b, rec_c = fixtures_db_inbox_records[:3]
    tag_a = _unique_tag("a")
    tag_b = _unique_tag("b")
    tag_foreign = _unique_tag("foreign")
    move_destination = "/fixtures-dt-mcp/Archive"

    # Cleanup state — populated as we go so try/finally can always
    # reach it regardless of where in the test we fail.
    cleanup: dict[str, Any] = {
        "added_tags": [],  # list of (uuid, tag) to remove
        "moves_to_revert": [],  # list of (uuid, destination)
    }

    try:
        # ----- Phase 1: dry_run preview to get a confirm_token -----
        preview_input = {
            "operations": [
                {"record_uuid": rec_a.uuid, "op": "add_tag", "payload": {"tag": tag_a}},
                {"record_uuid": rec_b.uuid, "op": "add_tag", "payload": {"tag": tag_b}},
                {
                    "record_uuid": rec_c.uuid,
                    "op": "move",
                    "payload": {"destination": move_destination},
                },
            ],
            "dry_run": True,
            "stop_on_first_error": True,
        }
        preview_result = _structured(
            await mcp_server.call_tool("bulk_apply", {"input": preview_input})
        )
        assert preview_result.get("success") is True, preview_result
        preview_data = preview_result.get("data") or {}
        confirm_token = preview_data.get("preview_token")
        assert confirm_token, f"missing preview_token in {preview_data}"

        # ----- Phase 2: apply for real -----
        apply_input = {
            **preview_input,
            "dry_run": False,
            "confirm_token": confirm_token,
        }
        apply_result = _structured(
            await mcp_server.call_tool("bulk_apply", {"input": apply_input})
        )
        assert apply_result.get("success") is True, apply_result
        apply_data = apply_result.get("data") or {}
        assert apply_data.get("operations_applied") == 3, apply_data
        audit_id = apply_result.get("audit_id")
        assert audit_id, f"missing audit_id in apply result: {apply_result}"

        # Track what to revert in cleanup.
        cleanup["added_tags"].extend([(rec_a.uuid, tag_a), (rec_b.uuid, tag_b)])
        cleanup["moves_to_revert"].append((rec_c.uuid, rec_c.location))

        # ----- Phase 3: external mutation simulating 3 drift scenarios ----
        # A: revert the tag we just added → already_reverted
        await real_adapter.remove_tag(rec_a.uuid, tag_a, dry_run=False)
        # We just removed it, so cleanup no longer needs to.
        cleanup["added_tags"].remove((rec_a.uuid, tag_a))

        # B: add an unrelated tag on top → hostile_drift
        await real_adapter.apply_tag(rec_b.uuid, tag_foreign, dry_run=False)
        cleanup["added_tags"].append((rec_b.uuid, tag_foreign))

        # C: untouched → no_drift

        # ----- Phase 4: undo dry_run, force=False -----
        report_no_force = await undo_audit(
            live_deps, audit_id, dry_run=True, force=False
        )
        drift_per_op = report_no_force.get("drift_per_op") or []
        assert isinstance(drift_per_op, list)
        # bulk_apply undo evaluates ops in LIFO. Index in payload is
        # the original index from the apply call (0=A, 1=B, 2=C).
        by_uuid = {entry["uuid"]: entry for entry in drift_per_op}
        assert (
            by_uuid[rec_a.uuid]["drift_state"] == "already_reverted"
        ), "A should be already_reverted"
        assert (
            by_uuid[rec_b.uuid]["drift_state"] == "hostile_drift"
        ), "B should be hostile_drift"
        assert by_uuid[rec_c.uuid]["drift_state"] == "no_drift", "C should be no_drift"

        # Without --force: only C in inverse plan; A and B skipped.
        would_revert = report_no_force.get("would_revert") or []
        revert_uuids = {op["uuid"] for op in would_revert}
        assert revert_uuids == {
            rec_c.uuid
        }, f"force=False should plan only C; got {revert_uuids}"
        skipped_uuids = {s["uuid"] for s in report_no_force.get("skipped") or []}
        assert {rec_a.uuid, rec_b.uuid}.issubset(skipped_uuids)
        assert report_no_force.get("force_acknowledged") is False

        # ----- Phase 5: undo dry_run, force=True -----
        report_force = await undo_audit(live_deps, audit_id, dry_run=True, force=True)
        force_revert = {op["uuid"] for op in report_force.get("would_revert") or []}
        # A still skipped (already_reverted not bypassed by --force);
        # B and C now in plan.
        assert force_revert == {
            rec_b.uuid,
            rec_c.uuid,
        }, f"force=True should plan B+C; got {force_revert}"
        force_skipped = {s["uuid"] for s in report_force.get("skipped") or []}
        assert (
            rec_a.uuid in force_skipped
        ), "force=True must NOT bypass already_reverted (A must stay skipped)"
        assert report_force.get("force_acknowledged") is True

    finally:
        # Reset DT state. Order matters: undo moves first (so location
        # references are correct), then strip any tags we added.
        for record_uuid, original_location in cleanup["moves_to_revert"]:
            await _safe_move(real_adapter, record_uuid, original_location)
        for record_uuid, tag in cleanup["added_tags"]:
            await _safe_remove_tag(real_adapter, record_uuid, tag)
        # Belt-and-suspenders: also strip the foreign tag on B even if
        # bookkeeping above missed it — the unique random suffix means
        # this is always safe.
        await _safe_remove_tag(real_adapter, rec_b.uuid, tag_foreign)
        # Defensively unset env-leaked confirm_token TTL overrides.
        os.environ.pop("ISTEFOX_PREVIEW_TTL_S", None)
