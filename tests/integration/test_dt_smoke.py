"""Tier 3 smoke tests against a real DEVONthink 4.

One test per primary tool; assertions are tolerance-based (no
hard-coded UUIDs, names, or counts) so the suite passes against any
user database with at least a handful of records.

Skipped by default. Run with:

    uv run pytest tests/integration -m integration -v

Requires DEVONthink 4 running with at least one open database.
"""

from __future__ import annotations

import pytest
from istefox_dt_mcp_adapter.jxa import JXAAdapter
from istefox_dt_mcp_schemas.common import (
    ClassifySuggestion,
    Database,
    Record,
    RelatedResult,
    SearchResult,
    TagResult,
    WriteOutcome,
)

# Module-level marker: every test in this file is an integration test.
# Combined with `-m "not integration"` in addopts, default sessions
# skip these without requiring per-test decorators.
pytestmark = pytest.mark.integration


# A deliberately broad query that will match content in virtually any
# multilingual DB. Using a lowercased English stopword keeps the test
# meaningful even on small DBs without favoring any specific user.
_BROAD_QUERY = "the"


async def test_list_databases_returns_at_least_one(
    real_adapter: JXAAdapter,
) -> None:
    """Bridge can enumerate databases."""
    databases = await real_adapter.list_databases()
    assert isinstance(databases, list)
    assert len(databases) >= 1
    assert all(isinstance(db, Database) for db in databases)
    # At least one DB must be open — our fixtures rely on that.
    assert any(db.is_open for db in databases)


async def test_search_for_known_term_returns_results(
    real_adapter: JXAAdapter,
    first_open_database: str,
) -> None:
    """A broad query returns at least one structurally-valid hit."""
    results = await real_adapter.search(
        _BROAD_QUERY,
        databases=[first_open_database],
        max_results=5,
    )
    assert isinstance(results, list)
    # Tolerance: tiny / empty DBs may legitimately return zero hits;
    # skip rather than fail to keep the suite robust.
    if not results:
        pytest.skip(
            f"DB '{first_open_database}' has no hits for '{_BROAD_QUERY}' — "
            "open a DB with more content and retry"
        )
    assert len(results) <= 5
    assert all(isinstance(r, SearchResult) for r in results)
    for hit in results:
        assert hit.uuid
        assert hit.name
        assert hit.reference_url.startswith("x-devonthink-item://")


async def test_find_related_on_first_search_result_works(
    real_adapter: JXAAdapter,
    first_open_database: str,
) -> None:
    """Chain: search -> take uuid -> find_related."""
    hits = await real_adapter.search(
        _BROAD_QUERY,
        databases=[first_open_database],
        max_results=5,
    )
    if not hits:
        pytest.skip(f"No search hits in '{first_open_database}' to seed find_related")

    seed_uuid = hits[0].uuid
    related = await real_adapter.find_related(seed_uuid, k=5)
    assert isinstance(related, list)
    assert len(related) <= 5
    assert all(isinstance(r, RelatedResult) for r in related)
    # Seed must never be echoed back as related to itself.
    assert all(r.uuid != seed_uuid for r in related)


async def test_get_record_round_trip(
    real_adapter: JXAAdapter,
    first_open_database: str,
) -> None:
    """Chain: search -> take uuid -> get_record -> assert match."""
    hits = await real_adapter.search(
        _BROAD_QUERY,
        databases=[first_open_database],
        max_results=5,
    )
    if not hits:
        pytest.skip(f"No search hits in '{first_open_database}' to seed get_record")

    seed = hits[0]
    record = await real_adapter.get_record(seed.uuid)
    assert isinstance(record, Record)
    assert record.uuid == seed.uuid
    assert record.name == seed.name
    assert record.reference_url == seed.reference_url
    # Record kind comes from DT's enum or unknown fallback; either
    # way it must be a non-empty string after coercion.
    assert str(record.kind)


async def test_classify_record_returns_suggestions(
    real_adapter: JXAAdapter,
    first_open_database: str,
) -> None:
    """Chain: search -> take uuid -> classify_record."""
    hits = await real_adapter.search(
        _BROAD_QUERY,
        databases=[first_open_database],
        max_results=5,
    )
    if not hits:
        pytest.skip(f"No search hits in '{first_open_database}' to seed classify")

    suggestions = await real_adapter.classify_record(hits[0].uuid, top_n=3)
    # DT may return zero suggestions for short/atypical records; the
    # contract is "list of ClassifySuggestion (possibly empty)".
    assert isinstance(suggestions, list)
    assert len(suggestions) <= 3
    assert all(isinstance(s, ClassifySuggestion) for s in suggestions)
    for sug in suggestions:
        assert sug.location  # non-empty path-like string


async def test_dry_run_apply_tag_does_not_mutate(
    real_adapter: JXAAdapter,
    first_open_database: str,
) -> None:
    """apply_tag(dry_run=True) returns PREVIEWED and never mutates DT.

    We pick a tag string unlikely to be already present on the
    record, so the path exercised is "would add" not NOOP.
    """
    hits = await real_adapter.search(
        _BROAD_QUERY,
        databases=[first_open_database],
        max_results=5,
    )
    if not hits:
        pytest.skip(f"No search hits in '{first_open_database}' to seed apply_tag")

    seed_uuid = hits[0].uuid
    record_before = await real_adapter.get_record(seed_uuid)
    tags_before_snapshot = sorted(record_before.tags)

    probe_tag = "istefox-dt-mcp-integration-probe"
    # Defensive: if the tag somehow already exists (previous broken
    # run), skip rather than risk a misleading NOOP assertion.
    if probe_tag in record_before.tags:
        pytest.skip(f"Probe tag already present on {seed_uuid} — manual cleanup needed")

    result = await real_adapter.apply_tag(seed_uuid, probe_tag, dry_run=True)
    assert isinstance(result, TagResult)
    assert result.uuid == seed_uuid
    assert result.outcome == WriteOutcome.PREVIEWED
    assert probe_tag not in result.tags_before
    assert probe_tag in result.tags_after

    # Re-read the record from DT and confirm no mutation actually
    # happened — this is the core dry-run guarantee.
    record_after = await real_adapter.get_record(seed_uuid)
    assert sorted(record_after.tags) == tags_before_snapshot
    assert probe_tag not in record_after.tags
