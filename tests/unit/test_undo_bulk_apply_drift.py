"""Per-op drift detection in _undo_bulk_apply (3-state classifier)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from istefox_dt_mcp_schemas.common import Record, RecordKind
from istefox_dt_mcp_server.undo import undo_audit

if TYPE_CHECKING:
    from istefox_dt_mcp_server.deps import Deps


def _record(
    uuid: str = "u",
    location: str = "/Inbox",
    tags: list[str] | None = None,
) -> Record:
    return Record(
        uuid=uuid, name=f"r-{uuid}", kind=RecordKind.PDF,
        location=location, reference_url=f"x-d://{uuid}",
        creation_date=datetime.now(), modification_date=datetime.now(),
        tags=tags or [],
    )


def _audit_bulk_apply(
    deps: "Deps",
    *,
    applied_ops: list[dict],
    per_op_snapshots: dict[str, dict] | None = None,
    pre_move_snapshots: dict[str, str] | None = None,
):
    """Insert a bulk_apply audit entry as if a successful apply had run."""
    audit_id = deps.audit.append(
        tool_name="bulk_apply",
        input_data={
            "operations": [
                {"record_uuid": op["uuid"], "op": op["op"], "payload": op["payload"]}
                for op in applied_ops
            ],
            "dry_run": False,
        },
        output_data={"operations_applied": len(applied_ops)},
        duration_ms=10.0,
        before_state={"operations": list(applied_ops)},
    )
    after_state: dict = {
        "applied": applied_ops,
        "operations_applied": len(applied_ops),
        "pre_move_snapshots": pre_move_snapshots or {},
    }
    if per_op_snapshots is not None:
        after_state["per_op_snapshots"] = per_op_snapshots
    deps.audit.set_after_state(audit_id, after_state)
    return audit_id


@pytest.mark.asyncio
async def test_no_drift_per_op_reverts_add_tag(deps):
    """Single add_tag op, current state matches `after`: revert proceeds."""
    audit_id = _audit_bulk_apply(
        deps,
        applied_ops=[{"uuid": "u1", "op": "add_tag", "payload": {"tag": "x"}}],
        per_op_snapshots={
            "0": {
                "before": {"location": "/Inbox", "tags": []},
                "after":  {"location": "/Inbox", "tags": ["x"]},
            }
        },
    )
    deps.adapter.get_record = AsyncMock(
        return_value=_record(uuid="u1", location="/Inbox", tags=["x"])
    )
    deps.adapter.remove_tag = AsyncMock(return_value=None)

    result = await undo_audit(deps, audit_id, dry_run=False)

    assert result["reverted"] is True
    assert result["reverted_count"] == 1
    drift_per_op = result.get("drift_per_op", [])
    assert len(drift_per_op) == 1
    assert drift_per_op[0]["drift_state"] == "no_drift"
    deps.adapter.remove_tag.assert_awaited_once_with("u1", "x", dry_run=False)


@pytest.mark.asyncio
async def test_already_reverted_per_op_skips(deps):
    """Single add_tag op, user externally removed the tag: undo skips."""
    audit_id = _audit_bulk_apply(
        deps,
        applied_ops=[{"uuid": "u1", "op": "add_tag", "payload": {"tag": "x"}}],
        per_op_snapshots={
            "0": {
                "before": {"location": "/Inbox", "tags": []},
                "after":  {"location": "/Inbox", "tags": ["x"]},
            }
        },
    )
    # Current state matches `before`: tag was already removed externally
    deps.adapter.get_record = AsyncMock(
        return_value=_record(uuid="u1", location="/Inbox", tags=[])
    )
    deps.adapter.remove_tag = AsyncMock(return_value=None)

    result = await undo_audit(deps, audit_id, dry_run=False)

    assert result["reverted"] is False
    assert result["reverted_count"] == 0
    assert result["drift_detected"] is False
    drift_per_op = result["drift_per_op"]
    assert drift_per_op[0]["drift_state"] == "already_reverted"
    assert any(s.get("reason") == "already_reverted" for s in result["skipped"])
    deps.adapter.remove_tag.assert_not_awaited()


@pytest.mark.asyncio
async def test_hostile_drift_per_op_skips_without_force(deps):
    """Single add_tag op, external actor changed the tag set: undo blocked."""
    audit_id = _audit_bulk_apply(
        deps,
        applied_ops=[{"uuid": "u1", "op": "add_tag", "payload": {"tag": "x"}}],
        per_op_snapshots={
            "0": {
                "before": {"location": "/Inbox", "tags": []},
                "after":  {"location": "/Inbox", "tags": ["x"]},
            }
        },
    )
    # Current matches NEITHER before nor after: external actor added "y"
    deps.adapter.get_record = AsyncMock(
        return_value=_record(uuid="u1", location="/Inbox", tags=["x", "y"])
    )
    deps.adapter.remove_tag = AsyncMock(return_value=None)

    result = await undo_audit(deps, audit_id, dry_run=False, force=False)

    assert result["reverted"] is False
    assert result["reverted_count"] == 0
    assert result["drift_detected"] is True
    drift_per_op = result["drift_per_op"]
    assert drift_per_op[0]["drift_state"] == "hostile_drift"
    assert "drift_details" in drift_per_op[0]
    deps.adapter.remove_tag.assert_not_awaited()


@pytest.mark.asyncio
async def test_hostile_drift_per_op_reverts_with_force(deps):
    """Same scenario but --force: revert proceeds, overwriting external edits."""
    audit_id = _audit_bulk_apply(
        deps,
        applied_ops=[{"uuid": "u1", "op": "add_tag", "payload": {"tag": "x"}}],
        per_op_snapshots={
            "0": {
                "before": {"location": "/Inbox", "tags": []},
                "after":  {"location": "/Inbox", "tags": ["x"]},
            }
        },
    )
    deps.adapter.get_record = AsyncMock(
        return_value=_record(uuid="u1", location="/Inbox", tags=["x", "y"])
    )
    deps.adapter.remove_tag = AsyncMock(return_value=None)

    result = await undo_audit(deps, audit_id, dry_run=False, force=True)

    assert result["reverted"] is True
    assert result["reverted_count"] == 1
    assert result["drift_detected"] is True  # still surfaces the drift
    deps.adapter.remove_tag.assert_awaited_once_with("u1", "x", dry_run=False)


@pytest.mark.asyncio
async def test_mixed_batch_drift_states(deps):
    """3-op batch: idx0 no_drift, idx1 already_reverted, idx2 hostile_drift.
    Expect 1 reverted, 2 skipped, drift_detected True."""
    audit_id = _audit_bulk_apply(
        deps,
        applied_ops=[
            {"uuid": "u1", "op": "add_tag", "payload": {"tag": "a"}},  # no_drift
            {"uuid": "u2", "op": "add_tag", "payload": {"tag": "b"}},  # already_reverted
            {"uuid": "u3", "op": "add_tag", "payload": {"tag": "c"}},  # hostile_drift
        ],
        per_op_snapshots={
            "0": {"before": {"location": "/", "tags": []},
                  "after":  {"location": "/", "tags": ["a"]}},
            "1": {"before": {"location": "/", "tags": []},
                  "after":  {"location": "/", "tags": ["b"]}},
            "2": {"before": {"location": "/", "tags": []},
                  "after":  {"location": "/", "tags": ["c"]}},
        },
    )

    def fake_get_record(uuid: str):
        if uuid == "u1":
            return _record(uuid="u1", location="/", tags=["a"])  # no_drift
        if uuid == "u2":
            return _record(uuid="u2", location="/", tags=[])  # already_reverted
        if uuid == "u3":
            return _record(uuid="u3", location="/", tags=["c", "foreign"])  # hostile
        raise ValueError(f"unexpected uuid {uuid}")

    deps.adapter.get_record = AsyncMock(side_effect=fake_get_record)
    deps.adapter.remove_tag = AsyncMock(return_value=None)

    result = await undo_audit(deps, audit_id, dry_run=False, force=False)

    assert result["reverted_count"] == 1
    assert result["drift_detected"] is True
    states = {d["uuid"]: d["drift_state"] for d in result["drift_per_op"]}
    assert states == {"u1": "no_drift", "u2": "already_reverted", "u3": "hostile_drift"}
    deps.adapter.remove_tag.assert_awaited_once_with("u1", "a", dry_run=False)


@pytest.mark.asyncio
async def test_legacy_audit_no_per_op_snapshots(deps):
    """Audit entry written before this feature: no per_op_snapshots key.
    Undo must fall back to legacy behavior (no drift detection, blind revert)."""
    audit_id = _audit_bulk_apply(
        deps,
        applied_ops=[{"uuid": "u1", "op": "add_tag", "payload": {"tag": "x"}}],
        per_op_snapshots=None,  # KEY ABSENT — legacy entry
    )
    deps.adapter.remove_tag = AsyncMock(return_value=None)
    # get_record should NOT be called in the legacy branch
    deps.adapter.get_record = AsyncMock(side_effect=AssertionError("must not be called"))

    result = await undo_audit(deps, audit_id, dry_run=False)

    assert result["reverted"] is True
    assert result["reverted_count"] == 1
    # Legacy: drift_per_op is empty (no detection performed)
    assert result.get("drift_per_op") == []
    deps.adapter.remove_tag.assert_awaited_once_with("u1", "x", dry_run=False)


@pytest.mark.asyncio
async def test_per_op_missing_after_falls_back_for_that_op_only(deps):
    """idx0 has full snapshot (drift detection), idx1 missing `after`
    (post-snapshot failure during apply). idx1 reverts blindly."""
    audit_id = _audit_bulk_apply(
        deps,
        applied_ops=[
            {"uuid": "u1", "op": "add_tag", "payload": {"tag": "a"}},
            {"uuid": "u2", "op": "add_tag", "payload": {"tag": "b"}},
        ],
        per_op_snapshots={
            "0": {"before": {"location": "/", "tags": []},
                  "after":  {"location": "/", "tags": ["a"]}},
            "1": {"before": {"location": "/", "tags": []}},  # no `after`
        },
    )

    def fake_get_record(uuid: str):
        return _record(uuid=uuid, location="/", tags=["a"] if uuid == "u1" else ["b"])

    deps.adapter.get_record = AsyncMock(side_effect=fake_get_record)
    deps.adapter.remove_tag = AsyncMock(return_value=None)

    result = await undo_audit(deps, audit_id, dry_run=False)

    assert result["reverted_count"] == 2
    states = {d["uuid"]: d["drift_state"] for d in result["drift_per_op"]}
    assert states["u1"] == "no_drift"
    assert states["u2"] == "unknown"


@pytest.mark.asyncio
async def test_no_drift_per_op_reverts_move(deps):
    """move op, current location matches `after` (post-move): revert moves back."""
    audit_id = _audit_bulk_apply(
        deps,
        applied_ops=[{"uuid": "u1", "op": "move", "payload": {"destination": "/Archive"}}],
        per_op_snapshots={
            "0": {
                "before": {"location": "/Inbox",   "tags": []},
                "after":  {"location": "/Archive", "tags": []},
            }
        },
        pre_move_snapshots={"u1": "/Inbox"},  # required for inverse op
    )
    deps.adapter.get_record = AsyncMock(
        return_value=_record(uuid="u1", location="/Archive", tags=[])
    )
    deps.adapter.move_record = AsyncMock(return_value=None)

    result = await undo_audit(deps, audit_id, dry_run=False)

    assert result["reverted"] is True
    assert result["reverted_count"] == 1
    assert result["drift_per_op"][0]["drift_state"] == "no_drift"
    deps.adapter.move_record.assert_awaited_once_with("u1", "/Inbox", dry_run=False)


@pytest.mark.asyncio
async def test_no_drift_per_op_reverts_remove_tag(deps):
    """remove_tag op, current matches `after` (tag absent): revert re-adds the tag."""
    audit_id = _audit_bulk_apply(
        deps,
        applied_ops=[{"uuid": "u1", "op": "remove_tag", "payload": {"tag": "x"}}],
        per_op_snapshots={
            "0": {
                "before": {"location": "/", "tags": ["x"]},
                "after":  {"location": "/", "tags": []},
            }
        },
    )
    deps.adapter.get_record = AsyncMock(
        return_value=_record(uuid="u1", location="/", tags=[])
    )
    deps.adapter.apply_tag = AsyncMock(return_value=None)

    result = await undo_audit(deps, audit_id, dry_run=False)

    assert result["reverted"] is True
    assert result["reverted_count"] == 1
    deps.adapter.apply_tag.assert_awaited_once_with("u1", "x", dry_run=False)
