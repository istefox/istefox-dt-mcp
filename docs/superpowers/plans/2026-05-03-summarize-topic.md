# `summarize_topic` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new read-only MCP tool `summarize_topic` that retrieves records related to a topic and groups them server-side by user-selected dimensions (date, tags, kind, location).

**Architecture:** Pure functions for the four clustering dimensions, plus a thin top-level operation that retrieves (vector if RAG enabled, BM25 fallback), hydrates records via `deps.adapter.get_record`, and dispatches to the clustering helpers. Output is a flat list of `Cluster` objects across all requested dimensions.

**Tech Stack:** Python 3.12, FastMCP, Pydantic v2, structlog, pytest + pytest-asyncio. Mirrors the existing `ask_database` tool's shape.

**Reference spec:** [`docs/superpowers/specs/2026-05-03-summarize-topic-design.md`](../specs/2026-05-03-summarize-topic-design.md)

---

### Task 1: Branch + baseline

**Files:**
- No file changes — preparation only

- [ ] **Step 1.1: Switch off main with the spec branch as base**

The spec doc lives on `spec/summarize-topic`. The implementation goes on a sibling feature branch derived from it, so the final PR contains both spec and code in one coherent unit (same approach used for drift-detection-3-state).

```bash
git fetch origin
git checkout main
git pull --ff-only
git checkout -b feat/summarize-topic
git merge --no-ff spec/summarize-topic -m "merge spec/summarize-topic into feat/summarize-topic"
```

If `--no-ff` produces an editor prompt, save and exit (or set `GIT_EDITOR=true` for the command).

- [ ] **Step 1.2: Run the existing test suite to establish baseline**

```bash
uv run pytest -q
```

Expected: all tests pass (around 175 in 0.2.0). If anything fails, stop and investigate.

- [ ] **Step 1.3: Read reference files**

```bash
ls apps/server/src/istefox_dt_mcp_server/tools/
wc -l apps/server/src/istefox_dt_mcp_server/tools/ask_database.py
wc -l libs/schemas/src/istefox_dt_mcp_schemas/tools.py
```

Expected: `ask_database.py` is the template (~143 LoC), `tools.py` has ~200 LoC of existing schemas. Skim both to internalize the patterns: `register(mcp, deps)`, `safe_call`, Envelope, StrictModel.

---

### Task 2: Add Pydantic schemas

**Files:**
- Modify: `libs/schemas/src/istefox_dt_mcp_schemas/tools.py` (append 4 schemas at the end)

- [ ] **Step 2.1: Append schemas at the end of `tools.py`**

Append this block at the very end of `libs/schemas/src/istefox_dt_mcp_schemas/tools.py` (after the existing `UndoOutput` class):

```python
# ----------------------------------------------------------------------
# summarize_topic (0.2.0 — read tool with server-side clustering)
# ----------------------------------------------------------------------


class SummarizeTopicInput(StrictModel):
    """Retrieve records related to a topic and group them by dimension.

    Default dimensions are date and tags. The retrieval layer mirrors
    ``ask_database``: vector if RAG is enabled, BM25 fallback otherwise.

    When to use:
    - The user wants a panorama / overview of a topic across many records.
    - You need data already grouped by category (date, tag, kind, location)
      so you can narrate the structure without doing the grouping yourself.

    Don't use for:
    - Direct questions with a single answer -> use ``ask_database``.
    - Listing candidate documents to drill into -> use ``search``.

    Examples:
    - {"topic": "bollette 2025", "cluster_by": ["date", "tags"]}
    - {"topic": "Keraglass", "cluster_by": ["kind", "location"]}
    """

    topic: str = Field(..., min_length=3, max_length=2000)
    databases: list[str] | None = None
    cluster_by: list[Literal["date", "tags", "kind", "location"]] = Field(
        default_factory=lambda: ["date", "tags"],
        min_length=1,
        max_length=4,
    )
    max_records: int = Field(default=50, ge=1, le=200)
    max_per_cluster: int = Field(default=10, ge=1, le=50)
    max_clusters: int = Field(default=10, ge=1, le=50)

    @field_validator("cluster_by")
    @classmethod
    def _dedupe_cluster_by(
        cls, v: list[Literal["date", "tags", "kind", "location"]]
    ) -> list[Literal["date", "tags", "kind", "location"]]:
        # Preserve first-occurrence order; drop duplicates.
        seen: set[str] = set()
        deduped: list[Literal["date", "tags", "kind", "location"]] = []
        for item in v:
            if item not in seen:
                seen.add(item)
                deduped.append(item)
        return deduped


class Cluster(StrictModel):
    """One group of records along a single clustering dimension."""

    dimension: Literal["date", "tags", "kind", "location"]
    label: str
    count: int
    records: list[Citation]


class SummarizeTopicResult(StrictModel):
    """Topic panorama: clusters across requested dimensions."""

    topic: str
    clusters: list[Cluster]
    total_records_retrieved: int
    retrieval_mode: Literal["vector", "bm25"]


class SummarizeTopicOutput(Envelope[SummarizeTopicResult]):
    pass
```

