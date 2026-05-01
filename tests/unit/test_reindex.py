"""reindex_database — adapter + rag wired with mocks."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from istefox_dt_mcp_server.reindex import reindex_database

if TYPE_CHECKING:
    from istefox_dt_mcp_server.deps import Deps


@pytest.fixture
def deps_chroma_like(deps: Deps, mock_adapter: AsyncMock) -> Deps:
    """Replace Noop with a fake that quacks like ChromaRAGProvider."""

    class FakeChroma:
        def __init__(self) -> None:
            self.indexed: list[tuple[str, str, dict]] = []

        async def index_many(self, items):
            self.indexed.extend(items)
            return len(items)

        async def index(self, uuid, text, meta=None):
            self.indexed.append((uuid, text, meta or {}))

    deps.rag = FakeChroma()  # type: ignore[assignment]
    return deps


@pytest.mark.asyncio
async def test_reindex_skips_when_noop_provider(deps: Deps) -> None:
    # Default fixture has NoopRAGProvider
    with pytest.raises(RuntimeError, match="ISTEFOX_RAG_ENABLED"):
        await reindex_database(deps, "Business")


@pytest.mark.asyncio
async def test_reindex_indexes_records_and_skips_empty(
    deps_chroma_like: Deps, mock_adapter: AsyncMock
) -> None:
    # 3 records: 1 with text, 1 empty, 1 with text
    mock_adapter.enumerate_records.side_effect = [
        (
            [
                {"uuid": "A", "name": "doc A", "kind": "pdf", "location": "/a"},
                {"uuid": "B", "name": "doc B", "kind": "image", "location": "/b"},
                {"uuid": "C", "name": "doc C", "kind": "rtf", "location": "/c"},
            ],
            3,
        ),
        ([], 3),  # second page empty -> stop
    ]
    mock_adapter.get_record_text.side_effect = ["text A", "", "text C"]

    counters = await reindex_database(deps_chroma_like, "Business")

    assert counters["seen"] == 3
    assert counters["indexed"] == 2
    assert counters["empty_text"] == 1
    assert counters["errors"] == 0
    assert {item[0] for item in deps_chroma_like.rag.indexed} == {"A", "C"}  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_reindex_respects_limit(
    deps_chroma_like: Deps, mock_adapter: AsyncMock
) -> None:
    mock_adapter.enumerate_records.side_effect = [
        (
            [
                {"uuid": str(i), "name": f"d{i}", "kind": "pdf", "location": "/"}
                for i in range(10)
            ],
            10,
        ),
        ([], 10),
    ]
    mock_adapter.get_record_text.return_value = "text"

    counters = await reindex_database(deps_chroma_like, "Business", limit=5)
    assert counters["seen"] == 5
    assert counters["indexed"] == 5


@pytest.mark.asyncio
async def test_reindex_counts_fetch_errors(
    deps_chroma_like: Deps, mock_adapter: AsyncMock
) -> None:
    mock_adapter.enumerate_records.side_effect = [
        (
            [
                {"uuid": "A", "name": "ok", "kind": "pdf", "location": "/"},
                {"uuid": "B", "name": "boom", "kind": "pdf", "location": "/"},
            ],
            2,
        ),
        ([], 2),
    ]

    async def text(uuid: str, *, max_chars: int = 2000) -> str:
        if uuid == "B":
            raise RuntimeError("simulated DT failure")
        return "text"

    mock_adapter.get_record_text.side_effect = text

    counters = await reindex_database(deps_chroma_like, "Business")
    assert counters["seen"] == 2
    assert counters["indexed"] == 1
    assert counters["errors"] == 1
