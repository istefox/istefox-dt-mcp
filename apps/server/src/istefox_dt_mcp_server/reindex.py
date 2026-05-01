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


async def reconcile_database(
    deps: Deps,
    database_name: str,
    *,
    batch_size: int = BATCH_SIZE,
) -> dict[str, int]:
    """Reconcile a DT database against the RAG store.

    Strategy (set-diff, no fingerprint yet — fingerprint diff lands
    in v1.5 once we wire the modification_date round-trip):
    - Compute `dt_uuids` by walking DT (paged enumerate)
    - Compute `rag_uuids` via `rag.list_uuids()`
    - Index `dt_uuids - rag_uuids`  (new records)
    - Remove `rag_uuids - dt_uuids`  (orphan vectors)
    - Skip the intersection — fingerprint-based update comes later

    Returns counters: {dt_count, rag_count, indexed, removed,
    empty_text, errors}.
    """
    from istefox_dt_mcp_adapter.rag import NoopRAGProvider

    if isinstance(deps.rag, NoopRAGProvider):
        raise RuntimeError(
            "RAG provider is Noop — set ISTEFOX_RAG_ENABLED=1 before reconcile"
        )

    counters = {
        "dt_count": 0,
        "rag_count": 0,
        "indexed": 0,
        "removed": 0,
        "empty_text": 0,
        "errors": 0,
    }

    # Step 1: enumerate all DT content records
    dt_records: dict[str, dict[str, str]] = {}
    offset = 0
    page = 500
    while True:
        records, _total = await deps.adapter.enumerate_records(
            database_name, limit=page, offset=offset
        )
        if not records:
            break
        for rec in records:
            uuid = rec.get("uuid") or ""
            if uuid:
                dt_records[uuid] = rec
        offset += len(records)
        if len(records) < page:
            break
    counters["dt_count"] = len(dt_records)

    # Step 2: read what's already in the vector store
    rag_uuids = await deps.rag.list_uuids()
    counters["rag_count"] = len(rag_uuids)

    dt_uuid_set = set(dt_records.keys())
    to_add = dt_uuid_set - rag_uuids
    to_remove = rag_uuids - dt_uuid_set

    log.info(
        "reconcile_diff",
        database=database_name,
        dt_count=counters["dt_count"],
        rag_count=counters["rag_count"],
        to_add=len(to_add),
        to_remove=len(to_remove),
    )

    # Step 3: remove orphans
    for uuid in to_remove:
        try:
            await deps.rag.remove(uuid)
            counters["removed"] += 1
        except Exception as e:
            log.warning("reconcile_remove_failed", uuid=uuid, error=str(e))
            counters["errors"] += 1

    # Step 4: index newcomers
    pending: list[tuple[str, str, dict[str, str]]] = []
    for uuid in to_add:
        rec = dt_records[uuid]
        try:
            text = await deps.adapter.get_record_text(uuid, max_chars=SNIPPET_CHARS)
        except Exception as e:
            log.warning("reconcile_fetch_failed", uuid=uuid, error=str(e))
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
            counters["indexed"] += await _flush(deps.rag, pending)
            pending.clear()

    if pending:
        counters["indexed"] += await _flush(deps.rag, pending)

    # Mark reconcile timestamp on the provider if it supports it
    mark = getattr(deps.rag, "mark_reconciled", None)
    if callable(mark):
        mark()

    return counters