The imports at the top of `tools.py` already include `Field`, `Literal`, `StrictModel`, `Envelope`, `Citation`. Verify with:

```bash
grep -E "^from|^import" libs/schemas/src/istefox_dt_mcp_schemas/tools.py | head -10
```

If `field_validator` is not imported, add it:

```python
from pydantic import Field, field_validator
```

(Likely needs to be added — current imports are minimal.)

- [ ] **Step 2.2: Verify import works**

```bash
uv run python -c "from istefox_dt_mcp_schemas.tools import SummarizeTopicInput, Cluster, SummarizeTopicResult, SummarizeTopicOutput; print('ok')"
```

Expected: prints `ok`. If ImportError, fix the missing import (likely `field_validator`).

- [ ] **Step 2.3: Verify dedupe validator**

```bash
uv run python -c "
from istefox_dt_mcp_schemas.tools import SummarizeTopicInput
i = SummarizeTopicInput(topic='x', cluster_by=['date', 'tags', 'date'])
assert i.cluster_by == ['date', 'tags'], i.cluster_by
print('ok')
"
```

Expected: prints `ok`.

- [ ] **Step 2.4: Verify default cluster_by**

```bash
uv run python -c "
from istefox_dt_mcp_schemas.tools import SummarizeTopicInput
i = SummarizeTopicInput(topic='x')
assert i.cluster_by == ['date', 'tags']
assert i.max_records == 50
assert i.max_per_cluster == 10
assert i.max_clusters == 10
print('ok')
"
```

Expected: prints `ok`.

- [ ] **Step 2.5: Commit**

```bash
git add libs/schemas/src/istefox_dt_mcp_schemas/tools.py
git commit -m "feat(schemas): add SummarizeTopicInput/Cluster/Result/Output

Pydantic v2 schemas for the new summarize_topic tool. Field validator
dedupes cluster_by while preserving first-occurrence order. Limits
default to 50 records / 10 clusters / 10 records-per-cluster, all
configurable.

Spec: docs/superpowers/specs/2026-05-03-summarize-topic-design.md"
```

---

### Task 3: Date clustering helper (TDD, pure function)

**Files:**
- Create: `apps/server/src/istefox_dt_mcp_server/tools/summarize_topic.py` (new module — start with the date helper only)
- Create: `tests/unit/test_summarize_topic.py` (new test file)

- [ ] **Step 3.1: Create the new tool module with imports + date helper signature**

Create `apps/server/src/istefox_dt_mcp_server/tools/summarize_topic.py`:

```python
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

    # Sort cluster labels reverse-chronologically (most recent first).
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
```

- [ ] **Step 3.2: Create the test file with date tests**

Create `tests/unit/test_summarize_topic.py`:

```python
"""Tests for summarize_topic — clustering helpers + tool integration."""

from __future__ import annotations

from datetime import datetime, timedelta
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
    assert clusters[1].count == 2  # January cluster
    assert clusters[0].count == 1  # March cluster


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
    assert clusters[0].count == 3  # original count
    assert len(clusters[0].records) == 2
    # Top 2 by score: b (0.9), c (0.7)
    assert clusters[0].records[0].uuid == "b"
    assert clusters[0].records[1].uuid == "c"


def test_cluster_by_date_empty_input_returns_empty() -> None:
    assert _cluster_by_date([], max_clusters=10, max_per_cluster=10) == []
```

