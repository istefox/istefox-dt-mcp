"""sync_handler.process_sync_event — RAG side-effects from webhook events."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from istefox_dt_mcp_adapter.rag import RAGProvider
from istefox_dt_mcp_schemas.common import Record, RecordKind
from istefox_dt_mcp_server.sync_handler import process_sync_event

if TYPE_CHECKING:
    from istefox_dt_mcp_server.deps import Deps


@pytest.fixture
def mock_rag() -> AsyncMock:
    return AsyncMock(spec=RAGProvider)


@pytest.fixture
def deps_with_mock_rag(deps: Deps, mock_rag: AsyncMock) -> Deps:
    deps.rag = mock_rag
    return deps


def _record(uuid: str = "u") -> Record:
    from datetime import datetime

    return Record(
        uuid=uuid,
        name=f"name-{uuid}",
        kind=RecordKind.PDF,
        location=f"/{uuid}",
        reference_url=f"x-d://{uuid}",
        creation_date=datetime.now(),
        modification_date=datetime.now(),
    )


@pytest.mark.asyncio
async def test_deleted_event_calls_remove(
    deps_with_mock_rag: Deps, mock_rag: AsyncMock
) -> None:
    await process_sync_event(
        deps_with_mock_rag,
        {"action": "deleted", "uuid": "abc", "database": "Business"},
    )
    mock_rag.remove.assert_awaited_once_with("abc")
    mock_rag.index.assert_not_awaited()


@pytest.mark.asyncio
async def test_modified_event_indexes(
    deps_with_mock_rag: Deps, mock_adapter: AsyncMock, mock_rag: AsyncMock
) -> None:
    mock_adapter.get_record_text.return_value = "some text"
    mock_adapter.get_record.return_value = _record()
    await process_sync_event(
        deps_with_mock_rag,
        {"action": "modified", "uuid": "u", "database": "Business"},
    )
    mock_rag.index.assert_awaited_once()
    args, _ = mock_rag.index.call_args
    assert args[0] == "u"
    assert args[1] == "some text"


@pytest.mark.asyncio
async def test_created_event_skipped_when_text_empty(
    deps_with_mock_rag: Deps, mock_adapter: AsyncMock, mock_rag: AsyncMock
) -> None:
    mock_adapter.get_record_text.return_value = "   "  # only whitespace
    await process_sync_event(
        deps_with_mock_rag,
        {"action": "created", "uuid": "u", "database": "Business"},
    )
    mock_rag.index.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_action_noop(
    deps_with_mock_rag: Deps, mock_rag: AsyncMock
) -> None:
    await process_sync_event(
        deps_with_mock_rag,
        {"action": "spurious", "uuid": "u"},
    )
    mock_rag.index.assert_not_awaited()
    mock_rag.remove.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_uuid_noop(deps_with_mock_rag: Deps, mock_rag: AsyncMock) -> None:
    await process_sync_event(deps_with_mock_rag, {"action": "modified"})
    mock_rag.index.assert_not_awaited()
    mock_rag.remove.assert_not_awaited()


@pytest.mark.asyncio
async def test_modified_event_falls_back_when_meta_fetch_fails(
    deps_with_mock_rag: Deps, mock_adapter: AsyncMock, mock_rag: AsyncMock
) -> None:
    mock_adapter.get_record_text.return_value = "text"
    mock_adapter.get_record.side_effect = RuntimeError("boom")
    await process_sync_event(
        deps_with_mock_rag,
        {"action": "modified", "uuid": "abc", "database": "X"},
    )
    mock_rag.index.assert_awaited_once()
    args, _ = mock_rag.index.call_args
    assert args[0] == "abc"
    assert args[2] == {"database": "X"}  # meta fallback
