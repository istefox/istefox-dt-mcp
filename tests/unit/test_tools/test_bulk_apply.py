"""bulk_apply tool — preview/apply, validation, stop_on_first_error."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from istefox_dt_mcp_adapter.errors import RecordNotFoundError
from istefox_dt_mcp_schemas.tools import (
    BulkApplyInput,
    BulkApplyOperation,
    BulkApplyOutput,
)
from istefox_dt_mcp_server.tools.bulk_apply import register

if TYPE_CHECKING:
    from unittest.mock import AsyncMock

    from istefox_dt_mcp_server.deps import Deps


def _register_and_get_callable(deps: Deps):
    captured: dict[str, object] = {}

    class _StubMCP:
        def tool(self):
            def decorator(fn):
                captured["fn"] = fn
                return fn

            return decorator

    register(_StubMCP(), deps)  # type: ignore[arg-type]
    return captured["fn"]


def _op(uuid: str, op: str, **payload: str) -> BulkApplyOperation:
    return BulkApplyOperation(record_uuid=uuid, op=op, payload=payload)


async def _obtain_token(fn, ops: list[BulkApplyOperation]) -> str:
    """Run a dry_run preview and return the preview_token."""
    preview = await fn(BulkApplyInput(operations=ops, dry_run=True))
    assert preview.data.preview_token is not None
    return preview.data.preview_token


@pytest.mark.asyncio
async def test_dry_run_returns_planned_outcomes(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    fn = _register_and_get_callable(deps)
    out: BulkApplyOutput = await fn(
        BulkApplyInput(
            operations=[
                _op("u1", "add_tag", tag="alpha"),
                _op("u2", "move", destination="/Biz"),
            ],
            dry_run=True,
        )
    )
    assert out.success is True
    assert out.data is not None
    assert out.data.operations_total == 2
    assert out.data.operations_applied == 0
    assert all(o.status == "planned" for o in out.data.outcomes)
    assert out.data.preview_token is not None
    # No adapter mutations during dry_run
    mock_adapter.apply_tag.assert_not_awaited()
    mock_adapter.move_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_dry_run_flags_invalid_op_type(deps: Deps) -> None:
    fn = _register_and_get_callable(deps)
    out: BulkApplyOutput = await fn(
        BulkApplyInput(
            operations=[_op("u1", "rename", new_name="x")],
            dry_run=True,
        )
    )
    assert out.success is True
    assert out.data.outcomes[0].status == "failed"
    assert out.data.outcomes[0].error_code == "INVALID_INPUT"
    assert out.data.failed_index == 0


@pytest.mark.asyncio
async def test_dry_run_flags_missing_payload(deps: Deps) -> None:
    fn = _register_and_get_callable(deps)
    out: BulkApplyOutput = await fn(
        BulkApplyInput(
            operations=[
                _op("u1", "add_tag"),  # no tag
                _op("u2", "move"),  # no destination
            ],
            dry_run=True,
        )
    )
    assert out.data.outcomes[0].status == "failed"
    assert "tag" in out.data.outcomes[0].error_message
    assert out.data.outcomes[1].status == "failed"
    assert "destination" in out.data.outcomes[1].error_message


@pytest.mark.asyncio
async def test_apply_dispatches_to_adapter(deps: Deps, mock_adapter: AsyncMock) -> None:
    fn = _register_and_get_callable(deps)
    ops = [
        _op("u1", "add_tag", tag="alpha"),
        _op("u2", "remove_tag", tag="beta"),
        _op("u3", "move", destination="/Biz/X"),
    ]
    token = await _obtain_token(fn, ops)
    out: BulkApplyOutput = await fn(
        BulkApplyInput(operations=ops, dry_run=False, confirm_token=token)
    )
    assert out.success is True
    assert out.data.operations_applied == 3
    assert out.data.failed_index is None
    assert all(o.status == "applied" for o in out.data.outcomes)
    mock_adapter.apply_tag.assert_awaited_once_with("u1", "alpha", dry_run=False)
    mock_adapter.remove_tag.assert_awaited_once_with("u2", "beta", dry_run=False)
    mock_adapter.move_record.assert_awaited_once_with("u3", "/Biz/X", dry_run=False)


@pytest.mark.asyncio
async def test_apply_stop_on_first_error_halts(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    # Second op fails — the third op must not run
    mock_adapter.apply_tag.side_effect = [
        None,  # u1 ok
        RecordNotFoundError("u2"),  # u2 fails
    ]
    fn = _register_and_get_callable(deps)
    ops = [
        _op("u1", "add_tag", tag="alpha"),
        _op("u2", "add_tag", tag="beta"),
        _op("u3", "add_tag", tag="gamma"),  # should NOT run
    ]
    token = await _obtain_token(fn, ops)
    out: BulkApplyOutput = await fn(
        BulkApplyInput(
            operations=ops,
            dry_run=False,
            confirm_token=token,
            stop_on_first_error=True,
        )
    )
    assert out.success is True
    assert out.data.operations_applied == 1
    assert out.data.failed_index == 1
    assert len(out.data.outcomes) == 2  # halted before u3
    assert out.data.outcomes[0].status == "applied"
    assert out.data.outcomes[1].status == "failed"
    assert out.data.outcomes[1].error_code == "RECORD_NOT_FOUND"
    assert mock_adapter.apply_tag.await_count == 2


@pytest.mark.asyncio
async def test_apply_continue_on_error(deps: Deps, mock_adapter: AsyncMock) -> None:
    mock_adapter.apply_tag.side_effect = [
        None,  # u1 ok
        RecordNotFoundError("u2"),  # u2 fails
        None,  # u3 ok
    ]
    fn = _register_and_get_callable(deps)
    ops = [
        _op("u1", "add_tag", tag="alpha"),
        _op("u2", "add_tag", tag="beta"),
        _op("u3", "add_tag", tag="gamma"),
    ]
    token = await _obtain_token(fn, ops)
    out: BulkApplyOutput = await fn(
        BulkApplyInput(
            operations=ops,
            dry_run=False,
            confirm_token=token,
            stop_on_first_error=False,
        )
    )
    assert out.data.operations_applied == 2
    assert out.data.failed_index == 1  # first failure index
    assert len(out.data.outcomes) == 3
    assert [o.status for o in out.data.outcomes] == ["applied", "failed", "applied"]


@pytest.mark.asyncio
async def test_apply_invalid_op_does_not_call_adapter(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    fn = _register_and_get_callable(deps)
    ops = [_op("u1", "rename", new_name="x")]
    token = await _obtain_token(fn, ops)
    out: BulkApplyOutput = await fn(
        BulkApplyInput(operations=ops, dry_run=False, confirm_token=token)
    )
    assert out.data.operations_applied == 0
    assert out.data.failed_index == 0
    mock_adapter.apply_tag.assert_not_awaited()
    mock_adapter.move_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_audit_persists_before_state(deps: Deps, mock_adapter: AsyncMock) -> None:
    fn = _register_and_get_callable(deps)
    out: BulkApplyOutput = await fn(
        BulkApplyInput(
            operations=[_op("u1", "add_tag", tag="alpha")],
            dry_run=True,
        )
    )
    entry = deps.audit.get(out.audit_id)
    assert entry is not None
    assert entry.before_state is not None
    assert entry.before_state["operations"] == [
        {"uuid": "u1", "op": "add_tag", "payload": {"tag": "alpha"}}
    ]


@pytest.mark.asyncio
async def test_apply_without_confirm_token_is_rejected(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    """Hard enforcement (v0.0.9): missing token → INVALID_PREVIEW_TOKEN."""
    fn = _register_and_get_callable(deps)
    out: BulkApplyOutput = await fn(
        BulkApplyInput(
            operations=[_op("u1", "add_tag", tag="alpha")],
            dry_run=False,  # no confirm_token
        )
    )
    assert out.success is False
    assert out.error_code == "INVALID_PREVIEW_TOKEN"
    mock_adapter.apply_tag.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_consumed_token_rejected_on_replay(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    fn = _register_and_get_callable(deps)
    ops = [_op("u1", "add_tag", tag="alpha")]
    token = await _obtain_token(fn, ops)
    first = await fn(BulkApplyInput(operations=ops, dry_run=False, confirm_token=token))
    assert first.success is True
    assert first.data.operations_applied == 1
    second = await fn(
        BulkApplyInput(operations=ops, dry_run=False, confirm_token=token)
    )
    assert second.success is False
    assert second.error_code == "CONSUMED_PREVIEW_TOKEN"


@pytest.mark.asyncio
async def test_apply_with_other_tools_token_is_rejected(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    """A file_document preview_token cannot be used to apply bulk_apply."""
    foreign_id = deps.audit.append(
        tool_name="file_document",
        input_data={"dry_run": True, "record_uuid": "u"},
        output_data=None,
        duration_ms=1.0,
    )
    fn = _register_and_get_callable(deps)
    out = await fn(
        BulkApplyInput(
            operations=[_op("u1", "add_tag", tag="alpha")],
            dry_run=False,
            confirm_token=str(foreign_id),
        )
    )
    assert out.success is False
    assert out.error_code == "INVALID_PREVIEW_TOKEN"
    mock_adapter.apply_tag.assert_not_awaited()