- [ ] **Step 3.3: Run tests, verify they pass**

```bash
uv run pytest tests/unit/test_summarize_topic.py -v
```

Expected: 5 tests pass.

- [ ] **Step 3.4: Commit**

```bash
git add apps/server/src/istefox_dt_mcp_server/tools/summarize_topic.py tests/unit/test_summarize_topic.py
git commit -m "feat(summarize_topic): add _cluster_by_date with adaptive granularity

Pure helper that groups records by modification_date. Adaptive: uses
YYYY when range > 730 days, YYYY-MM otherwise. Sorts clusters reverse-
chronologically, truncates to max_clusters, takes top max_per_cluster
by score within each.

5 unit tests cover both granularities + truncation + empty input."
```

---

### Task 4: Tags / kind / location clustering helpers (TDD)

**Files:**
- Modify: `apps/server/src/istefox_dt_mcp_server/tools/summarize_topic.py` (add 3 helpers)
- Modify: `tests/unit/test_summarize_topic.py` (add 6 tests)

- [ ] **Step 4.1: Append the 3 helpers to `summarize_topic.py`**

Append after `_record_to_citation`:

```python
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
```

- [ ] **Step 4.2: Append tests**

Append at the end of `tests/unit/test_summarize_topic.py`:

```python
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
    assert by_label["x"].count == 2  # a + c
    assert by_label["y"].count == 2  # a + b
    assert by_label["z"].count == 1  # c


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
    # Top 2 by score: b (0.9), c (0.7)
    assert clusters[0].records[0].uuid == "b"
```

- [ ] **Step 4.3: Run tests**

```bash
uv run pytest tests/unit/test_summarize_topic.py -v
```

Expected: 11 tests pass total (5 from Task 3 + 6 new).

- [ ] **Step 4.4: Commit**

```bash
git add apps/server/src/istefox_dt_mcp_server/tools/summarize_topic.py tests/unit/test_summarize_topic.py
git commit -m "feat(summarize_topic): add _cluster_by_tags / _cluster_by_kind / _cluster_by_location

Three pure helpers, parallel structure to _cluster_by_date. Tags
explode multi-tagged records into multiple clusters. Kind uses the
RecordKind enum value as label. Location uses the full DT path.

All sort clusters by record-count desc with alphabetical tie-break,
respect max_clusters and max_per_cluster, return empty list on empty
input. 6 new unit tests."
```

---

### Task 5: Hydration + score synthesis + `summarize_topic_op`

**Files:**
- Modify: `apps/server/src/istefox_dt_mcp_server/tools/summarize_topic.py` (add hydration, score synthesis, and the top-level operation)
- Modify: `tests/unit/test_summarize_topic.py` (add 4 integration-style unit tests with mocked deps)

- [ ] **Step 5.1: Append hydration + op to `summarize_topic.py`**

Add the necessary imports near the top — change the imports section to:

```python
import asyncio
from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING, Literal

import structlog
from istefox_dt_mcp_adapter.rag import NoopRAGProvider
from istefox_dt_mcp_schemas.common import Record
from istefox_dt_mcp_schemas.rag import RAGFilter
from istefox_dt_mcp_schemas.tools import (
    Citation,
    Cluster,
    SummarizeTopicInput,
    SummarizeTopicOutput,
    SummarizeTopicResult,
)
```

Append at the end of the module:

```python
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
        hits = [(h.uuid, score) for h, score in zip(bm25_hits, synthesized, strict=True)]
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
```

- [ ] **Step 5.2: Append integration-style unit tests**

Append at the end of `tests/unit/test_summarize_topic.py`:

```python
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
    # default cluster_by = ["date", "tags"] → 2 dimensions, 1 cluster each.
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
            SearchResult(uuid="ok", name="A", location="/Inbox", reference_url="x-d://ok"),
            SearchResult(uuid="bad", name="B", location="/Inbox", reference_url="x-d://bad"),
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
            SearchResult(uuid="a", name="A", location="/Inbox", reference_url="x-d://a"),
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
```

- [ ] **Step 5.3: Run tests**

```bash
uv run pytest tests/unit/test_summarize_topic.py -v
```

