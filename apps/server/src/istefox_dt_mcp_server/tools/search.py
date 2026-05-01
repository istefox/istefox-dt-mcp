"""search tool — BM25 / semantic / hybrid retrieval.

Modes:
- `bm25` (default): DEVONthink native full-text search only
- `semantic`: vector retrieval via RAG provider only (requires
  ISTEFOX_RAG_ENABLED=1; falls back to bm25 if not)
- `hybrid`: both, merged via Reciprocal Rank Fusion (RRF)

The output schema is identical across modes — `score` reflects the
fused rank in hybrid mode, the cosine similarity in semantic mode,
and `null` in bm25 mode (DT does not expose a native score).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog
from istefox_dt_mcp_adapter.rag import NoopRAGProvider
from istefox_dt_mcp_schemas.common import SearchResult
from istefox_dt_mcp_schemas.rag import RAGFilter, RAGHit
from istefox_dt_mcp_schemas.tools import SearchInput, SearchOutput

from ._common import safe_call

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from ..deps import Deps


log = structlog.get_logger(__name__)

# RRF constant. Higher = flatter fusion (less weight to top ranks).
# 60 is the value from the original RRF paper (Cormack et al. 2009).
RRF_K = 60


def _rrf_fuse(
    bm25_uuids: list[str],
    rag_hits: list[RAGHit],
    *,
    max_results: int,
    k: int = RRF_K,
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion of two ordered lists.

    Returns [(uuid, fused_score), ...] sorted by score descending.
    A doc absent from one list contributes only the other list's term.
    """
    scores: dict[str, float] = {}
    for rank, uuid in enumerate(bm25_uuids):
        scores[uuid] = scores.get(uuid, 0.0) + 1.0 / (k + rank + 1)
    for rank, hit in enumerate(rag_hits):
        scores[hit.uuid] = scores.get(hit.uuid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:max_results]


def register(mcp: FastMCP, deps: Deps) -> None:
    @mcp.tool()
    async def search(input: SearchInput) -> SearchOutput:  # noqa: A002
        kinds = [k.value for k in input.kinds] if input.kinds else None
        mode = input.mode
        rag_available = not isinstance(deps.rag, NoopRAGProvider)
        if mode in {"semantic", "hybrid"} and not rag_available:
            log.info("search_rag_unavailable_fallback_bm25", requested=mode)
            mode = "bm25"

        async def op() -> list[SearchResult]:
            if mode == "bm25":
                return await deps.adapter.search(
                    input.query,
                    databases=input.databases,
                    max_results=input.max_results,
                    kinds=kinds,
                )

            rag_filter = RAGFilter(databases=input.databases, kinds=kinds)
            if mode == "semantic":
                hits = await deps.rag.query(
                    input.query, k=input.max_results, filters=rag_filter
                )
                return await _hydrate_semantic_hits(deps, hits)

            # mode == "hybrid": run both in parallel
            bm25_task = deps.adapter.search(
                input.query,
                databases=input.databases,
                max_results=input.max_results * 2,
                kinds=kinds,
            )
            rag_task = deps.rag.query(
                input.query, k=input.max_results * 2, filters=rag_filter
            )
            bm25_results, rag_hits = await asyncio.gather(bm25_task, rag_task)

            fused = _rrf_fuse(
                [r.uuid for r in bm25_results],
                rag_hits,
                max_results=input.max_results,
            )

            # Build final SearchResult list, preferring metadata from
            # bm25 results (they include name/location/reference_url
            # already), filling gaps from rag hydration.
            bm25_by_uuid = {r.uuid: r for r in bm25_results}
            rag_by_uuid = {h.uuid: h for h in rag_hits}
            need_hydration = [
                uuid
                for uuid, _ in fused
                if uuid not in bm25_by_uuid and uuid in rag_by_uuid
            ]
            hydrated = await _hydrate_uuids(deps, need_hydration)
            hydrated_by_uuid = {r.uuid: r for r in hydrated}

            out: list[SearchResult] = []
            for uuid, fused_score in fused:
                if uuid in bm25_by_uuid:
                    base = bm25_by_uuid[uuid]
                    out.append(
                        SearchResult(
                            uuid=base.uuid,
                            name=base.name,
                            location=base.location,
                            reference_url=base.reference_url,
                            score=fused_score,
                            snippet=(
                                rag_by_uuid[uuid].snippet
                                if uuid in rag_by_uuid
                                else None
                            ),
                        )
                    )
                elif uuid in hydrated_by_uuid:
                    base = hydrated_by_uuid[uuid]
                    out.append(
                        SearchResult(
                            uuid=base.uuid,
                            name=base.name,
                            location=base.location,
                            reference_url=base.reference_url,
                            score=fused_score,
                            snippet=(
                                rag_by_uuid[uuid].snippet
                                if uuid in rag_by_uuid
                                else None
                            ),
                        )
                    )
            return out

        return await safe_call(
            tool_name="search",
            input_data=input.model_dump(mode="json"),
            deps=deps,
            operation=op,
            output_factory=SearchOutput,
        )


async def _hydrate_semantic_hits(deps: Deps, hits: list[RAGHit]) -> list[SearchResult]:
    """Pure-semantic mode: pull metadata for each RAG hit via get_record."""
    results: list[SearchResult] = []
    for hit in hits:
        try:
            rec = await deps.adapter.get_record(hit.uuid)
        except Exception as e:
            log.debug("search_hydrate_failed", uuid=hit.uuid, error=str(e))
            continue
        results.append(
            SearchResult(
                uuid=hit.uuid,
                name=rec.name,
                location=rec.location,
                reference_url=rec.reference_url,
                score=hit.score,
                snippet=hit.snippet,
            )
        )
    return results


async def _hydrate_uuids(deps: Deps, uuids: list[str]) -> list[SearchResult]:
    """Hybrid-mode helper: fetch metadata for vector-only winners."""
    results: list[SearchResult] = []
    for uuid in uuids:
        try:
            rec = await deps.adapter.get_record(uuid)
        except Exception as e:
            log.debug("search_hydrate_failed", uuid=uuid, error=str(e))
            continue
        results.append(
            SearchResult(
                uuid=uuid,
                name=rec.name,
                location=rec.location,
                reference_url=rec.reference_url,
            )
        )
    return results
