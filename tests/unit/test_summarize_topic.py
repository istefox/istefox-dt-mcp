"""Tests for summarize_topic — clustering helpers + tool integration."""

from __future__ import annotations

from datetime import datetime

import pytest
from istefox_dt_mcp_schemas.common import Record, RecordKind
from istefox_dt_mcp_server.tools.summarize_topic import _cluster_by_date


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


# ---------- summarize_topic_op (with mocked deps) ----------


@pytest.mark.asyncio
async def test_summarize_topic_op_bm25_path_returns_clusters(deps) -> None:
    """When RAG is disabled, retrieval uses adapter.search and clusters
    by date+tags by default."""
    from unittest.mock import AsyncMock

    from istefox_dt_mcp_schemas.common import SearchResult
    from istefox_dt_mcp_schemas.tools import SummarizeTopicInput
    from istefox_dt_mcp_server.tools.summarize_topic import summarize_topic_op

    deps.adapter.search = AsyncMock(
        return_value=[
            SearchResult(
                uuid="a",
                name="A",
                location="/Inbox",
                reference_url="x-d://a",
            ),
            SearchResult(
                uuid="b",
                name="B",
                location="/Archive",
                reference_url="x-d://b",
            ),
        ]
    )
    deps.adapter.get_record = AsyncMock(
        side_effect=lambda uuid: _record(
            uuid=uuid,
            tags=["x"],
            modification_date=datetime(2026, 1, 1),
        )
    )

    result = await summarize_topic_op(
        deps,
        SummarizeTopicInput(topic="hello world"),
    )

    assert result.retrieval_mode == "bm25"
    assert result.total_records_retrieved == 2
    dims = {c.dimension for c in result.clusters}
    assert dims == {"date", "tags"}


@pytest.mark.asyncio
async def test_summarize_topic_op_skips_hydration_failures(deps) -> None:
    """A record that fails to hydrate is dropped silently, others kept."""
    from unittest.mock import AsyncMock

    from istefox_dt_mcp_schemas.common import SearchResult
    from istefox_dt_mcp_schemas.tools import SummarizeTopicInput
    from istefox_dt_mcp_server.tools.summarize_topic import summarize_topic_op

    deps.adapter.search = AsyncMock(
        return_value=[
            SearchResult(
                uuid="ok", name="A", location="/Inbox", reference_url="x-d://ok"
            ),
            SearchResult(
                uuid="bad", name="B", location="/Inbox", reference_url="x-d://bad"
            ),
        ]
    )

    async def get_record_side_effect(uuid: str):
        if uuid == "bad":
            raise RuntimeError("simulated hydration failure")
        return _record(uuid=uuid, tags=["t"])

    deps.adapter.get_record = AsyncMock(side_effect=get_record_side_effect)

    result = await summarize_topic_op(
        deps,
        SummarizeTopicInput(topic="topic"),
    )

    assert result.total_records_retrieved == 1


@pytest.mark.asyncio
async def test_summarize_topic_op_empty_retrieval_returns_empty_clusters(deps) -> None:
    from unittest.mock import AsyncMock

    from istefox_dt_mcp_schemas.tools import SummarizeTopicInput
    from istefox_dt_mcp_server.tools.summarize_topic import summarize_topic_op

    deps.adapter.search = AsyncMock(return_value=[])
    deps.adapter.get_record = AsyncMock()

    result = await summarize_topic_op(
        deps,
        SummarizeTopicInput(topic="topic"),
    )

    assert result.total_records_retrieved == 0
    assert result.clusters == []
    deps.adapter.get_record.assert_not_called()


@pytest.mark.asyncio
async def test_summarize_topic_op_respects_cluster_by_param(deps) -> None:
    """cluster_by=['kind'] produces only kind-dimension clusters."""
    from unittest.mock import AsyncMock

    from istefox_dt_mcp_schemas.common import SearchResult
    from istefox_dt_mcp_schemas.tools import SummarizeTopicInput
    from istefox_dt_mcp_server.tools.summarize_topic import summarize_topic_op

    deps.adapter.search = AsyncMock(
        return_value=[
            SearchResult(
                uuid="a", name="A", location="/Inbox", reference_url="x-d://a"
            ),
        ]
    )
    deps.adapter.get_record = AsyncMock(
        return_value=_record(uuid="a", kind=RecordKind.PDF, tags=["t"])
    )

    result = await summarize_topic_op(
        deps,
        SummarizeTopicInput(topic="topic", cluster_by=["kind"]),
    )

    dims = {c.dimension for c in result.clusters}
    assert dims == {"kind"}
