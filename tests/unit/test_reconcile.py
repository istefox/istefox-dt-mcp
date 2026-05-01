"""reconcile_database — set-diff DT vs RAG."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from istefox_dt_mcp_server.reindex import reconcile_database


class _FakeChroma:
    def __init__(self, indexed: set[str]) -> None:
        self._uuids = set(indexed)
        self.removed: list[str] = []
        self.indexed_now: list[tuple[str, str, dict]] = []
        self.reconciled = False

    async def list_uuids(self) -> set[str]:
        return self._uuids

    async def remove(self, uuid: str) -> None:
        self.removed.append(uuid)
        self._uuids.discard(uuid)

    async def index_many(self, items) -> int:
        self.indexed_now.extend(items)
        for it in items:
            self._uuids.add(it[0])
        return len(items)

    async def index(self, uuid, text, meta=None) -> None:
        self.indexed_now.append((uuid, text, meta or {}))
        self._uuids.add(uuid)

    def mark_reconciled(self) -> None:
        self.reconciled = True


@pytest.fixture
def mock_dt(mock_adapter: AsyncMock) -> AsyncMock:
    """Have enumerate_records return DT records once then exhaust."""
    return mock_adapter


@pytest.mark.asyncio
async def test_reconcile_indexes_new_and_removes_orphans(
    deps, mock_dt: AsyncMock
) -> None:
    # DT has A, B; RAG has B, C  →  index A, remove C, leave B
    deps.rag = _FakeChroma(indexed={"B", "C"})
    mock_dt.enumerate_records.side_effect = [
        (
            [
                {"uuid": "A", "name": "a", "kind": "pdf", "location": "/"},
                {"uuid": "B", "name": "b", "kind": "pdf", "location": "/"},
            ],
            2,
        ),
        ([], 2),
    ]
    mock_dt.get_record_text.return_value = "text"

    counters = await reconcile_database(deps, "Business")

    assert counters["dt_count"] == 2
    assert counters["rag_count"] == 2
    assert counters["indexed"] == 1  # A
    assert counters["removed"] == 1  # C
    assert deps.rag.removed == ["C"]
    assert {item[0] for item in deps.rag.indexed_now} == {"A"}
    assert deps.rag.reconciled is True


@pytest.mark.asyncio
async def test_reconcile_noop_when_already_in_sync(deps, mock_dt: AsyncMock) -> None:
    deps.rag = _FakeChroma(indexed={"A", "B"})
    mock_dt.enumerate_records.side_effect = [
        (
            [
                {"uuid": "A", "name": "a", "kind": "pdf", "location": "/"},
                {"uuid": "B", "name": "b", "kind": "pdf", "location": "/"},
            ],
            2,
        ),
        ([], 2),
    ]

    counters = await reconcile_database(deps, "Business")

    assert counters["indexed"] == 0
    assert counters["removed"] == 0


@pytest.mark.asyncio
async def test_reconcile_skips_empty_text_records(deps, mock_dt: AsyncMock) -> None:
    deps.rag = _FakeChroma(indexed=set())
    mock_dt.enumerate_records.side_effect = [
        (
            [
                {"uuid": "A", "name": "a", "kind": "image", "location": "/"},
            ],
            1,
        ),
        ([], 1),
    ]
    mock_dt.get_record_text.return_value = ""  # empty text -> skip

    counters = await reconcile_database(deps, "Business")
    assert counters["empty_text"] == 1
    assert counters["indexed"] == 0


@pytest.mark.asyncio
async def test_reconcile_aborts_on_noop_provider(deps) -> None:
    # default deps has NoopRAGProvider
    with pytest.raises(RuntimeError, match="ISTEFOX_RAG_ENABLED"):
        await reconcile_database(deps, "Business")
