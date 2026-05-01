"""RAG provider abstraction.

`RAGProvider` is the unified interface for semantic search and
indexing. The default `NoopRAGProvider` is registered when the
sidecar is unavailable, letting `search` and `ask_database` degrade
gracefully to BM25-only.

Concrete implementations:
- v1.0: `NoopRAGProvider` (always returns empty results)
- v1.1 (W5-6): `ChromaRAGProvider` (same-process ChromaDB embedded)
- v2 (TBD): `QdrantRAGProvider` (separate process, multi-collection)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from istefox_dt_mcp_schemas.rag import RAGFilter, RAGHit, RAGStats


class RAGProvider(ABC):
    """Vector retrieval contract. All methods async."""

    @abstractmethod
    async def query(
        self,
        text: str,
        *,
        k: int = 10,
        filters: RAGFilter | None = None,
    ) -> list[RAGHit]:
        """Semantic search. Empty list = no hits or provider not ready."""

    @abstractmethod
    async def index(
        self,
        uuid: str,
        text: str,
        metadata: dict[str, str] | None = None,
    ) -> None:
        """Upsert a document into the vector store."""

    @abstractmethod
    async def remove(self, uuid: str) -> None:
        """Remove a document from the vector store. Idempotent."""

    @abstractmethod
    async def stats(self) -> RAGStats:
        """Snapshot of index state for /ready and observability."""

    async def close(self) -> None:
        """Release embedding model + DB handles."""
        return None


class NoopRAGProvider(RAGProvider):
    """Always-empty provider. Used as default when sidecar disabled."""

    async def query(
        self,
        text: str,
        *,
        k: int = 10,
        filters: RAGFilter | None = None,
    ) -> list[RAGHit]:
        return []

    async def index(
        self,
        uuid: str,
        text: str,
        metadata: dict[str, str] | None = None,
    ) -> None:
        return None

    async def remove(self, uuid: str) -> None:
        return None

    async def stats(self) -> RAGStats:
        from istefox_dt_mcp_schemas.rag import RAGStats

        return RAGStats(
            indexed_count=0,
            last_index_at=None,
            last_reconcile_at=None,
            embedding_model=None,
        )
