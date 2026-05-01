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
    out = await fn(
        FileDocumentInput(record_uuid="u", dry_run=False, confirm_token="prev-audit-id")
    )

    assert out.success is True
    assert out.data.applied is True
    mock_adapter.move_record.assert_awaited_once_with(
        "u", "/Business/Projects/X", dry_run=False
    )
    mock_adapter.apply_tag.assert_awaited_once_with("u", "X", dry_run=False)


@pytest.mark.asyncio
async def test_apply_without_confirm_token_logs_warning_but_proceeds(
    deps: Deps, mock_adapter: AsyncMock, caplog
) -> None:
    mock_adapter.get_record.return_value = _record(location="/Inbox", tags=[])
    mock_adapter.classify_record.return_value = []  # no destination
    fn = _register_file_document_and_get_callable(deps)
    out = await fn(
        FileDocumentInput(record_uuid="u", dry_run=False)  # no confirm_token
    )
    assert out.success is True
    # No move/tag because preview is empty, but no exception either
    mock_adapter.move_record.assert_not_awaited()


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
