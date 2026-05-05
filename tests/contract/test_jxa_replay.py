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


_FIXTURE_REC_UUID = "FIXTURE-REC-0001-AAAA-AAAAAAAAAAAA"


def _bytes(payload: dict[str, Any] | list[Any]) -> bytes:
    """Encode a JSON-serializable payload as bytes for the mock pipe."""
    return (json.dumps(payload) + "\n").encode("utf-8")


@pytest.mark.asyncio
async def test_replay_list_databases() -> None:
    """list_databases.js -> 2 Databases (fixtures-dt-mcp + system Inbox)."""
    cassette = _load_cassette("list_databases")
    adapter = JXAAdapter(pool_size=1, timeout_s=2.0, max_retries=1, cache=None)

    with patch(
        "asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=_mock_proc(stdout=_stdout_bytes(cassette))),
    ):
        result = await adapter.list_databases()

    assert len(result) == 2
    assert all(isinstance(db, Database) for db in result)
    by_name = {db.name: db for db in result}
    assert "fixtures-dt-mcp" in by_name
    assert "Inbox" in by_name
    fixtures_db = by_name["fixtures-dt-mcp"]
    assert fixtures_db.is_open is True
    assert fixtures_db.record_count == 10
    # System Inbox count varies by Stefano's actual usage; just sanity-check.
    assert by_name["Inbox"].is_open is True
    assert by_name["Inbox"].record_count >= 0


@pytest.mark.asyncio
async def test_replay_get_record() -> None:
    """get_record.js -> Record for the FIXTURE-REC-0001 PDF."""
    cassette = _load_cassette("get_record")
    adapter = JXAAdapter(pool_size=1, timeout_s=2.0, max_retries=1, cache=None)
    uuid = cassette["argv"][0]

    with patch(
        "asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=_mock_proc(stdout=_stdout_bytes(cassette))),
    ):
        result = await adapter.get_record(uuid)

    assert isinstance(result, Record)
    assert result.uuid == _FIXTURE_REC_UUID
    assert result.name == "Sample PDF Invoice 2025"
    # DT4 returns the create-side type token "PDF document" (vs DT3's "PDF").
    assert result.kind == "PDF document"
    assert result.location == "/Inbox/"
    assert result.reference_url == f"x-devonthink-item://{_FIXTURE_REC_UUID}"
    assert "invoices" in result.tags
    assert "2025" in result.tags
    # path is the .dtBase2-internal filesystem path; sanitized to the
    # placeholder because the per-machine UUID can't be deterministically
    # mapped. The Pydantic model still accepts the placeholder string.
    assert result.path is not None


@pytest.mark.asyncio
async def test_replay_search_bm25() -> None:
    """search_bm25.js -> 10 SearchResults, one per fixture record."""
    cassette = _load_cassette("search_bm25")
    adapter = JXAAdapter(pool_size=1, timeout_s=2.0, max_retries=1, cache=None)

    with patch(
        "asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=_mock_proc(stdout=_stdout_bytes(cassette))),
    ):
        result = await adapter.search("Sample", databases=["fixtures-dt-mcp"])

    assert len(result) == 10
    assert all(isinstance(hit, SearchResult) for hit in result)
    # All hits are FIXTURE placeholders (sanitization invariant).
    assert all(hit.uuid.startswith("FIXTURE-REC-") for hit in result)
    # The first hit is REC-0001 in this capture; the underlying score
    # ordering is BM25-driven and not strictly monotonic against capture
    # order, so we only validate the leading record + score bounds.
    assert result[0].uuid == _FIXTURE_REC_UUID
    assert result[0].name == "Sample PDF Invoice 2025"
    for hit in result:
        assert hit.score is not None
        assert 0.0 <= hit.score <= 1.0


@pytest.mark.asyncio
async def test_replay_find_related() -> None:
    """find_related.js -> empty list.

    The fixture records are placeholders without indexable content, so
    DEVONthink's compare() returns no matches. The cassette therefore
    captures the empty-response shape — still a valuable contract test
    because it exercises the JSON parsing path for `[]`.
    """
    cassette = _load_cassette("find_related")
    adapter = JXAAdapter(pool_size=1, timeout_s=2.0, max_retries=1, cache=None)
    seed_uuid = cassette["argv"][0]

    with patch(
        "asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=_mock_proc(stdout=_stdout_bytes(cassette))),
    ):
        result = await adapter.find_related(seed_uuid, k=10)

    assert result == []


