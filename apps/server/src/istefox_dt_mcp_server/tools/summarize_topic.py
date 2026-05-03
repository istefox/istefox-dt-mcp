"""summarize_topic tool — server-side clustering retrieval.

Retrieves records related to a topic (vector if RAG is enabled, BM25
fallback otherwise) and groups them by user-selected dimensions:
date, tags, kind, location.

Output is a flat list of Cluster objects across all requested
dimensions, with bounded size (default: 10 clusters per dimension,
10 records per cluster, 50 records total retrieved).
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import TYPE_CHECKING, Literal

import structlog
from istefox_dt_mcp_adapter.rag import NoopRAGProvider
from istefox_dt_mcp_schemas.rag import RAGFilter
from istefox_dt_mcp_schemas.tools import (
    Citation,
    Cluster,
    SummarizeTopicInput,
    SummarizeTopicOutput,
    SummarizeTopicResult,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from istefox_dt_mcp_schemas.common import Record

    from ..deps import Deps


log = structlog.get_logger(__name__)


YEAR_THRESHOLD_DAYS = 730  # ≈24 months — switch from year-month to year-only


def _cluster_by_date(
    records: list[tuple[Record, float]],
    *,
    max_clusters: int,
    max_per_cluster: int,
) -> list[Cluster]:
    """Group records by modification_date with adaptive granularity.

    If the date range across the records exceeds 730 days (~24 months),
    use year-only labels ("2025"). Otherwise use year-month ("2025-03").

    Sort clusters reverse-chronologically. Take top ``max_clusters``,
    each truncated to ``max_per_cluster`` records sorted by score desc.

    Args:
        records: Hydrated records paired with their retrieval score.
        max_clusters: Maximum clusters to keep along this dimension.
        max_per_cluster: Maximum records to keep per cluster.

    Returns:
        List of Cluster objects with dimension="date".
    """
    if not records:
        return []

    dates = [r.modification_date for r, _ in records]
    span_days = (max(dates) - min(dates)).days
    use_year_only = span_days > YEAR_THRESHOLD_DAYS

    groups: dict[str, list[tuple[Record, float]]] = defaultdict(list)
    for rec, score in records:
        if use_year_only:
            label = rec.modification_date.strftime("%Y")
        else:
            label = rec.modification_date.strftime("%Y-%m")
        groups[label].append((rec, score))

    sorted_labels = sorted(groups.keys(), reverse=True)
    sorted_labels = sorted_labels[:max_clusters]

    out: list[Cluster] = []
    for label in sorted_labels:
        bucket = groups[label]
        bucket.sort(key=lambda pair: pair[1], reverse=True)
        top = bucket[:max_per_cluster]
        out.append(
            Cluster(
                dimension="date",
                label=label,
                count=len(bucket),
                records=[_record_to_citation(rec) for rec, _ in top],
            )
        )
    return out


def _record_to_citation(rec: Record) -> Citation:
    """Project a Record into the lightweight Citation shape."""
    return Citation(
        uuid=rec.uuid,
        name=rec.name,
        snippet="",
        reference_url=rec.reference_url,
    )


def _cluster_by_tags(
    records: list[tuple[Record, float]],
    *,
    max_clusters: int,
    max_per_cluster: int,
) -> list[Cluster]:
    """Group records by tag. Multi-tag records appear in multiple clusters.

    Sort clusters by record count desc, break ties alphabetically.
    """
    if not records:
        return []

    groups: dict[str, list[tuple[Record, float]]] = defaultdict(list)
    for rec, score in records:
        for tag in rec.tags:
            groups[tag].append((rec, score))

    if not groups:
        return []

    sorted_labels = sorted(groups.keys(), key=lambda k: (-len(groups[k]), k))
    sorted_labels = sorted_labels[:max_clusters]

    out: list[Cluster] = []
    for label in sorted_labels:
        bucket = groups[label]
        bucket.sort(key=lambda pair: pair[1], reverse=True)
        top = bucket[:max_per_cluster]
        out.append(
            Cluster(
                dimension="tags",
                label=label,
                count=len(bucket),
                records=[_record_to_citation(rec) for rec, _ in top],
            )
        )
    return out


def _cluster_by_kind(
    records: list[tuple[Record, float]],
    *,
    max_clusters: int,
    max_per_cluster: int,
) -> list[Cluster]:
    """Group records by RecordKind enum value. Sort by count desc."""
    if not records:
        return []

    groups: dict[str, list[tuple[Record, float]]] = defaultdict(list)
    for rec, score in records:
        groups[rec.kind.value].append((rec, score))

    sorted_labels = sorted(groups.keys(), key=lambda k: (-len(groups[k]), k))
    sorted_labels = sorted_labels[:max_clusters]

    out: list[Cluster] = []
    for label in sorted_labels:
        bucket = groups[label]
        bucket.sort(key=lambda pair: pair[1], reverse=True)
        top = bucket[:max_per_cluster]
        out.append(
            Cluster(
                dimension="kind",
                label=label,
                count=len(bucket),
                records=[_record_to_citation(rec) for rec, _ in top],
            )
        )
    return out


def _cluster_by_location(
    records: list[tuple[Record, float]],
    *,
    max_clusters: int,
    max_per_cluster: int,
) -> list[Cluster]:
    """Group records by full location path. Sort by count desc."""
    if not records:
        return []

    groups: dict[str, list[tuple[Record, float]]] = defaultdict(list)
    for rec, score in records:
        groups[rec.location].append((rec, score))

    sorted_labels = sorted(groups.keys(), key=lambda k: (-len(groups[k]), k))
    sorted_labels = sorted_labels[:max_clusters]

    out: list[Cluster] = []
    for label in sorted_labels:
        bucket = groups[label]
        bucket.sort(key=lambda pair: pair[1], reverse=True)
        top = bucket[:max_per_cluster]
        out.append(
            Cluster(
                dimension="location",
                label=label,
                count=len(bucket),
                records=[_record_to_citation(rec) for rec, _ in top],
            )
        )
    return out


async def _hydrate_records(
    deps: Deps,
    hits: list[tuple[str, float]],
) -> list[tuple[Record, float]]:
    """Fetch full Record objects for each hit, in parallel.

    Failed fetches are skipped with a warning log. Returns only records
    that hydrated successfully, paired with their original score.
    """

    async def _one(uuid: str, score: float) -> tuple[Record, float] | None:
        try:
            rec = await deps.adapter.get_record(uuid)
            return (rec, score)
        except Exception as e:
            log.debug("summarize_topic_hydration_failed", uuid=uuid, error=str(e))
            return None

    results = await asyncio.gather(
        *(_one(uuid, score) for uuid, score in hits),
        return_exceptions=False,
    )
    return [r for r in results if r is not None]


def _synthesize_bm25_scores(n: int) -> list[float]:
    """Generate descending rank-based scores for BM25 hits.

    BM25 results don't carry a normalized score, but we need ordering
    inside clusters. Synthesize: position 0 → 1.0, position N-1 → ~0.0.
    """
    if n == 0:
        return []
    return [1.0 - (i / n) for i in range(n)]


CLUSTERER_BY_DIMENSION: dict[str, object] = {
    "date": _cluster_by_date,
    "tags": _cluster_by_tags,
    "kind": _cluster_by_kind,
    "location": _cluster_by_location,
}


async def summarize_topic_op(
    deps: Deps,
    input_data: SummarizeTopicInput,
) -> SummarizeTopicResult:
    """Top-level operation: retrieve, hydrate, cluster.

    Args:
        deps: Wired dependency graph (adapter, rag, cache, audit).
        input_data: Validated SummarizeTopicInput.

    Returns:
        SummarizeTopicResult with flat clusters list and retrieval mode.
    """
    rag_available = not isinstance(deps.rag, NoopRAGProvider)

    if rag_available:
        rag_filter = RAGFilter(databases=input_data.databases)
        rag_hits = await deps.rag.query(
            input_data.topic, k=input_data.max_records, filters=rag_filter
        )
        hits: list[tuple[str, float]] = [(h.uuid, h.score) for h in rag_hits]
        retrieval_mode: Literal["vector", "bm25"] = "vector"
    else:
        bm25_hits = await deps.adapter.search(
            input_data.topic,
            databases=input_data.databases,
            max_results=input_data.max_records,
        )
        synthesized = _synthesize_bm25_scores(len(bm25_hits))
        hits = [
            (h.uuid, score) for h, score in zip(bm25_hits, synthesized, strict=True)
        ]
        retrieval_mode = "bm25"

    log.debug(
        "summarize_topic_retrieved",
        mode=retrieval_mode,
        n_hits=len(hits),
        topic_chars=len(input_data.topic),
    )

    records = await _hydrate_records(deps, hits)

    clusters: list[Cluster] = []
    for dimension in input_data.cluster_by:
        clusterer = CLUSTERER_BY_DIMENSION[dimension]
        clusters.extend(
            clusterer(  # type: ignore[operator]
                records,
                max_clusters=input_data.max_clusters,
                max_per_cluster=input_data.max_per_cluster,
            )
        )

    return SummarizeTopicResult(
        topic=input_data.topic,
        clusters=clusters,
        total_records_retrieved=len(records),
        retrieval_mode=retrieval_mode,
    )


def register(mcp: FastMCP, deps: Deps) -> None:
    """Wire the summarize_topic MCP tool to the FastMCP server."""
    from ._common import safe_call

    @mcp.tool()
    async def summarize_topic(
        input: SummarizeTopicInput,  # noqa: A002 — same
    ) -> SummarizeTopicOutput:
        async def op() -> SummarizeTopicResult:
            return await summarize_topic_op(deps, input)

        return await safe_call(
            tool_name="summarize_topic",
            input_data=input.model_dump(),
            deps=deps,
            operation=op,
            output_factory=SummarizeTopicOutput,
        )
