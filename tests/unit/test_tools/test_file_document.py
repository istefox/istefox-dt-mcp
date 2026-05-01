"""file_document tool — preview-then-apply flow with mocked deps."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import pytest
from istefox_dt_mcp_schemas.common import (
    ClassifySuggestion,
    MoveResult,
    Record,
    RecordKind,
    TagResult,
    WriteOutcome,
)
from istefox_dt_mcp_schemas.tools import (
    FileDocumentInput,
    FileDocumentOutput,
)
from istefox_dt_mcp_server.tools.file_document import register

if TYPE_CHECKING:
    from unittest.mock import AsyncMock

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


def _register_file_document_and_get_callable(deps: Deps):
    captured: dict[str, object] = {}

    class _StubMCP:
        def tool(self):
            def decorator(fn):
                captured["fn"] = fn
                return fn

            return decorator

    register(_StubMCP(), deps)  # type: ignore[arg-type]
    return captured["fn"]


@pytest.mark.asyncio
async def test_dry_run_returns_preview_with_classify(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    mock_adapter.get_record.return_value = _record(location="/Inbox")
    mock_adapter.classify_record.return_value = [
        ClassifySuggestion(location="/Business/Projects/X", score=0.9)
    ]

    fn = _register_file_document_and_get_callable(deps)
    out: FileDocumentOutput = await fn(FileDocumentInput(record_uuid="u", dry_run=True))

    assert out.success is True
    assert out.data is not None
    assert out.data.applied is False
    assert out.data.would_apply is True
    assert out.data.preview.destination_group == "/Business/Projects/X"
    assert "X" in out.data.preview.tags_to_add
    assert out.data.preview_token is not None  # echoed audit_id
    # Adapter should NOT have been asked to mutate
    mock_adapter.move_record.assert_not_awaited()
    mock_adapter.apply_tag.assert_not_awaited()


@pytest.mark.asyncio
async def test_dry_run_skips_no_op_move(deps: Deps, mock_adapter: AsyncMock) -> None:
    """If classify suggests current location, no destination should be set."""
    mock_adapter.get_record.return_value = _record(location="/Inbox")
    mock_adapter.classify_record.return_value = [
        ClassifySuggestion(location="/Inbox", score=0.7)  # same as current
    ]
    fn = _register_file_document_and_get_callable(deps)
    out: FileDocumentOutput = await fn(FileDocumentInput(record_uuid="u", dry_run=True))
    assert out.data.preview.destination_group is None
    assert out.data.would_apply is False


@pytest.mark.asyncio
async def test_destination_hint_overrides_classify(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    mock_adapter.get_record.return_value = _record(location="/Inbox")

    fn = _register_file_document_and_get_callable(deps)
    out = await fn(
        FileDocumentInput(
            record_uuid="u",
            dry_run=True,
            destination_hint="/Business/Manual",
        )
    )
    assert out.data.preview.destination_group == "/Business/Manual"
    # classify_record must NOT be called when a hint is provided
    mock_adapter.classify_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_calls_move_and_tag(deps: Deps, mock_adapter: AsyncMock) -> None:
    mock_adapter.get_record.return_value = _record(location="/Inbox", tags=[])
    mock_adapter.classify_record.return_value = [
        ClassifySuggestion(location="/Business/Projects/X", score=0.9)
    ]
    mock_adapter.move_record.return_value = MoveResult(
        uuid="u",
        outcome=WriteOutcome.APPLIED,
        location_before="/Inbox",
        location_after="/Business/Projects/X",
    )
    mock_adapter.apply_tag.return_value = TagResult(
        uuid="u",
        outcome=WriteOutcome.APPLIED,
        tags_before=[],
        tags_after=["X"],
    )

    fn = _register_file_document_and_get_callable(deps)

    # Step 1: dry_run to obtain a valid preview_token
    preview_out = await fn(FileDocumentInput(record_uuid="u", dry_run=True))
    token = preview_out.data.preview_token
    assert token is not None

    # Step 2: apply with the real token
    out = await fn(
        FileDocumentInput(record_uuid="u", dry_run=False, confirm_token=token)
    )

    assert out.success is True
    assert out.data.applied is True
    mock_adapter.move_record.assert_awaited_once_with(
        "u", "/Business/Projects/X", dry_run=False
    )
    mock_adapter.apply_tag.assert_awaited_once_with("u", "X", dry_run=False)


@pytest.mark.asyncio
async def test_apply_without_confirm_token_is_rejected(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    """Hard enforcement (v0.0.9): missing token → INVALID_PREVIEW_TOKEN."""
    mock_adapter.get_record.return_value = _record(location="/Inbox", tags=[])
    mock_adapter.classify_record.return_value = []
    fn = _register_file_document_and_get_callable(deps)
    out = await fn(FileDocumentInput(record_uuid="u", dry_run=False))
    assert out.success is False
    assert out.error_code == "INVALID_PREVIEW_TOKEN"
    mock_adapter.move_record.assert_not_awaited()
    mock_adapter.apply_tag.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_with_garbage_token_is_rejected(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    mock_adapter.get_record.return_value = _record(location="/Inbox", tags=[])
    mock_adapter.classify_record.return_value = []
    fn = _register_file_document_and_get_callable(deps)
    out = await fn(
        FileDocumentInput(record_uuid="u", dry_run=False, confirm_token="not-a-uuid")
    )
    assert out.success is False
    assert out.error_code == "INVALID_PREVIEW_TOKEN"
    mock_adapter.move_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_consumed_token_is_rejected_on_replay(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    """A token can be used exactly once."""
    mock_adapter.get_record.return_value = _record(location="/Inbox", tags=[])
    mock_adapter.classify_record.return_value = [
        ClassifySuggestion(location="/Business/X", score=0.8)
    ]
    fn = _register_file_document_and_get_callable(deps)
    preview = await fn(FileDocumentInput(record_uuid="u", dry_run=True))
    token = preview.data.preview_token

    first = await fn(
        FileDocumentInput(record_uuid="u", dry_run=False, confirm_token=token)
    )
    assert first.success is True
    assert first.data.applied is True

    second = await fn(
        FileDocumentInput(record_uuid="u", dry_run=False, confirm_token=token)
    )
    assert second.success is False
    assert second.error_code == "CONSUMED_PREVIEW_TOKEN"


@pytest.mark.asyncio
async def test_apply_with_other_tools_token_is_rejected(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    """A bulk_apply preview_token cannot be used to apply file_document."""
    mock_adapter.get_record.return_value = _record(location="/Inbox", tags=[])
    mock_adapter.classify_record.return_value = []
    # Inject an audit entry from a different tool, marked as a dry_run
    foreign_id = deps.audit.append(
        tool_name="bulk_apply",
        input_data={"dry_run": True, "operations": []},
        output_data=None,
        duration_ms=1.0,
    )
    fn = _register_file_document_and_get_callable(deps)
    out = await fn(
        FileDocumentInput(record_uuid="u", dry_run=False, confirm_token=str(foreign_id))
    )
    assert out.success is False
    assert out.error_code == "INVALID_PREVIEW_TOKEN"


@pytest.mark.asyncio
async def test_apply_with_expired_token_is_rejected(
    deps: Deps, mock_adapter: AsyncMock, monkeypatch
) -> None:
    """Tokens older than TTL are rejected."""
    monkeypatch.setenv("ISTEFOX_PREVIEW_TTL_S", "1")  # 1 second
    mock_adapter.get_record.return_value = _record(location="/Inbox", tags=[])
    mock_adapter.classify_record.return_value = []
    fn = _register_file_document_and_get_callable(deps)
    preview = await fn(FileDocumentInput(record_uuid="u", dry_run=True))
    token = preview.data.preview_token

    import time

    time.sleep(1.2)

    out = await fn(
        FileDocumentInput(record_uuid="u", dry_run=False, confirm_token=token)
    )
    assert out.success is False
    assert out.error_code == "EXPIRED_PREVIEW_TOKEN"


@pytest.mark.asyncio
async def test_audit_log_persists_after_state_on_apply(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    """W10/v0.0.20: after_state holds the REFETCHED record state.

    file_document refetches the record after apply (instead of
    reconstructing from input), so what's persisted matches what
    `undo` will see on subsequent get_record calls — even if DT
    normalizes the location string differently from destination_hint.
    """
    # First call (initial snapshot for before_state): record at /Inbox
    # Second call (refetch after apply): DT reports the post-move
    # location relative to the database — note "/X/" not "/Business/X"
    mock_adapter.get_record.side_effect = [
        _record(location="/Inbox", tags=["alpha"]),  # initial snapshot
        _record(location="/X/", tags=["alpha", "X"]),  # post-apply refetch
        # Plus a 3rd call for the second invocation's initial snapshot
        # (preview phase of the apply call). Use last value as fallback.
        _record(location="/X/", tags=["alpha", "X"]),
        _record(location="/X/", tags=["alpha", "X"]),
    ]
    mock_adapter.classify_record.return_value = [
        ClassifySuggestion(location="/Business/X", score=0.9)
    ]
    mock_adapter.move_record.return_value = MoveResult(
        uuid="u",
        outcome=WriteOutcome.APPLIED,
        location_before="/Inbox",
        location_after="/Business/X",
    )
    mock_adapter.apply_tag.return_value = TagResult(
        uuid="u",
        outcome=WriteOutcome.APPLIED,
        tags_before=["alpha"],
        tags_after=["alpha", "X"],
    )
    fn = _register_file_document_and_get_callable(deps)
    preview = await fn(FileDocumentInput(record_uuid="u", dry_run=True))
    apply = await fn(
        FileDocumentInput(
            record_uuid="u", dry_run=False, confirm_token=preview.data.preview_token
        )
    )
    entry = deps.audit.get(apply.audit_id)
    assert entry is not None
    assert entry.after_state is not None
    # Now stores DT's actual location string (from refetch), not the
    # destination_hint or preview value
    assert entry.after_state["location"] == "/X/"
    assert entry.after_state["tags"] == ["X", "alpha"]


@pytest.mark.asyncio
async def test_audit_log_persists_before_state(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    mock_adapter.get_record.return_value = _record(location="/Inbox", tags=["alpha"])
    mock_adapter.classify_record.return_value = [
        ClassifySuggestion(location="/Business/X", score=0.8)
    ]
    fn = _register_file_document_and_get_callable(deps)
    out = await fn(FileDocumentInput(record_uuid="u", dry_run=True))

    entry = deps.audit.get(out.audit_id)
    assert entry is not None
    assert entry.before_state is not None
    assert entry.before_state["uuid"] == "u"
    assert entry.before_state["location"] == "/Inbox"
    assert entry.before_state["tags"] == ["alpha"]
