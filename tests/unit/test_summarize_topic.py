"""Tests for summarize_topic — clustering helpers + tool integration."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import pytest
from istefox_dt_mcp_schemas.common import Record, RecordKind

from istefox_dt_mcp_server.tools.summarize_topic import _cluster_by_date

if TYPE_CHECKING:
    pass


def _record(
    *,
    uuid: str,
    name: str = "doc",
    location: str = "/Inbox",
    tags: list[str] | None = None,
    kind: RecordKind = RecordKind.PDF,
    modification_date: datetime | None = None,
) -> Record:
    """Mock Record builder for tests."""
    mod = modification_date or datetime(2026, 1, 1)
    return Record(
        uuid=uuid,
        name=name,
        kind=kind,
        location=location,
        reference_url=f"x-d://{uuid}",
        creation_date=mod,
        modification_date=mod,
        tags=tags or [],
    )


# ---------- _cluster_by_date ----------


def test_cluster_by_date_year_month_when_range_within_24_months() -> None:
    """Date range < 24 months → use YYYY-MM labels."""
    records = [
        (_record(uuid="a", modification_date=datetime(2026, 1, 15)), 0.9),
        (_record(uuid="b", modification_date=datetime(2026, 1, 20)), 0.8),
        (_record(uuid="c", modification_date=datetime(2026, 3, 5)), 0.7),
    ]
    clusters = _cluster_by_date(records, max_clusters=10, max_per_cluster=10)
    labels = [c.label for c in clusters]
    assert labels == ["2026-03", "2026-01"]
    assert clusters[1].count == 2
    assert clusters[0].count == 1


def test_cluster_by_date_year_only_when_range_exceeds_24_months() -> None:
    """Date range > 24 months → use YYYY labels."""
    records = [
        (_record(uuid="a", modification_date=datetime(2022, 1, 15)), 0.9),
        (_record(uuid="b", modification_date=datetime(2025, 6, 1)), 0.8),
        (_record(uuid="c", modification_date=datetime(2026, 3, 5)), 0.7),
    ]
    clusters = _cluster_by_date(records, max_clusters=10, max_per_cluster=10)
    labels = [c.label for c in clusters]
    assert labels == ["2026", "2025", "2022"]


def test_cluster_by_date_max_clusters_truncates_oldest() -> None:
    """max_clusters=2 keeps the 2 most recent, drops older."""
    records = [
        (_record(uuid="a", modification_date=datetime(2024, 1, 1)), 0.9),
        (_record(uuid="b", modification_date=datetime(2025, 6, 1)), 0.8),
        (_record(uuid="c", modification_date=datetime(2026, 3, 5)), 0.7),
    ]
    clusters = _cluster_by_date(records, max_clusters=2, max_per_cluster=10)
    labels = [c.label for c in clusters]
    assert labels == ["2026", "2025"]


def test_cluster_by_date_max_per_cluster_truncates_records() -> None:
    """max_per_cluster=2 keeps top 2 records per group, sorted by score."""
    records = [
        (_record(uuid="a", modification_date=datetime(2026, 1, 1)), 0.5),
        (_record(uuid="b", modification_date=datetime(2026, 1, 2)), 0.9),
        (_record(uuid="c", modification_date=datetime(2026, 1, 3)), 0.7),
    ]
    clusters = _cluster_by_date(records, max_clusters=10, max_per_cluster=2)
    assert len(clusters) == 1
    assert clusters[0].count == 3
    assert len(clusters[0].records) == 2
    assert clusters[0].records[0].uuid == "b"
    assert clusters[0].records[1].uuid == "c"


def test_cluster_by_date_empty_input_returns_empty() -> None:
    assert _cluster_by_date([], max_clusters=10, max_per_cluster=10) == []


# ---------- _cluster_by_tags ----------


def test_cluster_by_tags_explodes_multi_tag_records() -> None:
    """A record with 3 tags appears in 3 clusters."""
    from istefox_dt_mcp_server.tools.summarize_topic import _cluster_by_tags

    records = [
        (_record(uuid="a", tags=["x", "y"]), 0.9),
        (_record(uuid="b", tags=["y"]), 0.8),
        (_record(uuid="c", tags=["x", "z"]), 0.7),
    ]
    clusters = _cluster_by_tags(records, max_clusters=10, max_per_cluster=10)
    by_label = {c.label: c for c in clusters}
    assert by_label["x"].count == 2
    assert by_label["y"].count == 2
    assert by_label["z"].count == 1


def test_cluster_by_tags_no_tags_returns_empty() -> None:
    """Records with no tags produce no tag clusters."""
    from istefox_dt_mcp_server.tools.summarize_topic import _cluster_by_tags

    records = [(_record(uuid="a", tags=[]), 0.9)]
    clusters = _cluster_by_tags(records, max_clusters=10, max_per_cluster=10)
    assert clusters == []


# ---------- _cluster_by_kind ----------


def test_cluster_by_kind_groups_by_record_kind() -> None:
    from istefox_dt_mcp_server.tools.summarize_topic import _cluster_by_kind

    records = [
        (_record(uuid="a", kind=RecordKind.PDF), 0.9),
        (_record(uuid="b", kind=RecordKind.PDF), 0.8),
        (_record(uuid="c", kind=RecordKind.MARKDOWN), 0.7),
    ]
    clusters = _cluster_by_kind(records, max_clusters=10, max_per_cluster=10)
    labels = [c.label for c in clusters]
    # PDF first (count 2), then markdown (count 1).
    # RecordKind.PDF.value == "PDF", RecordKind.MARKDOWN.value == "markdown".
    assert labels[0] == "PDF"
    assert clusters[0].count == 2


# ---------- _cluster_by_location ----------


def test_cluster_by_location_groups_by_full_path() -> None:
    from istefox_dt_mcp_server.tools.summarize_topic import _cluster_by_location

    records = [
        (_record(uuid="a", location="/Inbox/Triage"), 0.9),
        (_record(uuid="b", location="/Inbox/Triage"), 0.8),
        (_record(uuid="c", location="/Archive/2025"), 0.7),
    ]
    clusters = _cluster_by_location(records, max_clusters=10, max_per_cluster=10)
    labels = [c.label for c in clusters]
    assert labels[0] == "/Inbox/Triage"
    assert clusters[0].count == 2


def test_cluster_by_kind_max_clusters_truncates() -> None:
    from istefox_dt_mcp_server.tools.summarize_topic import _cluster_by_kind

    records = [
        (_record(uuid="a", kind=RecordKind.PDF), 0.9),
        (_record(uuid="b", kind=RecordKind.MARKDOWN), 0.8),
        (_record(uuid="c", kind=RecordKind.HTML), 0.7),
    ]
    clusters = _cluster_by_kind(records, max_clusters=2, max_per_cluster=10)
    assert len(clusters) == 2


def test_cluster_by_tags_max_per_cluster_truncates() -> None:
    from istefox_dt_mcp_server.tools.summarize_topic import _cluster_by_tags

    records = [
        (_record(uuid="a", tags=["x"]), 0.5),
        (_record(uuid="b", tags=["x"]), 0.9),
        (_record(uuid="c", tags=["x"]), 0.7),
    ]
    clusters = _cluster_by_tags(records, max_clusters=10, max_per_cluster=2)
    assert clusters[0].count == 3
    assert len(clusters[0].records) == 2
    assert clusters[0].records[0].uuid == "b"
