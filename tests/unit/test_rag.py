"""RAG provider abstraction + NoopRAGProvider behavior."""

from __future__ import annotations

import pytest
from istefox_dt_mcp_adapter.rag import NoopRAGProvider, RAGProvider
from istefox_dt_mcp_schemas.rag import RAGFilter, RAGStats


@pytest.mark.asyncio
async def test_noop_query_returns_empty() -> None:
    rag: RAGProvider = NoopRAGProvider()
    out = await rag.query("ciao", k=5)
    assert out == []


@pytest.mark.asyncio
async def test_noop_query_accepts_filters() -> None:
    rag: RAGProvider = NoopRAGProvider()
    out = await rag.query("ciao", k=5, filters=RAGFilter(databases=["X"], tags=["a"]))
    assert out == []


@pytest.mark.asyncio
async def test_noop_index_remove_are_idempotent() -> None:
    rag: RAGProvider = NoopRAGProvider()
    # Should not raise on either op
    await rag.index("abc", "text", {"k": "v"})
    await rag.remove("abc")
    await rag.remove("missing")


@pytest.mark.asyncio
async def test_noop_stats_returns_zero() -> None:
    rag: RAGProvider = NoopRAGProvider()
    stats = await rag.stats()
    assert isinstance(stats, RAGStats)
    assert stats.indexed_count == 0
    assert stats.embedding_model is None


@pytest.mark.asyncio
async def test_noop_close_is_safe() -> None:
    rag: RAGProvider = NoopRAGProvider()
    await rag.close()  # must not raise


def test_rag_filter_validation() -> None:
    f = RAGFilter(databases=["A", "B"], kinds=["PDF"])
    assert f.databases == ["A", "B"]
    assert f.tags is None