Expected: 15 tests pass total (5 from Task 3 + 6 from Task 4 + 4 new).

- [ ] **Step 5.4: Commit**

```bash
git add apps/server/src/istefox_dt_mcp_server/tools/summarize_topic.py tests/unit/test_summarize_topic.py
git commit -m "feat(summarize_topic): add hydration + score synthesis + summarize_topic_op

Top-level async operation that retrieves (vector if RAG enabled, BM25
fallback), hydrates records in parallel via asyncio.gather, synthesizes
rank-based scores for BM25 hits, and dispatches to the per-dimension
clustering helpers.

Failed hydrations are skipped with a debug log. Empty retrieval
returns empty clusters with total_records_retrieved=0. CLUSTERER_BY_DIMENSION
dispatch table maps dimension strings to helper functions.

4 new unit tests covering BM25 path, hydration failure handling,
empty retrieval, cluster_by parameter override."
```

---

### Task 6: Tool registration with MCP

**Files:**
- Modify: `apps/server/src/istefox_dt_mcp_server/tools/summarize_topic.py` (add `register` function at the bottom)
- Modify: `apps/server/src/istefox_dt_mcp_server/server.py` (call `tool_summarize_topic.register`)

- [ ] **Step 6.1: Append `register` to `summarize_topic.py`**

Append at the end of the module (after `summarize_topic_op`):

```python
def register(mcp: FastMCP, deps: Deps) -> None:
    """Wire the summarize_topic MCP tool to the FastMCP server."""
    from ._common import safe_call

    @mcp.tool()
    async def summarize_topic(  # noqa: A001 — name matches MCP tool spec
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
```

- [ ] **Step 6.2: Register the tool in `server.py`**

Open `apps/server/src/istefox_dt_mcp_server/server.py`. Find the imports block where the existing tools are imported. Add:

```python
from .tools import summarize_topic as tool_summarize_topic
```

Then in the `build_server` function, find the existing `tool_*.register(mcp, deps)` calls (there are 6 of them — one per tool). Add the new line after `tool_bulk_apply.register(mcp, deps)`:

```python
    tool_summarize_topic.register(mcp, deps)
```

Verify with grep:

```bash
grep -n "register(mcp, deps)" apps/server/src/istefox_dt_mcp_server/server.py
```

Expected: 7 matches (6 existing + 1 new for summarize_topic).

- [ ] **Step 6.3: Smoke test that the server starts and tools/list includes summarize_topic**

```bash
uv run python -c "
from istefox_dt_mcp_server.server import build_server
mcp = build_server()
tool_names = [t.name for t in mcp.list_tools_sync() if hasattr(mcp, 'list_tools_sync')] if hasattr(mcp, 'list_tools_sync') else None
# Fallback: introspect via private API
if tool_names is None:
    import asyncio
    tools = asyncio.run(mcp.get_tools())
    tool_names = list(tools.keys())
print(tool_names)
assert 'summarize_topic' in tool_names, tool_names
print('ok')
"
```

Expected: prints a list including `summarize_topic`, then `ok`. (FastMCP API may vary — if the introspection helper fails, fall back to `grep summarize_topic apps/server/src/istefox_dt_mcp_server/server.py` to verify the registration line is there.)

- [ ] **Step 6.4: Run the full test suite to verify no regressions**

```bash
uv run pytest -q
```

Expected: 175+15 = ~190 tests pass.

- [ ] **Step 6.5: Lint + type check**

```bash
uv run ruff check apps/server/src/istefox_dt_mcp_server/tools/summarize_topic.py apps/server/src/istefox_dt_mcp_server/server.py tests/unit/test_summarize_topic.py
uv run black --check apps/server/src/istefox_dt_mcp_server/tools/summarize_topic.py tests/unit/test_summarize_topic.py
uv run mypy apps/server/src/istefox_dt_mcp_server/tools/summarize_topic.py
```

Expected: zero issues. If black/ruff want reformatting, run without `--check` to fix in place.

- [ ] **Step 6.6: Commit**

