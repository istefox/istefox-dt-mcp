"""search tool — bm25 / semantic / hybrid mode behavior with mocked deps."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from istefox_dt_mcp_adapter.rag import NoopRAGProvider, RAGProvider
from istefox_dt_mcp_schemas.common import Record, RecordKind, SearchResult
from istefox_dt_mcp_schemas.rag import RAGHit
from istefox_dt_mcp_schemas.tools import SearchInput, SearchOutput
from istefox_dt_mcp_server.deps import Deps


def _record(uuid: str) -> Record:
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


def _hit(uuid: str, score: float = 0.9) -> RAGHit:
    return RAGHit(uuid=uuid, score=score, snippet=f"snippet-{uuid}", metadata={})


def _sr(uuid: str) -> SearchResult:
    return SearchResult(
        uuid=uuid,
        name=f"name-{uuid}",
        location=f"/{uuid}",
        reference_url=f"x-d://{uuid}",
    )


@pytest.fixture
def mock_rag() -> AsyncMock:
    return AsyncMock(spec=RAGProvider)


@pytest.fixture
def deps_with_mock_rag(deps: Deps, mock_rag: AsyncMock) -> Deps:
    deps.rag = mock_rag
    return deps


def _register_search_and_get_callable(deps: Deps):
    """Register the search tool against a stub MCP and return the inner async fn."""
    captured: dict[str, object] = {}

    class _StubMCP:
        def tool(self):
            def decorator(fn):
                captured["fn"] = fn
                return fn

            return decorator

    from istefox_dt_mcp_server.tools.search import register

    register(_StubMCP(), deps)  # type: ignore[arg-type]
    return captured["fn"]


@pytest.mark.asyncio
async def test_bm25_mode_calls_only_adapter(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    mock_adapter.search.return_value = [_sr("A"), _sr("B")]
    fn = _register_search_and_get_callable(deps)
    out: SearchOutput = await fn(SearchInput(query="ciao", mode="bm25"))
    assert out.success is True
    assert {r.uuid for r in out.data} == {"A", "B"}
    mock_adapter.search.assert_awaited()


@pytest.mark.asyncio
async def test_semantic_mode_falls_back_to_bm25_when_rag_noop(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    # default deps fixture wires NoopRAGProvider
    assert isinstance(deps.rag, NoopRAGProvider)
    mock_adapter.search.return_value = [_sr("A")]
    fn = _register_search_and_get_callable(deps)
    out: SearchOutput = await fn(SearchInput(query="x", mode="semantic"))
    assert out.success is True
    assert out.data[0].uuid == "A"
    mock_adapter.search.assert_awaited()


@pytest.mark.asyncio
async def test_semantic_mode_uses_rag_when_available(
    deps_with_mock_rag: Deps, mock_adapter: AsyncMock, mock_rag: AsyncMock
) -> None:
    mock_rag.query.return_value = [_hit("X"), _hit("Y")]
    mock_adapter.get_record.side_effect = [_record("X"), _record("Y")]

    fn = _register_search_and_get_callable(deps_with_mock_rag)
    out: SearchOutput = await fn(SearchInput(query="q", mode="semantic"))

    assert out.success is True
    assert {r.uuid for r in out.data} == {"X", "Y"}
    # Each hit got hydrated via get_record
    assert mock_adapter.get_record.await_count == 2


@pytest.mark.asyncio
async def test_hybrid_mode_fuses_bm25_and_rag(
    deps_with_mock_rag: Deps, mock_adapter: AsyncMock, mock_rag: AsyncMock
) -> None:
    mock_adapter.search.return_value = [_sr("A"), _sr("B")]
    mock_rag.query.return_value = [_hit("B"), _hit("C")]
    # B already in bm25; C needs hydration
    mock_adapter.get_record.return_value = _record("C")

    fn = _register_search_and_get_callable(deps_with_mock_rag)
    out: SearchOutput = await fn(SearchInput(query="q", mode="hybrid", max_results=3))

    uuids = [r.uuid for r in out.data]
    # B should be first because it's in both lists
    assert uuids[0] == "B"
    assert set(uuids) == {"A", "B", "C"}
    # All RRF-fused results have a score
    assert all(r.score is not None and r.score > 0 for r in out.data)


@pytest.mark.asyncio
async def test_hybrid_mode_snippet_from_rag(
    deps_with_mock_rag: Deps, mock_adapter: AsyncMock, mock_rag: AsyncMock
) -> None:
    mock_adapter.search.return_value = [_sr("A")]
    mock_rag.query.return_value = [_hit("A")]
    fn = _register_search_and_get_callable(deps_with_mock_rag)
    out: SearchOutput = await fn(SearchInput(query="q", mode="hybrid", max_results=1))
    assert out.data[0].snippet == "snippet-A"
