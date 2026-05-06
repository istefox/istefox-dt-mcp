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