```bash
git add apps/server/src/istefox_dt_mcp_server/tools/summarize_topic.py apps/server/src/istefox_dt_mcp_server/server.py
git commit -m "feat(server): register summarize_topic MCP tool

Wires summarize_topic into FastMCP via the standard register(mcp, deps)
pattern. Tool dispatches through safe_call for audit logging + uniform
error envelope.

Tools list grows to 7: list_databases, search, find_related,
ask_database, file_document, bulk_apply, summarize_topic."
```

---

### Task 7: Update ADR-0004 + CHANGELOG + README

**Files:**
- Modify: `docs/adr/0004-mvp-tool-scope.md` (add note)
- Modify: `CHANGELOG.md` (entry under `[Unreleased]`)
- Modify: `README.md` ("What you can ask Claude" section)

- [ ] **Step 7.1: Add note to ADR-0004**

Open `docs/adr/0004-mvp-tool-scope.md`. Find the "Esclusi da v1" table. Below it, append a new section:

```markdown
## Reconsiderations after v1

### `summarize_topic` — included in 0.2.0

The original v1 exclusion rationale ("replicable client-side via `ask_database`
+ prompt template") is reconsidered for 0.2.0. Server-side clustering produces
a *structured shape* (`Cluster[]` with `dimension` / `label` / `count` / `records`)
that the client can rely on without doing the grouping itself. The capability
is structural, not just a wrapper.

See [the design spec](../superpowers/specs/2026-05-03-summarize-topic-design.md)
for the algorithm and constraints. `summarize_topic` is read-only, reuses the
existing retrieval layer, adds no new infrastructure.

`bulk_apply` was already moved into v1 during the first reconsideration round
(0.0.x series). `create_smart_rule` remains deferred; reconsidered separately
for 0.2.0+.
```

- [ ] **Step 7.2: Add CHANGELOG entry**

In `CHANGELOG.md`, find the `## [Unreleased]` heading. Add this block under it (alongside any existing `### Added` subsection — if `### Added` already exists for drift detection 3-state, place this as a **separate** `### Added (summarize_topic)` block to keep the two features visually distinct):

```markdown
### Added (summarize_topic)

- New read-only MCP tool **`summarize_topic`** that retrieves records related
  to a topic and groups them server-side by user-selected dimensions:
  `date`, `tags`, `kind`, `location`. Default `cluster_by = ["date", "tags"]`.
- Adaptive date granularity: year-only labels for ranges > 24 months, year-month
  otherwise. Reverse-chronological cluster ordering.
- Bounded output (configurable): default 50 records retrieved, 10 clusters per
  dimension, 10 records per cluster. All bounds adjustable via `max_records`,
  `max_clusters`, `max_per_cluster`.
- Retrieval reuses the `ask_database` path: vector if `ISTEFOX_RAG_ENABLED=1`,
  BM25 fallback otherwise. BM25 mode synthesizes rank-based scores so within-
  cluster ordering remains meaningful.
- Empty clusters are omitted from the response (no `count: 0` placeholder).
- See [`docs/superpowers/specs/2026-05-03-summarize-topic-design.md`](docs/superpowers/specs/2026-05-03-summarize-topic-design.md)
  for the full design.

### Changed

- ADR-0004 updated with a "Reconsiderations after v1" section noting the
  inclusion of `summarize_topic` in 0.2.0.
```

- [ ] **Step 7.3: Update README "What you can ask Claude" section**

Open `README.md`. Find the existing examples list under "What you can ask Claude". Add this bullet at the end of the list (before the closing prose paragraph):

```markdown
- *"Dammi una panoramica di tutte le bollette del 2025 raggruppate per mese e tag"*
  → `summarize_topic` (retrieval + server-side clustering by date and tags)
```

- [ ] **Step 7.4: Sanity-check the diff**

```bash
git diff docs/adr/0004-mvp-tool-scope.md CHANGELOG.md README.md
```

Read the diff. Confirm: ADR has new section appended, CHANGELOG has new entry, README has new example bullet.

- [ ] **Step 7.5: Commit**

```bash
git add docs/adr/0004-mvp-tool-scope.md CHANGELOG.md README.md
git commit -m "docs: document summarize_topic in CHANGELOG, README, ADR-0004

- ADR-0004: new section reconsidering summarize_topic exclusion for 0.2.0
- CHANGELOG: new [Unreleased] entry covering tool semantics, limits, and
  the retrieval mode switch (vector with BM25 fallback)
- README: example added to 'What you can ask Claude'"
```

