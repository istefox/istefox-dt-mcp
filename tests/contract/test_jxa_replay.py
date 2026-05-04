"""VCR-style replay tests for the JXA adapter.

Cassettes capture (script_name, argv, stdout) tuples that a real
DEVONthink instance would emit. Each test patches
`asyncio.create_subprocess_exec` to feed the cassette's stdout to the
adapter and asserts the parsed Pydantic model matches expectations.

This validates the bridge contract: if DT changes its JXA output shape
in a future release, the cassette diverges and the test fails loudly
instead of silently corrupting downstream tools.

Cassette format (JSON):
    {
      "script": "<script_name>.js",
      "argv": ["..."],
      "stdout": "<raw JSON string DT would return>"
    }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from istefox_dt_mcp_adapter.jxa import JXAAdapter
from istefox_dt_mcp_schemas.common import (
    Database,
    MoveResult,
    Record,
    RelatedResult,
    SearchResult,
    TagResult,
    WriteOutcome,
)

CASSETTES_DIR = Path(__file__).parent / "cassettes"

pytestmark = pytest.mark.contract


def _mock_proc(
    *, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0
) -> AsyncMock:
    """Build an AsyncMock subprocess matching the unit-test pattern."""
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    proc.kill = AsyncMock()
    return proc


def _load_cassette(name: str) -> dict[str, Any]:
    """Load a cassette JSON file by basename (without .json suffix)."""
    path = CASSETTES_DIR / f"{name}.json"
    with path.open(encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)
    return data


def _stdout_bytes(cassette: dict[str, Any]) -> bytes:
    """Encode the cassette's stdout payload as bytes for the mock pipe."""
    payload: str = cassette["stdout"]
    return (payload + "\n").encode("utf-8")


@pytest.mark.asyncio
async def test_replay_list_databases() -> None:
    """list_databases.js -> list[Database] with 2 open databases."""
    cassette = _load_cassette("list_databases")
    adapter = JXAAdapter(pool_size=1, timeout_s=2.0, max_retries=1, cache=None)

    with patch(
        "asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=_mock_proc(stdout=_stdout_bytes(cassette))),
    ):
        result = await adapter.list_databases()

    assert len(result) == 2
    assert all(isinstance(db, Database) for db in result)
    assert result[0].name == "Inbox"
    assert result[0].is_open is True
    assert result[0].record_count == 42
    assert result[1].name == "privato"
    assert result[1].record_count == 3187


@pytest.mark.asyncio
async def test_replay_get_record() -> None:
    """get_record.js -> Record with all standard fields populated."""
    cassette = _load_cassette("get_record")
    adapter = JXAAdapter(pool_size=1, timeout_s=2.0, max_retries=1, cache=None)
    uuid = cassette["argv"][0]

    with patch(
        "asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=_mock_proc(stdout=_stdout_bytes(cassette))),
    ):
        result = await adapter.get_record(uuid)

    assert isinstance(result, Record)
    assert result.uuid == uuid
    assert result.name == "Fattura 2026-001 ACME Srl"
    assert result.kind == "PDF"
    assert result.location == "/privato/fatture/2026/"
    assert result.path is not None
    assert result.reference_url.startswith("x-devonthink-item://")
    assert result.tags == ["fattura", "2026", "acme"]
    assert result.size_bytes == 284512
    assert result.word_count == 421


@pytest.mark.asyncio
async def test_replay_search_bm25() -> None:
    """search_bm25.js -> list[SearchResult] with 3 hits."""
    cassette = _load_cassette("search_bm25")
    adapter = JXAAdapter(pool_size=1, timeout_s=2.0, max_retries=1, cache=None)

    with patch(
        "asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=_mock_proc(stdout=_stdout_bytes(cassette))),
    ):
        result = await adapter.search("antivibranti", max_results=10)

    assert len(result) == 3
    assert all(isinstance(hit, SearchResult) for hit in result)
    assert result[0].name == "Catalogo antivibranti 2026"
    assert result[0].score == 0.91
    assert result[0].snippet is None
    # Scores must be monotonically non-increasing in this cassette
    scores = [hit.score for hit in result if hit.score is not None]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_replay_find_related() -> None:
    """find_related.js -> list[RelatedResult] with 3 similar records."""
    cassette = _load_cassette("find_related")
    adapter = JXAAdapter(pool_size=1, timeout_s=2.0, max_retries=1, cache=None)
    seed_uuid = cassette["argv"][0]

    with patch(
        "asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=_mock_proc(stdout=_stdout_bytes(cassette))),
    ):
        result = await adapter.find_related(seed_uuid, k=10)

    assert len(result) == 3
    assert all(isinstance(rel, RelatedResult) for rel in result)
    assert result[0].name == "Documento simile A"
    assert result[0].similarity == 0.87
    # Seed must never appear in related results (defense in depth)
    assert all(rel.uuid != seed_uuid for rel in result)


