"""undo_audit — read audit, reverse write op."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from istefox_dt_mcp_schemas.common import Record, RecordKind
from istefox_dt_mcp_server.undo import compute_drift_state, undo_audit

if TYPE_CHECKING:
    from istefox_dt_mcp_server.deps import Deps


def _record(
    uuid: str = "u", location: str = "/Inbox", tags: list[str] | None = None
) -> Record:
    return Record(
        uuid=uuid,
        name=f"name-{uuid}",
        kind=RecordKind.PDF,
        location=location,
        reference_url=f"x-d://{uuid}",
        creation_date=datetime.now(),
        modification_date=datetime.now(),
        tags=tags or [],
    )


def _audit_file_document(
    deps: Deps,
    *,
    uuid: str = "u",
    before_location: str = "/Inbox",
    before_tags: list[str] | None = None,
    destination_hint: str | None = None,
    after_location: str | None = None,
    after_tags: list[str] | None = None,
):
    """Insert an audit entry as if a file_document apply had run.

    If `after_location`/`after_tags` are passed, also sets after_state
    so undo can use the precise drift check.
    """
    audit_id = deps.audit.append(
        tool_name="file_document",
        input_data={
            "record_uuid": uuid,
            "dry_run": False,
            "destination_hint": destination_hint,
        },
        output_data={"applied": True},
        duration_ms=10.0,
        before_state={
            "uuid": uuid,
            "location": before_location,
            "tags": before_tags or [],
            "name": "name",
        },
    )
    if after_location is not None or after_tags is not None:
        deps.audit.set_after_state(
            audit_id,
            {
                "uuid": uuid,
                "location": after_location or before_location,
                "tags": after_tags if after_tags is not None else (before_tags or []),
                "name": "name",
            },
        )
    return audit_id


@pytest.mark.asyncio
async def test_undo_unknown_audit_id_reports_missing(deps: Deps) -> None:
    from uuid import uuid4

    result = await undo_audit(deps, str(uuid4()))
    assert result["reverted"] is False
    assert "not found" in str(result["message"])


@pytest.mark.asyncio
async def test_undo_unsupported_tool(deps: Deps) -> None:
    audit_id = deps.audit.append(
        tool_name="search",
        input_data={"q": "x"},
        output_data=[],
        duration_ms=1.0,
    )
    result = await undo_audit(deps, audit_id)
    assert result["reverted"] is False
    assert "not supported" in str(result["message"])


@pytest.mark.asyncio
async def test_undo_no_before_state_skips(deps: Deps) -> None:
    audit_id = deps.audit.append(
        tool_name="file_document",
        input_data={"record_uuid": "u", "dry_run": True},
        output_data={"would_apply": True},
        duration_ms=1.0,
    )
    result = await undo_audit(deps, audit_id)
    assert result["reverted"] is False
    assert "no before_state" in str(result["message"])


@pytest.mark.asyncio
async def test_undo_dry_run_returns_would_revert(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    audit_id = _audit_file_document(
        deps, before_location="/Inbox", before_tags=[], destination_hint="/Biz"
    )
    # current state matches the destination_hint -> not drift
    mock_adapter.get_record.return_value = _record(location="/Biz", tags=["Biz"])

    result = await undo_audit(deps, audit_id, dry_run=True)
    assert result["reverted"] is False
    assert result["drift_detected"] is False
    would = result["would_revert"]
    assert would["move_to"] == "/Inbox"
    assert would["tags_to_remove"] == ["Biz"]
    mock_adapter.move_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_undo_apply_reverts_move_and_tags(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    audit_id = _audit_file_document(
        deps, before_location="/Inbox", before_tags=[], destination_hint="/Biz"
    )
    mock_adapter.get_record.return_value = _record(location="/Biz", tags=["Biz"])

    result = await undo_audit(deps, audit_id, dry_run=False)
    assert result["reverted"] is True
    assert result["drift_detected"] is False
    mock_adapter.move_record.assert_awaited_once_with("u", "/Inbox", dry_run=False)
    mock_adapter.remove_tag.assert_awaited_once_with("u", "Biz", dry_run=False)


@pytest.mark.asyncio
async def test_undo_drift_blocks_unless_force(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    audit_id = _audit_file_document(
        deps, before_location="/Inbox", before_tags=[], destination_hint=None
    )
    # Without an explicit hint, _is_first_undo can't confirm — so the
    # current /SomewhereElse path is treated as drift.
    mock_adapter.get_record.return_value = _record(location="/SomewhereElse", tags=[])

    blocked = await undo_audit(deps, audit_id, dry_run=False, force=False)
    assert blocked["reverted"] is False
    assert blocked["drift_detected"] is True
    mock_adapter.move_record.assert_not_awaited()

    forced = await undo_audit(deps, audit_id, dry_run=False, force=True)
    assert forced["reverted"] is True
    assert forced["drift_detected"] is True
    mock_adapter.move_record.assert_awaited_once()


@pytest.mark.asyncio
async def test_undo_uses_after_state_for_precise_drift_check(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    """W10: with after_state set, undo can confirm no-drift even when
    the original input had no destination_hint (the heuristic that
    legacy undo had to fall back on)."""
    audit_id = _audit_file_document(
        deps,
        before_location="/Inbox",
        before_tags=[],
        destination_hint=None,  # no hint → legacy path would say "drift"
        after_location="/Biz",
        after_tags=["Biz"],
    )
    # Current state matches after_state → no drift (precise check)
    mock_adapter.get_record.return_value = _record(location="/Biz", tags=["Biz"])

    result = await undo_audit(deps, audit_id, dry_run=False)
    assert result["reverted"] is True
    assert result["drift_detected"] is False
    mock_adapter.move_record.assert_awaited_once_with("u", "/Inbox", dry_run=False)
    mock_adapter.remove_tag.assert_awaited_once_with("u", "Biz", dry_run=False)


def _audit_bulk_apply(
    deps: Deps,
    *,
    applied_ops: list[dict],
    pre_move_snapshots: dict[str, str] | None = None,
):
    """Insert an audit entry as if a bulk_apply call had run, including
    after_state with the applied ops + pre_move snapshots."""
    audit_id = deps.audit.append(
        tool_name="bulk_apply",
        input_data={"dry_run": False, "operations": []},
        output_data={"applied": True},
        duration_ms=10.0,
        before_state={"operations": []},
    )
    deps.audit.set_after_state(
        audit_id,
        {
            "applied": applied_ops,
            "operations_applied": len(applied_ops),
            "pre_move_snapshots": pre_move_snapshots or {},
        },
    )
    return audit_id


@pytest.mark.asyncio
async def test_undo_bulk_apply_dry_run_returns_inverse_plan(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    """bulk_apply undo dry_run shows the inverse ops without mutating."""
    audit_id = _audit_bulk_apply(
        deps,
        applied_ops=[
            {"uuid": "u1", "op": "add_tag", "payload": {"tag": "alpha"}},
            {"uuid": "u2", "op": "remove_tag", "payload": {"tag": "beta"}},
            {"uuid": "u3", "op": "move", "payload": {"destination": "/Biz/X"}},
        ],
        pre_move_snapshots={"u3": "/Inbox"},
    )

    result = await undo_audit(deps, audit_id, dry_run=True)
    assert result["reverted"] is False
    assert result["dry_run"] is True
    assert result["n_ops_to_revert"] == 3

    plan = result["would_revert"]
    # LIFO order: move first (was last), then remove_tag, then add_tag
    assert plan[0] == {"uuid": "u3", "op": "move", "destination": "/Inbox"}
    assert plan[1] == {"uuid": "u2", "op": "add_tag", "tag": "beta"}
    assert plan[2] == {"uuid": "u1", "op": "remove_tag", "tag": "alpha"}
    mock_adapter.apply_tag.assert_not_awaited()
    mock_adapter.move_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_undo_bulk_apply_applies_inverse_ops(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    """bulk_apply undo apply executes the inverse ops in LIFO order."""
    audit_id = _audit_bulk_apply(
        deps,
        applied_ops=[
            {"uuid": "u1", "op": "add_tag", "payload": {"tag": "alpha"}},
            {"uuid": "u2", "op": "move", "payload": {"destination": "/Biz"}},
        ],
        pre_move_snapshots={"u2": "/Inbox"},
    )
    result = await undo_audit(deps, audit_id, dry_run=False)
    assert result["reverted"] is True
    assert result["reverted_count"] == 2
    assert result["failures"] == []
    # Move was last applied, so it's reverted first
    mock_adapter.move_record.assert_awaited_once_with("u2", "/Inbox", dry_run=False)
    # Then the add_tag is undone via remove_tag
    mock_adapter.remove_tag.assert_awaited_once_with("u1", "alpha", dry_run=False)


@pytest.mark.asyncio
async def test_undo_bulk_apply_skips_move_without_snapshot(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    """If a move op has no pre_move snapshot, it must be skipped
    (not reverted to an unknown location)."""
    audit_id = _audit_bulk_apply(
        deps,
        applied_ops=[
            {"uuid": "u1", "op": "move", "payload": {"destination": "/Biz"}},
        ],
        pre_move_snapshots={},  # no snapshot for u1
    )
    result = await undo_audit(deps, audit_id, dry_run=True)
    assert result["n_ops_to_revert"] == 0
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["uuid"] == "u1"
    assert "snapshot" in result["skipped"][0]["reason"]


@pytest.mark.asyncio
async def test_undo_bulk_apply_no_applied_ops_reports_nothing(
    deps: Deps,
) -> None:
    """If after_state has empty applied list, undo reports gracefully."""
    audit_id = _audit_bulk_apply(deps, applied_ops=[])
    result = await undo_audit(deps, audit_id, dry_run=False)
    assert result["reverted"] is False
    assert "nothing to undo" in str(result["message"])


@pytest.mark.asyncio
async def test_undo_after_state_diff_is_drift(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    """W10: when after_state and current diverge, drift is detected
    even if the legacy heuristic would have missed it."""
    audit_id = _audit_file_document(
        deps,
        before_location="/Inbox",
        before_tags=[],
        destination_hint="/Biz",  # heuristic would accept /Biz as no-drift
        after_location="/Biz",
        after_tags=["Biz"],
    )
    # User added an extra tag externally — diverges from after_state
    mock_adapter.get_record.return_value = _record(
        location="/Biz", tags=["Biz", "manuale"]
    )

    blocked = await undo_audit(deps, audit_id, dry_run=False, force=False)
    assert blocked["reverted"] is False
    assert blocked["drift_detected"] is True


# ---------- compute_drift_state (3-state classifier) ----------


def test_compute_drift_state_no_drift_exact_match() -> None:
    current = _record(location="/Archive", tags=["invoices"])
    before = {"location": "/Inbox", "tags": []}
    after = {"location": "/Archive", "tags": ["invoices"]}

    assert compute_drift_state(current, before, after) == "no_drift"


def test_compute_drift_state_no_drift_tag_order_irrelevant() -> None:
    current = _record(location="/Archive", tags=["b", "a"])
    before = {"location": "/Inbox", "tags": []}
    after = {"location": "/Archive", "tags": ["a", "b"]}

    assert compute_drift_state(current, before, after) == "no_drift"


def test_compute_drift_state_already_reverted_strict_match() -> None:
    current = _record(location="/Inbox", tags=[])
    before = {"location": "/Inbox", "tags": []}
    after = {"location": "/Archive", "tags": ["invoices"]}

    assert compute_drift_state(current, before, after) == "already_reverted"


def test_compute_drift_state_partial_revert_is_hostile() -> None:
    """Strict match: location matches before, but tag from apply is still
    present. Per spec Q1 = A, this is hostile_drift, not already_reverted."""
    current = _record(location="/Inbox", tags=["invoices"])
    before = {"location": "/Inbox", "tags": []}
    after = {"location": "/Archive", "tags": ["invoices"]}

    assert compute_drift_state(current, before, after) == "hostile_drift"


def test_compute_drift_state_unrelated_location_is_hostile() -> None:
    current = _record(location="/OPS", tags=["misfiled"])
    before = {"location": "/Inbox", "tags": []}
    after = {"location": "/Archive", "tags": ["invoices"]}

    assert compute_drift_state(current, before, after) == "hostile_drift"


def test_compute_drift_state_legacy_no_after_state_no_drift() -> None:
    """Pre-W10 audit entry (after_state=None). Without after_state we can
    only return no_drift if current still matches before, otherwise hostile.
    Per spec section 4 legacy fallback: only 2 states reachable."""
    current = _record(location="/Inbox", tags=[])
    before = {"location": "/Inbox", "tags": []}

    assert compute_drift_state(current, before, None) == "no_drift"


def test_compute_drift_state_legacy_no_after_state_hostile_when_diverged() -> None:
    current = _record(location="/OPS", tags=[])
    before = {"location": "/Inbox", "tags": []}

    assert compute_drift_state(current, before, None) == "hostile_drift"


# ---------- undo_audit dispatching on drift_state ----------


@pytest.mark.asyncio
async def test_undo_already_reverted_no_force_returns_noop(deps: Deps) -> None:
    """current matches before_state → already_reverted, no JXA mutation."""
    audit_id = _audit_file_document(
        deps,
        before_location="/Inbox",
        before_tags=[],
        after_location="/Archive",
        after_tags=["invoices"],
    )
    deps.adapter.get_record = AsyncMock(
        return_value=_record(location="/Inbox", tags=[])
    )
    deps.adapter.move_record = AsyncMock()
    deps.adapter.remove_tag = AsyncMock()

    result = await undo_audit(deps, audit_id, dry_run=False, force=False)

    assert result["reverted"] is False
    assert result["drift_state"] == "already_reverted"
    assert result["drift_detected"] is False
    assert "already" in str(result["message"]).lower()
    deps.adapter.move_record.assert_not_called()
    deps.adapter.remove_tag.assert_not_called()


@pytest.mark.asyncio
async def test_undo_already_reverted_with_force_ignores_force(deps: Deps) -> None:
    """--force in already_reverted: response flags force_ignored, no JXA call."""
    audit_id = _audit_file_document(
        deps,
        before_location="/Inbox",
        before_tags=[],
        after_location="/Archive",
        after_tags=["invoices"],
    )
    deps.adapter.get_record = AsyncMock(
        return_value=_record(location="/Inbox", tags=[])
    )
    deps.adapter.move_record = AsyncMock()
    deps.adapter.remove_tag = AsyncMock()

    result = await undo_audit(deps, audit_id, dry_run=False, force=True)

    assert result["reverted"] is False
    assert result["drift_state"] == "already_reverted"
    assert result.get("force_ignored") is True
    deps.adapter.move_record.assert_not_called()
    deps.adapter.remove_tag.assert_not_called()


@pytest.mark.asyncio
async def test_undo_no_drift_includes_drift_state_field(deps: Deps) -> None:
    """Existing no-drift path: drift_state="no_drift", drift_detected=False."""
    audit_id = _audit_file_document(
        deps,
        before_location="/Inbox",
        before_tags=[],
        after_location="/Archive",
        after_tags=["invoices"],
    )
    deps.adapter.get_record = AsyncMock(
        return_value=_record(location="/Archive", tags=["invoices"])
    )
    deps.adapter.move_record = AsyncMock()
    deps.adapter.remove_tag = AsyncMock()

    result = await undo_audit(deps, audit_id, dry_run=False, force=False)

    assert result["reverted"] is True
    assert result["drift_state"] == "no_drift"
    assert result["drift_detected"] is False


@pytest.mark.asyncio
async def test_undo_hostile_drift_no_force_blocks(deps: Deps) -> None:
    """Existing hostile-drift path: drift_state="hostile_drift", blocked."""
    audit_id = _audit_file_document(
        deps,
        before_location="/Inbox",
        before_tags=[],
        after_location="/Archive",
        after_tags=["invoices"],
    )
    deps.adapter.get_record = AsyncMock(
        return_value=_record(location="/OPS", tags=["misfiled"])
    )

    result = await undo_audit(deps, audit_id, dry_run=False, force=False)

    assert result["reverted"] is False
    assert result["drift_state"] == "hostile_drift"
    assert result["drift_detected"] is True
    assert "drift_details" in result


@pytest.mark.asyncio
async def test_undo_hostile_drift_with_force_proceeds(deps: Deps) -> None:
    """--force in hostile_drift overrides as today."""
    audit_id = _audit_file_document(
        deps,
        before_location="/Inbox",
        before_tags=[],
        after_location="/Archive",
        after_tags=["invoices"],
    )
    deps.adapter.get_record = AsyncMock(
        return_value=_record(location="/OPS", tags=["misfiled"])
    )
    deps.adapter.move_record = AsyncMock()
    deps.adapter.remove_tag = AsyncMock()

    result = await undo_audit(deps, audit_id, dry_run=False, force=True)

    assert result["reverted"] is True
    assert result["drift_state"] == "hostile_drift"
    deps.adapter.move_record.assert_called()