@pytest.mark.asyncio
async def test_replay_apply_tag() -> None:
    """apply_tag flow: get_record (tags_before) + apply_tag.js -> TagResult.

    Cassette contents: the captured stdout is the FIRST JXA call
    (get_record), since `_RecorderShim` records only the first call. We
    replay the cassette as call #1 and synthesize call #2 (apply_tag.js
    response shape: {uuid, tags_after}).
    """
    cassette = _load_cassette("apply_tag")
    adapter = JXAAdapter(pool_size=1, timeout_s=2.0, max_retries=1, cache=None)
    record_payload = json.loads(cassette["stdout"])
    uuid = record_payload["uuid"]
    tags_before = list(record_payload["tags"])
    new_tag = "review"
    assert new_tag not in tags_before, (
        "Cassette captured a state already carrying the 'review' tag — "
        "the recorder needs reset_to_manifest_state to run before --all."
    )
    tags_after = [*tags_before, new_tag]

    procs = [
        _mock_proc(stdout=_stdout_bytes(cassette)),
        _mock_proc(stdout=_bytes({"uuid": uuid, "tags_after": tags_after})),
    ]

    async def factory(*_args: object, **_kwargs: object) -> AsyncMock:
        return procs.pop(0)

    with patch("asyncio.create_subprocess_exec", new=factory):
        result = await adapter.apply_tag(uuid, new_tag, dry_run=False)

    assert isinstance(result, TagResult)
    assert result.uuid == uuid
    assert result.outcome is WriteOutcome.APPLIED
    assert result.tags_before == tags_before
    assert result.tags_after == tags_after


@pytest.mark.asyncio
async def test_replay_move_record() -> None:
    """move_record flow: get_record (location_before) + move_record.js -> MoveResult.

    Same shim semantics as apply_tag: the cassette is the get_record
    payload (call #1); we synthesize the move_record.js response (call
    #2) with the destination location.
    """
    cassette = _load_cassette("move_record")
    adapter = JXAAdapter(pool_size=1, timeout_s=2.0, max_retries=1, cache=None)
    record_payload = json.loads(cassette["stdout"])
    uuid = record_payload["uuid"]
    location_before = record_payload["location"]
    dest_path = "fixtures-dt-mcp/Archive"
    location_after = "/Archive/"

    procs = [
        _mock_proc(stdout=_stdout_bytes(cassette)),
        _mock_proc(stdout=_bytes({"uuid": uuid, "location": location_after})),
    ]

    async def factory(*_args: object, **_kwargs: object) -> AsyncMock:
        return procs.pop(0)

    with patch("asyncio.create_subprocess_exec", new=factory):
        result = await adapter.move_record(uuid, dest_path, dry_run=False)

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
    """No cassette contains <UNKNOWN_NAME_n> markers anywhere, and
    <UNKNOWN_PATH_n> only on Record.path (filesystem path inside the
    .dtBase2 bundle, e.g. /Files.noindex/<machine-uuid>.pdf — which is
    machine-specific and cannot be deterministically mapped to a manifest
    placeholder; it is safe but non-stable).
    """

    def _walk(node: Any, parent_key: str | None = None) -> list[tuple[str, str]]:
        """Return a list of (key, placeholder) tuples for any UNKNOWN_*
        marker found in ``node``. ``parent_key`` is the dict key under
        which ``node`` lives, or None for top-level/list elements.
        """
        out: list[tuple[str, str]] = []
        if isinstance(node, dict):
            for k, v in node.items():
                out.extend(_walk(v, parent_key=k))
        elif isinstance(node, list):
            for item in node:
                out.extend(_walk(item, parent_key=parent_key))
        elif isinstance(node, str) and (
            "<UNKNOWN_NAME_" in node or "<UNKNOWN_PATH_" in node
        ):
            out.append((parent_key or "<root>", node))
        return out

    for cassette_file in CASSETTES_DIR.glob("*.json"):
        cassette = json.loads(cassette_file.read_text(encoding="utf-8"))
        # The captured stdout is itself a JSON-encoded string (DT JXA
        # output). Parse it so we can match keys structurally.
        try:
            stdout_parsed = json.loads(cassette.get("stdout", "null"))
        except json.JSONDecodeError:
            stdout_parsed = None

        markers = _walk(stdout_parsed)
        for key, value in markers:
            if "<UNKNOWN_NAME_" in value:
                raise AssertionError(
                    f"Cassette {cassette_file.name} has <UNKNOWN_NAME_*> "
                    f"under key {key!r} — likely recorded against the "
                    "wrong DB."
                )
            # <UNKNOWN_PATH_*> is allowed only as the value of a `path`
            # key on a Record (the .dtBase2 internal filesystem path).
            if "<UNKNOWN_PATH_" in value and key != "path":
                raise AssertionError(
                    f"Cassette {cassette_file.name} has <UNKNOWN_PATH_*> "
                    f"under key {key!r} (only `path` is allowed) — "
                    "likely recorded against the wrong DB."
                )
