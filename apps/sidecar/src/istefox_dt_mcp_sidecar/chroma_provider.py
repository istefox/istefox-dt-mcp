"""ChromaRAGProvider — same-process RAG using ChromaDB embedded.

Implements the `RAGProvider` contract from `libs/adapter`. Lives in
the sidecar package because of the heavy deps (chromadb, torch,
sentence-transformers) — keeping these out of `apps/server` avoids
penalizing startup when RAG is disabled.

Lazy initialization:
- The embedding model is downloaded/loaded on the first `query` or
  `index` call, not at __init__. This lets the server start quickly
  even when RAG is configured but not exercised.

Thread-safety:
- ChromaDB embedded is NOT thread-safe for writes. We serialize
  index/remove operations with an asyncio.Lock; queries are
  read-only and run unsynchronized.

Spike validated (2026-05-01):
- 50K records, 100 q/s sustained, p95 5.5 ms (MiniLM proxy)
- See `docs/spikes/2026-05-01-chromadb-stress-test.md`
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
from istefox_dt_mcp_adapter.rag import RAGProvider
from istefox_dt_mcp_schemas.rag import RAGFilter, RAGHit, RAGStats

if TYPE_CHECKING:
    import chromadb  # noqa: F401  — heavy import done lazily
    from sentence_transformers import SentenceTransformer  # noqa: F401


log = structlog.get_logger(__name__)

DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_COLLECTION = "istefox_dt"


class ChromaRAGProvider(RAGProvider):
    """Same-process RAG over ChromaDB persistent storage."""

    def __init__(
        self,
        *,
        db_dir: Path | str,
        model_name: str = DEFAULT_MODEL,
        collection_name: str = DEFAULT_COLLECTION,
    ) -> None:
        self._db_dir = Path(db_dir).expanduser()
        self._db_dir.mkdir(parents=True, exist_ok=True)
        self._model_name = model_name
        self._collection_name = collection_name
        self._lock = asyncio.Lock()
        self._client: Any = None
        self._collection: Any = None
        self._model: Any = None
        self._last_index_at: str | None = None
        self._last_reconcile_at: str | None = None

    async def _ensure_loaded(self) -> None:
        """Lazy import + initialize on first use."""
        if self._collection is not None and self._model is not None:
            return
        async with self._lock:
            if self._collection is not None and self._model is not None:
                return  # racey re-check after acquiring the lock

            log.info("rag_loading", model=self._model_name, db=str(self._db_dir))

            # Heavy imports happen here, not at module level
            import chromadb
            from chromadb.config import Settings
            from sentence_transformers import SentenceTransformer

            # Silence the noisy chromadb startup banners; structlog stays
            logging.getLogger("chromadb").setLevel(logging.WARNING)

            self._model = SentenceTransformer(self._model_name)
            self._client = chromadb.PersistentClient(
                path=str(self._db_dir),
                settings=Settings(anonymized_telemetry=False),
            )
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            log.info(
                "rag_loaded",
                model=self._model_name,
                count=self._collection.count(),
            )

    async def query(
        self,
        text: str,
        *,
        k: int = 10,
        filters: RAGFilter | None = None,
    ) -> list[RAGHit]:
        await self._ensure_loaded()
        # Embedding: CPU/GPU bound — push to thread pool
        emb = await asyncio.to_thread(
            self._model.encode,
            [text],
            convert_to_numpy=True,
            show_progress_bar=False,
        )

        where = self._build_where_filter(filters)
        result = await asyncio.to_thread(
            self._collection.query,
            query_embeddings=emb.tolist(),
            n_results=k,
            where=where,
        )

        # ChromaDB returns parallel lists, one per query embedding (we send one)
        ids = (result.get("ids") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        documents = (result.get("documents") or [[]])[0] or []
        metadatas = (result.get("metadatas") or [[]])[0] or []

        hits: list[RAGHit] = []
        for i, uuid in enumerate(ids):
            distance = distances[i] if i < len(distances) else 1.0
            # cosine distance is in [0, 2]; normalize to score in [0, 1]
            score = max(0.0, min(1.0, 1.0 - (distance / 2.0)))
            snippet = (documents[i] or "")[:300] if i < len(documents) else ""
            metadata = metadatas[i] if i < len(metadatas) else {}
            hits.append(
                RAGHit(
                    uuid=uuid,
                    score=score,
                    snippet=snippet,
                    metadata=dict(metadata or {}),
                )
            )
        return hits

    async def index(
        self,
        uuid: str,
        text: str,
        metadata: dict[str, str] | None = None,
    ) -> None:
        await self._ensure_loaded()
        emb = await asyncio.to_thread(
            self._model.encode,
            [text],
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        async with self._lock:
            await asyncio.to_thread(
                self._collection.upsert,
                ids=[uuid],
                embeddings=emb.tolist(),
                documents=[text],
                metadatas=[metadata or {}],
            )
        self._last_index_at = dt.datetime.now(dt.UTC).isoformat()

    async def index_many(
        self,
        items: list[tuple[str, str, dict[str, str] | None]],
    ) -> int:
        """Batch index. Returns count actually indexed."""
        if not items:
            return 0
        await self._ensure_loaded()
        ids = [it[0] for it in items]
        texts = [it[1] for it in items]
        metas = [it[2] or {} for it in items]
        emb = await asyncio.to_thread(
            self._model.encode,
            texts,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        async with self._lock:
            await asyncio.to_thread(
                self._collection.upsert,
                ids=ids,
                embeddings=emb.tolist(),
                documents=texts,
                metadatas=metas,
            )
        self._last_index_at = dt.datetime.now(dt.UTC).isoformat()
        return len(ids)

    async def remove(self, uuid: str) -> None:
        await self._ensure_loaded()
        async with self._lock:
            try:
                await asyncio.to_thread(self._collection.delete, ids=[uuid])
            except Exception as e:
                log.debug("rag_remove_idempotent", uuid=uuid, error=str(e))

    async def list_uuids(self) -> set[str]:
        if self._collection is None:
            return set()
        result = await asyncio.to_thread(self._collection.get, include=[])
        ids = result.get("ids") or []
        return set(ids)

    def mark_reconciled(self) -> None:
        self._last_reconcile_at = dt.datetime.now(dt.UTC).isoformat()

    async def stats(self) -> RAGStats:
        if self._collection is None:
            return RAGStats(
                indexed_count=0,
                last_index_at=None,
                last_reconcile_at=None,
                embedding_model=self._model_name,
            )
        count = await asyncio.to_thread(self._collection.count)
        return RAGStats(
            indexed_count=count,
            last_index_at=self._last_index_at,
            last_reconcile_at=self._last_reconcile_at,
            embedding_model=self._model_name,
        )

    async def close(self) -> None:
        # ChromaDB persistent client has no explicit close. The model
        # is GC'd when the provider is dropped.
        self._collection = None
        self._client = None
        self._model = None

    @staticmethod
    def _build_where_filter(filters: RAGFilter | None) -> dict[str, Any] | None:
        """Translate RAGFilter to a ChromaDB `where` clause."""
        if not filters:
            return None
        clauses: list[dict[str, Any]] = []
        if filters.databases:
            clauses.append({"database": {"$in": filters.databases}})
        if filters.kinds:
            clauses.append({"kind": {"$in": filters.kinds}})
        # tags would need an array contains operator that ChromaDB
        # doesn't expose; we filter post-query in the service layer
        if not clauses:
            return None
        if len(clauses) == 1:
            return clauses[0]
        return {"$and": clauses}