---

### Task 8: Push, open PR, verify CI

**Files:**
- No file changes — git + GitHub flow only.

- [ ] **Step 8.1: Push**

```bash
git push -u origin feat/summarize-topic
```

- [ ] **Step 8.2: Open PR**

```bash
gh pr create --title "feat(tools): summarize_topic — server-side clustering retrieval (0.2.0)" --body "$(cat <<'EOF'
## Summary

Adds a new read-only MCP tool \`summarize_topic\` that retrieves records related to a topic and groups them server-side by user-selected dimensions (\`date\`, \`tags\`, \`kind\`, \`location\`). Default clustering is \`["date", "tags"]\`.

This supersedes the ADR-0004 v1 exclusion of \`summarize_topic\`. Updated rationale: server-side clustering is a *structural* capability, not a client-replicable wrapper.

## Spec + plan

Both committed in this PR:
- \`docs/superpowers/specs/2026-05-03-summarize-topic-design.md\` — approved 2026-05-03
- \`docs/superpowers/plans/2026-05-03-summarize-topic.md\` — TDD step-by-step

## Behavior

| Aspect | Default | Configurable |
|---|---|---|
| Retrieval | vector if \`ISTEFOX_RAG_ENABLED=1\`, BM25 fallback otherwise | env-driven, no input change |
| Cluster dimensions | \`["date", "tags"]\` | yes, any subset of \`{date, tags, kind, location}\` |
| Max records retrieved | 50 | 1-200 |
| Max clusters per dimension | 10 | 1-50 |
| Max records per cluster | 10 | 1-50 |
| Date granularity | adaptive (year if >24mo span, year-month otherwise) | no |
| Empty clusters | omitted | no |

## Test plan

- [x] 15 unit tests covering each clustering helper (date, tags, kind, location), the score synthesizer, and the top-level operation with mocked deps
- [x] All existing tests continue to pass
- [x] \`uv run pytest -q\`, \`uv run ruff check\`, \`uv run black --check\`, \`uv run mypy\` all clean

## Compatibility notes

- New tool, no schema changes to existing tools.
- Tools list grows from 6 to 7 — clients introspecting via \`tools/list\` see the new one.
- No new dependencies, no new env vars.

## Out of scope (followups)

- Server-side LLM-generated summaries (rejected per spec §3 — keeps connector stateless).
- Custom dimensions beyond the four built-in (could add a \`cluster_by\` extension API in 0.3.0+).
- Per-cluster snippet enrichment (currently snippets are empty strings; could call \`get_record_text\` if useful, but that doubles JXA calls).

## Out of scope but adjacent

\`create_smart_rule\` is the next item on the 0.2.0 roadmap. Brainstorming continues separately.
EOF
)"
```

- [ ] **Step 8.3: Watch CI**

```bash
gh pr checks --watch --interval 15
```

Expected: \`lint-and-test\`, \`mypy\`, and the macOS workflow (if it triggers on these paths) all pass within 1-3 minutes.

- [ ] **Step 8.4: Stop**

Do **not** auto-merge. The PR is ready for human review. The plan ends with the PR open and CI green.

---

## Notes for the executor

- Run from repo root: `/Users/stefanoferri/Developer/Devonthink_MCP`.
- Python 3.12 is required (`uv run` should pick it up automatically).
- If `uv run pytest` cannot import `istefox_dt_mcp_schemas` or `istefox_dt_mcp_server`, run `uv sync --all-packages` once.
- Conventional Commits in English. NO `Co-Authored-By: Claude` trailer in any commit.
- This plan is ~300 LoC additive. If you find a fix that drifts off-scope (e.g. wanting to also extend `find_related` with a similar clustering pattern), open a separate issue/PR — do not bundle.
- The existing `Citation` schema is reused as-is. The Cluster `records` field is `list[Citation]` with empty `snippet`. If snippet enrichment ever becomes desired, that's a follow-up — not this PR.
- Tests use `_record()` helper local to `test_summarize_topic.py` (intentionally private to that file — there are similar helpers in `test_undo.py`, kept independent for module isolation).
