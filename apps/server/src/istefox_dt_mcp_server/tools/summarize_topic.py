"""summarize_topic tool — server-side clustering retrieval.

Retrieves records related to a topic (vector if RAG is enabled, BM25
fallback otherwise) and groups them by user-selected dimensions:
date, tags, kind, location.

Output is a flat list of Cluster objects across all requested
dimensions, with bounded size (default: 10 clusters per dimension,
10 records per cluster, 50 records total retrieved).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING, Literal

import structlog
from istefox_dt_mcp_schemas.common import Record
from istefox_dt_mcp_schemas.tools import Citation, Cluster

if TYPE_CHECKING:
    from fastmcp import FastMCP

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