@pytest.mark.asyncio
async def test_replay_apply_tag() -> None:
    """apply_tag flow: get_record (tags_before) + apply_tag.js -> TagResult.

    The adapter calls get_record first to capture tags_before, then
    runs apply_tag.js. With dry_run=False both subprocesses fire.
    """
    cassette = _load_cassette("apply_tag")
    adapter = JXAAdapter(pool_size=1, timeout_s=2.0, max_retries=1, cache=None)
    uuid = cassette["argv"][0]
    tag = cassette["argv"][1]

    # Synthesize a get_record stdout consistent with the apply_tag
    # cassette: tags_before is everything in tags_after minus the new tag.
    tags_after_payload = json.loads(cassette["stdout"])["tags_after"]
    tags_before = [t for t in tags_after_payload if t != tag]
    record_stdout = (
        json.dumps(
            {
                "uuid": uuid,
                "name": "Fattura 2026-001 ACME Srl",
                "kind": "PDF",
                "location": "/privato/fatture/2026/",
                "path": None,
                "reference_url": f"x-devonthink-item://{uuid}",
                "creation_date": "2026-01-15T09:32:11.000Z",
                "modification_date": "2026-01-15T09:33:02.000Z",
                "tags": tags_before,
                "size_bytes": None,
                "word_count": None,
            }
        ).encode("utf-8")
        + b"\n"
    )

    procs = [
        _mock_proc(stdout=record_stdout),
        _mock_proc(stdout=_stdout_bytes(cassette)),
    ]

    async def factory(*_args: object, **_kwargs: object) -> AsyncMock:
        return procs.pop(0)

    with patch("asyncio.create_subprocess_exec", new=factory):
        result = await adapter.apply_tag(uuid, tag, dry_run=False)

    assert isinstance(result, TagResult)
    assert result.uuid == uuid
    assert result.outcome is WriteOutcome.APPLIED
    assert result.tags_before == tags_before
    assert result.tags_after == tags_after_payload
    assert tag in result.tags_after


@pytest.mark.asyncio
async def test_replay_move_record() -> None:
    """move_record flow: get_record (location_before) + move_record.js -> MoveResult."""
    cassette = _load_cassette("move_record")
    adapter = JXAAdapter(pool_size=1, timeout_s=2.0, max_retries=1, cache=None)
    uuid = cassette["argv"][0]
    dest = cassette["argv"][1]

    location_before = "/privato/inbox/"
    location_after = json.loads(cassette["stdout"])["location"]

    record_stdout = (
        json.dumps(
            {
                "uuid": uuid,
                "name": "Documento da archiviare",
                "kind": "PDF",
                "location": location_before,
                "path": None,
                "reference_url": f"x-devonthink-item://{uuid}",
                "creation_date": "2026-01-10T08:00:00.000Z",
                "modification_date": "2026-01-10T08:00:00.000Z",
                "tags": [],
                "size_bytes": None,
                "word_count": None,
            }
        ).encode("utf-8")
        + b"\n"
    )

    procs = [
        _mock_proc(stdout=record_stdout),
        _mock_proc(stdout=_stdout_bytes(cassette)),
    ]

    async def factory(*_args: object, **_kwargs: object) -> AsyncMock:
        return procs.pop(0)

    with patch("asyncio.create_subprocess_exec", new=factory):
        result = await adapter.move_record(uuid, dest, dry_run=False)

    assert isinstance(result, MoveResult)
    assert result.uuid == uuid
    assert result.outcome is WriteOutcome.APPLIED
    assert result.location_before == location_before
    assert result.location_after == location_after


# ----------------------------------------------------------------------
# Sanity invariant: cassettes pass sanitization rules
# ----------------------------------------------------------------------


def test_cassettes_have_no_personal_filesystem_paths() -> None:
    """No cassette in tests/contract/cassettes/ leaks /Users/<realname>/."""
    import re

    pattern = re.compile(r"/Users/([^/\"']+)/")
    for cassette_file in CASSETTES_DIR.glob("*.json"):
        text = cassette_file.read_text(encoding="utf-8")
        matches = pattern.findall(text)
        # The only acceptable username in committed cassettes is "fixture".
        leaks = [m for m in matches if m != "fixture"]
        assert not leaks, (
            f"Cassette {cassette_file.name} contains personal paths: "
            f"/Users/{leaks[0]}/... — re-record with sanitization enabled."
        )


def test_cassettes_have_no_unknown_placeholders() -> None:
    """No cassette contains <UNKNOWN_NAME_n> or <UNKNOWN_PATH_n> markers."""
    for cassette_file in CASSETTES_DIR.glob("*.json"):
        text = cassette_file.read_text(encoding="utf-8")
        assert "<UNKNOWN_NAME_" not in text, (
            f"Cassette {cassette_file.name} has unknown record names — "
            f"likely recorded against the wrong DB."
        )
        assert "<UNKNOWN_PATH_" not in text, (
            f"Cassette {cassette_file.name} has unknown paths — "
            f"likely recorded against the wrong DB."
        )
