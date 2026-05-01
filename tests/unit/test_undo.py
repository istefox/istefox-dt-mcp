"""undo_audit — read audit, reverse write op."""

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
