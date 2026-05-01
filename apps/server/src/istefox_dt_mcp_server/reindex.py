"""Reindex pipeline: walk DT databases → fetch text → push to RAG.

One-shot manual operation in v1. The smart-rule-driven incremental
sync ships in W6 (DT4 smart rule POSTs to a local webhook → triggers
single-record `index` calls).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from .deps import Deps


log = structlog.get_logger(__name__)


SNIPPET_CHARS = 4000  # full-doc indexing for now; chunking lands W6+
BATCH_SIZE = 64


async def reindex_database(
    deps: Deps,
    database_name: str,
    *,
    limit: int | None = None,
    batch_size: int = BATCH_SIZE,
) -> dict[str, int]:
    """Index all content records of one database into the RAG provider.

    Returns counters: {seen, indexed, empty_text, errors}.
    Skips records whose plain text is empty (groups, images without OCR).
    """
    from istefox_dt_mcp_adapter.rag import NoopRAGProvider
    from istefox_dt_mcp_sidecar.chroma_provider import ChromaRAGProvider

    if isinstance(deps.rag, NoopRAGProvider):
        raise RuntimeError(
            "RAG provider is Noop — set ISTEFOX_RAG_ENABLED=1 before reindex"
        )
    if not isinstance(deps.rag, ChromaRAGProvider):
        log.warning("reindex_unknown_provider", type=type(deps.rag).__name__)

    counters = {"seen": 0, "indexed": 0, "empty_text": 0, "errors": 0}
    offset = 0
    page = 500
    pending: list[tuple[str, str, dict[str, str]]] = []

    while True:
        if limit is not None and counters["seen"] >= limit:
            break
        page_size = page if limit is None else min(page, limit - counters["seen"])
        records, _total = await deps.adapter.enumerate_records(
            database_name, limit=page_size, offset=offset
        )
        if not records:
            break

        for rec in records:
            if limit is not None and counters["seen"] >= limit:
                break
            counters["seen"] += 1
            uuid = rec.get("uuid") or ""
            if not uuid:
                continue
            try:
                text = await deps.adapter.get_record_text(uuid, max_chars=SNIPPET_CHARS)
            except Exception as e:
                log.warning("reindex_fetch_failed", uuid=uuid, error=str(e))
                counters["errors"] += 1
                continue

            if not text.strip():
                counters["empty_text"] += 1
                continue

            metadata = {
                "database": database_name,
                "kind": rec.get("kind") or "",
                "name": rec.get("name") or "",
                "location": rec.get("location") or "",
            }
            pending.append((uuid, text, metadata))

            if len(pending) >= batch_size:
                added = await _flush(deps.rag, pending)
                counters["indexed"] += added
                pending.clear()

        offset += len(records)
        if len(records) < page_size:
            break

    if pending:
        added = await _flush(deps.rag, pending)
        counters["indexed"] += added
        pending.clear()

    return counters


async def _flush(
    rag: object,
    items: list[tuple[str, str, dict[str, str]]],
) -> int:
    """Submit a batch to the RAG provider, preferring index_many if available."""
    index_many = getattr(rag, "index_many", None)
    if callable(index_many):
        return int(await index_many(items))
    index_one = rag.index  # type: ignore[attr-defined]
    n = 0
    for uuid, text, meta in items:
        await index_one(uuid, text, meta)
        n += 1
    return n
