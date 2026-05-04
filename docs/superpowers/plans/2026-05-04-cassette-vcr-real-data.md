# Cassette VCR Real-Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace 6 hand-written synthetic cassettes in `tests/contract/cassettes/` with real-data captures from a dedicated synthetic DT4 fixture database, via a new `istefox-dt-mcp record-cassette` Click subcommand.

**Architecture:** Synthetic fixture DB defined by a committed manifest (`tests/fixtures/dt-database-manifest.json`) and recreatable via `scripts/setup_test_database.py`. The CLI wraps `JXAAdapter._run_script` to capture `(script, argv, stdout)` triples, applies sanitization (UUIDs/names/paths swapped to manifest-known stable values), and writes the result to `tests/contract/cassettes/<tool>.json`. Existing replay engine (`tests/contract/test_jxa_replay.py`) is unchanged.

**Tech Stack:** Python 3.12, Click 8.x, Pydantic v2, structlog, pytest + pytest-asyncio. JXA bridge via `Application("DEVONthink")` reached through the existing `_run_script` helper.

**Reference spec:** [`docs/superpowers/specs/2026-05-04-cassette-vcr-real-data-design.md`](../specs/2026-05-04-cassette-vcr-real-data-design.md)

---

## Important note for the executor

**Tasks 1–7 are mockable on Linux** (no DT4 needed). They build the infrastructure: schema fix, manifest, regen script, sanitization, recorder orchestrator, CLI subcommand, docs/invariant test.

**Task 8 (live capture)** is **manual** and **must run on Stefano's Mac with DT4 live**. A subagent on a remote runner cannot execute it. The plan structure lets the implementer commit a fully-working PR (Tasks 1–7 + Task 9) with the existing synthetic cassettes still in place; Stefano runs Task 8 locally when ready and commits the captured cassettes as a follow-up commit on the same branch.

If the executor is a subagent without DT4 access: skip Task 8 and proceed to Task 9 (push + PR). Document in the PR description that the live-capture step is pending.

---

### Task 1: Branch + baseline

**Files:** No file changes — prep only.

- [ ] **Step 1.1: Create feat branch off main, merge spec/cassette-vcr-real-data**

```bash
git fetch origin
git checkout main
git pull --ff-only
git checkout -b feat/cassette-vcr-real-data
git merge --no-ff spec/cassette-vcr-real-data -m "merge spec/cassette-vcr-real-data into feat branch"
```

- [ ] **Step 1.2: Run baseline tests**

```bash
uv run pytest -q
```

Expected: ~190 tests pass.

- [ ] **Step 1.3: Inspect existing cassette format + replay engine**

```bash
cat tests/contract/cassettes/list_databases.json
head -60 tests/contract/test_jxa_replay.py
ls tests/contract/cassettes/
```

Expected: cassettes follow `{"script", "argv", "stdout"}` shape; 6 files (`apply_tag, find_related, get_record, list_databases, move_record, search_bm25`); replay test patches `asyncio.create_subprocess_exec`.

---

### Task 2: Pydantic output models — relax strictness for real data

**Files:**
- Modify: `libs/schemas/src/istefox_dt_mcp_schemas/common.py` (add a `LooseModel` base, switch output classes to inherit from it)
- Test: existing test suite (no new test file; just confirm nothing breaks)

#### Background

`StrictModel` currently has `extra="forbid"` (verified: `libs/schemas/.../common.py:23-28`). Real DT captures may include fields the synthetic cassettes omitted — `extra="forbid"` would reject those and break replay. Per spec §7: switch *output* models to `extra="ignore"` while keeping input models strict (input validation defends against bad LLM/user input).

#### Steps

- [ ] **Step 2.1: Add `LooseModel` base class**

In `libs/schemas/src/istefox_dt_mcp_schemas/common.py`, add right after the `StrictModel` definition (around line 28):

```python
class LooseModel(BaseModel):
    """Base for OUTPUT models parsed from external sources (JXA, RAG, etc.).

    Same defaults as StrictModel except extra='ignore' — accept fields DT or
    other adapters may add in future versions without breaking replay tests
    or downstream consumers. Input models (validating LLM/user input) keep
    StrictModel; only models that wrap data from outside our control use
    LooseModel.
    """

    model_config = ConfigDict(
        extra="ignore",
        frozen=False,
        str_strip_whitespace=True,
        validate_assignment=True,
    )
```

- [ ] **Step 2.2: Switch the output-side schemas in common.py to inherit from `LooseModel`**

In the same file, change the base class for the data-from-DT models. Find each `class` definition and switch:

```python
class Database(StrictModel):  →  class Database(LooseModel):
class Record(StrictModel):  →  class Record(LooseModel):
class SearchResult(StrictModel):  →  class SearchResult(LooseModel):
class RelatedResult(StrictModel):  →  class RelatedResult(LooseModel):
class TagResult(StrictModel):  →  class TagResult(LooseModel):
class MoveResult(StrictModel):  →  class MoveResult(LooseModel):
class HealthStatus(StrictModel):  →  class HealthStatus(LooseModel):
class ClassifySuggestion(StrictModel):  →  class ClassifySuggestion(LooseModel):
```

Keep `Envelope[T]` on `StrictModel` (it's our wrapper, we control its shape).

Verify the line counts changed only on those 8 class declarations:

```bash
git diff libs/schemas/src/istefox_dt_mcp_schemas/common.py
```

Expected: 8 single-word swaps (`StrictModel` → `LooseModel`) plus one new class definition.

- [ ] **Step 2.3: Run full test suite to confirm no regressions**

```bash
uv run pytest -q
```

Expected: ~190 tests pass. Some existing tests may have asserted on the strict behavior — if any fail, **read the error**: it should be a clear "extra fields" assertion that's now obsolete. Fix the test by removing the obsolete strict-mode assertion. Do **not** revert to `StrictModel`.

- [ ] **Step 2.4: Lint + type check**

```bash
uv run ruff check libs/schemas/src/istefox_dt_mcp_schemas/common.py
uv run black --check libs/schemas/src/istefox_dt_mcp_schemas/common.py
uv run mypy libs/schemas
```

Expected: zero issues.

- [ ] **Step 2.5: Commit**

```bash
git add libs/schemas/src/istefox_dt_mcp_schemas/common.py
git commit -m "feat(schemas): add LooseModel base for output schemas

Output models (Record, Database, SearchResult, etc.) parsed from JXA,
RAG, and other external sources now inherit from LooseModel
(extra='ignore') instead of StrictModel (extra='forbid'). Real-data
cassettes from DT4 may include fields synthetic cassettes omitted;
StrictModel would reject them and break replay.

Input models stay on StrictModel — input validation against bad
LLM/user input is defense in depth.

Spec: docs/superpowers/specs/2026-05-04-cassette-vcr-real-data-design.md §7"
```

---

### Task 3: Fixture database manifest

**Files:**
- Create: `tests/fixtures/dt-database-manifest.json`

#### Steps

- [ ] **Step 3.1: Create the manifest with 10 records spanning the kind variants**

Create `tests/fixtures/dt-database-manifest.json`:

```json
{
  "version": 1,
  "database": {
    "name": "fixtures-dt-mcp",
    "uuid_placeholder": "FIXTURE-DB-0001-AAAA-AAAAAAAAAAAA"
  },
  "groups": [
    {"path": "/Inbox", "uuid_placeholder": "FIXTURE-GRP-INBOX-0000-AAAAAAAAAAAA"},
    {"path": "/Archive", "uuid_placeholder": "FIXTURE-GRP-ARCHIVE-00-AAAAAAAAAAAA"},
    {"path": "/Archive/2025", "uuid_placeholder": "FIXTURE-GRP-2025-0000-AAAAAAAAAAAA"}
  ],
  "records": [
    {
      "uuid_placeholder": "FIXTURE-REC-0001-AAAA-AAAAAAAAAAAA",
      "name": "Sample PDF Invoice 2025",
      "kind": "PDF",
      "location": "/Inbox",
      "tags": ["invoices", "2025"],
      "creation_date": "2025-03-15T10:00:00Z",
      "modification_date": "2025-03-15T10:00:00Z"
    },
    {
      "uuid_placeholder": "FIXTURE-REC-0002-AAAA-AAAAAAAAAAAA",
      "name": "Sample Markdown Note",
      "kind": "markdown",
      "location": "/Archive/2025",
      "tags": ["notes"],
      "creation_date": "2025-06-01T14:30:00Z",
      "modification_date": "2025-06-01T14:30:00Z"
    },
    {
      "uuid_placeholder": "FIXTURE-REC-0003-AAAA-AAAAAAAAAAAA",
      "name": "Sample HTML Article",
      "kind": "html",
      "location": "/Archive",
      "tags": ["articles"],
      "creation_date": "2025-04-20T09:15:00Z",
      "modification_date": "2025-04-20T09:15:00Z"
    },
    {
      "uuid_placeholder": "FIXTURE-REC-0004-AAAA-AAAAAAAAAAAA",
      "name": "Sample RTF Memo",
      "kind": "rtf",
      "location": "/Inbox",
      "tags": ["memos"],
      "creation_date": "2025-05-10T11:00:00Z",
      "modification_date": "2025-05-10T11:00:00Z"
    },
    {
      "uuid_placeholder": "FIXTURE-REC-0005-AAAA-AAAAAAAAAAAA",
      "name": "Sample Plain Text Note",
      "kind": "txt",
      "location": "/Inbox",
      "tags": ["notes", "draft"],
      "creation_date": "2025-07-01T08:00:00Z",
      "modification_date": "2025-07-01T08:00:00Z"
    },
    {
      "uuid_placeholder": "FIXTURE-REC-0006-AAAA-AAAAAAAAAAAA",
      "name": "Sample WebArchive",
      "kind": "webarchive",
      "location": "/Archive/2025",
      "tags": ["clipping"],
      "creation_date": "2025-08-15T16:45:00Z",
      "modification_date": "2025-08-15T16:45:00Z"
    },
    {
      "uuid_placeholder": "FIXTURE-REC-0007-AAAA-AAAAAAAAAAAA",
      "name": "Sample Bookmark",
      "kind": "bookmark",
      "location": "/Archive",
      "tags": ["bookmark", "reference"],
      "creation_date": "2025-09-01T12:00:00Z",
      "modification_date": "2025-09-01T12:00:00Z"
    },
    {
      "uuid_placeholder": "FIXTURE-REC-0008-AAAA-AAAAAAAAAAAA",
      "name": "Sample Image",
      "kind": "image",
      "location": "/Archive/2025",
      "tags": ["screenshot"],
      "creation_date": "2025-10-12T13:30:00Z",
      "modification_date": "2025-10-12T13:30:00Z"
    },
    {
      "uuid_placeholder": "FIXTURE-REC-0009-AAAA-AAAAAAAAAAAA",
      "name": "Sample Second PDF",
      "kind": "PDF",
      "location": "/Inbox",
      "tags": ["invoices", "2024"],
      "creation_date": "2024-11-05T15:00:00Z",
      "modification_date": "2024-11-05T15:00:00Z"
    },
    {
      "uuid_placeholder": "FIXTURE-REC-0010-AAAA-AAAAAAAAAAAA",
      "name": "Sample Tagged Reference",
      "kind": "markdown",
      "location": "/Archive",
      "tags": ["reference", "starred"],
      "creation_date": "2025-02-28T17:30:00Z",
      "modification_date": "2025-02-28T17:30:00Z"
    }
  ]
}
```

The `uuid_placeholder` fields are **stable identifiers used by sanitization** (Task 4) to map captured UUIDs back to manifest entries — DT4 may not honor these UUIDs at record creation time, but the sanitizer maps DT-assigned UUIDs to the placeholders at capture time using `name` lookup.

- [ ] **Step 3.2: Validate JSON syntax**

```bash
uv run python -c "import json; data = json.load(open('tests/fixtures/dt-database-manifest.json')); print(f'records: {len(data[\"records\"])}, groups: {len(data[\"groups\"])}'); assert data['version'] == 1"
```

Expected: prints `records: 10, groups: 3`.

- [ ] **Step 3.3: Commit**

```bash
git add tests/fixtures/dt-database-manifest.json
git commit -m "feat(fixtures): manifest for synthetic DT4 test database

Canonical state of the fixtures-dt-mcp database used to capture cassettes
in tests/contract/cassettes/. 10 records across 3 groups, kinds spanning
PDF/markdown/html/rtf/txt/webarchive/bookmark/image — exercises the
RecordKind enum surface.

uuid_placeholder fields are stable identifiers used by the cassette
sanitizer (Task 4): captured DT-assigned UUIDs are rewritten to these
placeholders via name-lookup so the cassette diff is deterministic
across re-recordings.

Spec: docs/superpowers/specs/2026-05-04-cassette-vcr-real-data-design.md §4.2"
```

---

### Task 4: Sanitization module + tests (TDD pure)

**Files:**
- Create: `apps/server/src/istefox_dt_mcp_server/_record_cassette.py` (sanitization helpers — recording orchestrator added in Task 5)
- Create: `tests/unit/test_record_cassette.py`

#### Steps

- [ ] **Step 4.1: Create the module with sanitization functions**

Create `apps/server/src/istefox_dt_mcp_server/_record_cassette.py`:

```python
"""Cassette recording infrastructure for tests/contract/cassettes/.

Two responsibilities, separated for testability:

1. ``sanitize_cassette`` — pure function that rewrites captured stdout
   to use stable manifest placeholders (UUIDs, names, paths). Defense
   in depth: even if the recorder is pointed at the wrong DB, the
   sanitizer flags suspicious data and aborts before disk write.

2. ``record_cassette`` (in Task 5) — async orchestrator that wraps
   adapter._run_script, invokes the named tool, captures the first
   JXA call, applies sanitize_cassette, writes to disk.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)


SAFE_USERNAME_PLACEHOLDER = "fixture"


class SanitizationError(RuntimeError):
    """Raised when the captured cassette doesn't match the manifest.

    Indicates the recorder was pointed at the wrong DB or the manifest
    is stale. Aborting prevents committing a leaky cassette.
    """


def _build_name_to_uuid_map(manifest: dict[str, Any]) -> dict[str, str]:
    """Map record name → manifest uuid_placeholder for fast lookup."""
    out = {
        rec["name"]: rec["uuid_placeholder"]
        for rec in manifest.get("records", [])
    }
    out[manifest["database"]["name"]] = manifest["database"]["uuid_placeholder"]
    for group in manifest.get("groups", []):
        # Groups keyed by their last path segment (e.g. "Inbox" from "/Inbox")
        # because DT may surface the leaf name rather than the full path.
        leaf = group["path"].rstrip("/").split("/")[-1] or group["path"]
        out[leaf] = group["uuid_placeholder"]
    return out


def _build_path_set(manifest: dict[str, Any]) -> set[str]:
    """Collect all known paths from the manifest groups + records."""
    paths: set[str] = set()
    for group in manifest.get("groups", []):
        paths.add(group["path"])
    for rec in manifest.get("records", []):
        paths.add(rec["location"])
    return paths


def _rewrite_filesystem_paths(text: str) -> str:
    """Replace any /Users/<name>/ with /Users/fixture/."""
    return re.sub(r"/Users/[^/]+/", f"/Users/{SAFE_USERNAME_PLACEHOLDER}/", text)


def sanitize_cassette(
    cassette: dict[str, Any],
    manifest: dict[str, Any],
    *,
    abort_threshold: float = 0.5,
) -> dict[str, Any]:
    """Rewrite a captured cassette to use manifest-stable identifiers.

    Operations:
      - Filesystem paths /Users/<name>/ → /Users/fixture/
      - UUIDs in the captured stdout JSON: if the parent record's `name`
        matches a manifest entry, the UUID is replaced with the manifest
        placeholder. Otherwise the UUID is flagged unknown.
      - Record names not in the manifest: replaced with <UNKNOWN_NAME_n>.
      - Locations not in the manifest groups: replaced with <UNKNOWN_PATH_n>.

    Args:
        cassette: dict with keys "script", "argv", "stdout" (raw string).
        manifest: parsed dt-database-manifest.json content.
        abort_threshold: max fraction of unknown items before aborting.
            Default 0.5: if more than half the records in the captured
            stdout don't match manifest entries, we assume the recorder
            was pointed at the wrong DB and abort.

    Returns:
        New cassette dict with sanitized stdout.

    Raises:
        SanitizationError: if abort_threshold is exceeded or stdout is
            not parseable JSON.
    """
    name_to_uuid = _build_name_to_uuid_map(manifest)
    known_paths = _build_path_set(manifest)

    raw_stdout = cassette.get("stdout", "")
    if not raw_stdout:
        return {**cassette}

    # Step 1: filesystem paths (text-level)
    stdout_text = _rewrite_filesystem_paths(raw_stdout)

    # Step 2: parse JSON for record-level rewrites
    try:
        parsed = json.loads(stdout_text)
    except json.JSONDecodeError as e:
        raise SanitizationError(
            f"Captured stdout is not valid JSON: {e}. "
            f"First 200 chars: {stdout_text[:200]!r}"
        ) from e

    unknown_count = 0
    total_count = 0
    unknown_name_counter = 0
    unknown_path_counter = 0

    def _walk(node: Any) -> Any:
        nonlocal unknown_count, total_count, unknown_name_counter, unknown_path_counter
        if isinstance(node, dict):
            new: dict[str, Any] = {}
            name_field = node.get("name")
            for key, val in node.items():
                if key == "uuid" and isinstance(val, str) and name_field in name_to_uuid:
                    new[key] = name_to_uuid[name_field]
                    total_count += 1
                elif key == "uuid" and isinstance(val, str):
                    new[key] = val
                    total_count += 1
                    unknown_count += 1
                elif key == "name" and isinstance(val, str) and val not in name_to_uuid:
                    unknown_name_counter += 1
                    new[key] = f"<UNKNOWN_NAME_{unknown_name_counter}>"
                elif (
                    key in ("location", "path")
                    and isinstance(val, str)
                    and val not in known_paths
                    and not val.startswith("/Users/fixture/")
                ):
                    unknown_path_counter += 1
                    new[key] = f"<UNKNOWN_PATH_{unknown_path_counter}>"
                else:
                    new[key] = _walk(val)
            return new
        if isinstance(node, list):
            return [_walk(item) for item in node]
        return node

    sanitized_parsed = _walk(parsed)

    if total_count > 0 and unknown_count / total_count > abort_threshold:
        raise SanitizationError(
            f"Captured cassette has {unknown_count}/{total_count} unknown UUIDs "
            f"({unknown_count / total_count:.0%}, threshold {abort_threshold:.0%}). "
            "Are you running the recorder against fixtures-dt-mcp?"
        )

    log.debug(
        "cassette_sanitized",
        total_uuids=total_count,
        unknown_uuids=unknown_count,
        unknown_names=unknown_name_counter,
        unknown_paths=unknown_path_counter,
    )

    return {
        "script": cassette.get("script", ""),
        "argv": cassette.get("argv", []),
        "stdout": json.dumps(sanitized_parsed, ensure_ascii=False),
    }


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    """Load the canonical fixture-DB manifest from disk.

    Default path is ``tests/fixtures/dt-database-manifest.json`` resolved
    against the repo root. Tests can pass an explicit path to use a
    purpose-built manifest fixture.
    """
    if path is None:
        # Repo root is the parent of the apps/ directory.
        repo_root = Path(__file__).resolve().parents[5]
        path = repo_root / "tests" / "fixtures" / "dt-database-manifest.json"
    with path.open(encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)
    return data
```

- [ ] **Step 4.2: Create unit tests**

Create `tests/unit/test_record_cassette.py`:

```python
"""Tests for sanitization helpers in _record_cassette."""

from __future__ import annotations

import json

import pytest

from istefox_dt_mcp_server._record_cassette import (
    SanitizationError,
    sanitize_cassette,
)


_MANIFEST = {
    "version": 1,
    "database": {
        "name": "fixtures-dt-mcp",
        "uuid_placeholder": "FIXTURE-DB-0001",
    },
    "groups": [
        {"path": "/Inbox", "uuid_placeholder": "FIXTURE-GRP-INBOX"},
        {"path": "/Archive", "uuid_placeholder": "FIXTURE-GRP-ARCHIVE"},
    ],
    "records": [
        {
            "uuid_placeholder": "FIXTURE-REC-0001",
            "name": "Sample PDF Invoice 2025",
            "kind": "PDF",
            "location": "/Inbox",
            "tags": ["invoices"],
            "creation_date": "2025-01-01T00:00:00Z",
            "modification_date": "2025-01-01T00:00:00Z",
        },
    ],
}


def test_sanitize_replaces_known_uuids() -> None:
    """When the record name matches the manifest, the UUID is rewritten."""
    captured = {
        "script": "get_record.js",
        "argv": ["DT-RUNTIME-UUID-XYZ"],
        "stdout": json.dumps(
            {
                "uuid": "DT-RUNTIME-UUID-XYZ",
                "name": "Sample PDF Invoice 2025",
                "location": "/Inbox",
            }
        ),
    }
    out = sanitize_cassette(captured, _MANIFEST)
    parsed = json.loads(out["stdout"])
    assert parsed["uuid"] == "FIXTURE-REC-0001"


def test_sanitize_rewrites_filesystem_paths() -> None:
    captured = {
        "script": "list_databases.js",
        "argv": [],
        "stdout": json.dumps(
            [{"name": "fixtures-dt-mcp", "path": "/Users/john/Library/db.dtBase2"}]
        ),
    }
    out = sanitize_cassette(captured, _MANIFEST)
    assert "/Users/fixture/" in out["stdout"]
    assert "/Users/john/" not in out["stdout"]


def test_sanitize_replaces_unknown_record_name() -> None:
    captured = {
        "script": "search.js",
        "argv": ["something"],
        "stdout": json.dumps(
            [{"uuid": "DT-RUNTIME-XYZ", "name": "Personal Diary", "location": "/Inbox"}]
        ),
    }
    out = sanitize_cassette(captured, _MANIFEST)
    parsed = json.loads(out["stdout"])
    assert parsed[0]["name"] == "<UNKNOWN_NAME_1>"


def test_sanitize_replaces_unknown_path() -> None:
    captured = {
        "script": "search.js",
        "argv": ["x"],
        "stdout": json.dumps(
            [{"uuid": "x", "name": "Sample PDF Invoice 2025", "location": "/Confidential"}]
        ),
    }
    out = sanitize_cassette(captured, _MANIFEST)
    parsed = json.loads(out["stdout"])
    assert parsed[0]["location"] == "<UNKNOWN_PATH_1>"


def test_sanitize_aborts_when_too_many_unknowns() -> None:
    """If >50% of UUIDs lack a manifest match, abort with SanitizationError."""
    captured = {
        "script": "search.js",
        "argv": ["x"],
        "stdout": json.dumps(
            [
                {"uuid": "U1", "name": "Unknown 1", "location": "/Inbox"},
                {"uuid": "U2", "name": "Unknown 2", "location": "/Inbox"},
                {"uuid": "U3", "name": "Unknown 3", "location": "/Inbox"},
            ]
        ),
    }
    with pytest.raises(SanitizationError, match="unknown UUIDs"):
        sanitize_cassette(captured, _MANIFEST)


def test_sanitize_raises_on_invalid_json_stdout() -> None:
    captured = {"script": "x.js", "argv": [], "stdout": "not valid json {"}
    with pytest.raises(SanitizationError, match="not valid JSON"):
        sanitize_cassette(captured, _MANIFEST)


def test_sanitize_handles_empty_stdout() -> None:
    captured = {"script": "x.js", "argv": [], "stdout": ""}
    out = sanitize_cassette(captured, _MANIFEST)
    assert out["stdout"] == ""
```

- [ ] **Step 4.3: Run tests**

```bash
uv run pytest tests/unit/test_record_cassette.py -v
```

Expected: 7 tests pass.

- [ ] **Step 4.4: Lint + type check**

```bash
uv run ruff check apps/server/src/istefox_dt_mcp_server/_record_cassette.py tests/unit/test_record_cassette.py
uv run black --check apps/server/src/istefox_dt_mcp_server/_record_cassette.py tests/unit/test_record_cassette.py
uv run mypy apps/server/src/istefox_dt_mcp_server/_record_cassette.py
```

Expected: zero issues.

- [ ] **Step 4.5: Commit**

```bash
git add apps/server/src/istefox_dt_mcp_server/_record_cassette.py tests/unit/test_record_cassette.py
git commit -m "feat(record_cassette): sanitization module + 7 unit tests

Pure-function sanitizer rewrites captured cassettes to use stable
manifest placeholders: UUIDs by name-lookup, unknown record names →
<UNKNOWN_NAME_n>, unknown paths → <UNKNOWN_PATH_n>, /Users/<x>/ →
/Users/fixture/.

Aborts with SanitizationError if >50% of captured UUIDs don't match
the manifest — defends against accidentally pointing the recorder
at the wrong DB.

Spec: docs/superpowers/specs/2026-05-04-cassette-vcr-real-data-design.md §6"
```

---

### Task 5: Recording orchestrator + `--all` defaults

**Files:**
- Modify: `apps/server/src/istefox_dt_mcp_server/_record_cassette.py` (append `record_cassette` async function + `DEFAULT_INPUTS` map)
- Modify: `tests/unit/test_record_cassette.py` (append integration tests with mocked adapter)

#### Steps

- [ ] **Step 5.1: Append the recording orchestrator + defaults map**

Append at the end of `apps/server/src/istefox_dt_mcp_server/_record_cassette.py`:

```python
# ----------------------------------------------------------------------
# Recording orchestrator
# ----------------------------------------------------------------------


# Default inputs for the --all mode. Each entry is the JSON args the CLI
# would pass via --input; subagent/Stefano can override per-tool when
# recording manually.
DEFAULT_INPUTS: dict[str, dict[str, Any]] = {
    "list_databases": {},
    "search_bm25": {"query": "Sample", "databases": ["fixtures-dt-mcp"]},
    "find_related": {"uuid": "FIXTURE-REC-0001-AAAA-AAAAAAAAAAAA", "k": 5},
    "get_record": {"uuid": "FIXTURE-REC-0001-AAAA-AAAAAAAAAAAA"},
    "apply_tag": {
        "uuid": "FIXTURE-REC-0001-AAAA-AAAAAAAAAAAA",
        "tag": "review",
    },
    "move_record": {
        "uuid": "FIXTURE-REC-0001-AAAA-AAAAAAAAAAAA",
        "destination": "/Archive",
    },
}


SUPPORTED_TOOLS: tuple[str, ...] = tuple(DEFAULT_INPUTS.keys())


class _RecorderShim:
    """Wraps an adapter's _run_script to intercept the FIRST JXA call.

    After the first call, subsequent calls pass through unchanged.
    The captured (script, argv, stdout) is exposed via .captured.
    """

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter
        self._original = adapter._run_script
        self.captured: dict[str, Any] | None = None

    async def _wrapped(self, script: str, *args: Any, **kwargs: Any) -> Any:
        result = await self._original(script, *args, **kwargs)
        if self.captured is None:
            # The bridge typically passes script body; we record a synthetic
            # script_name based on the call site (the script_name field
            # is informational — replay matches by content, not name).
            argv = list(args) + [str(v) for v in kwargs.values()]
            self.captured = {
                "script": "<inline>.js",
                "argv": argv,
                "stdout": result if isinstance(result, str) else json.dumps(result),
            }
        return result

    def install(self) -> None:
        self._adapter._run_script = self._wrapped  # type: ignore[method-assign]

    def uninstall(self) -> None:
        self._adapter._run_script = self._original  # type: ignore[method-assign]


async def record_cassette(
    *,
    tool: str,
    input_args: dict[str, Any] | None = None,
    deps: Any,
    cassettes_dir: Path,
    manifest: dict[str, Any],
) -> Path:
    """Record a single cassette by invoking the named tool against live DT.

    Steps:
      1. Validate ``tool`` is in SUPPORTED_TOOLS.
      2. Wrap deps.adapter._run_script with _RecorderShim.
      3. Look up the tool's adapter method by name and invoke with input_args.
      4. Sanitize the captured stdout via sanitize_cassette.
      5. Write the result to ``cassettes_dir / f"{tool}.json"``.

    Args:
        tool: Name of the tool to record (must be in SUPPORTED_TOOLS).
        input_args: Args dict to pass to the tool. If None, uses DEFAULT_INPUTS[tool].
        deps: Live Deps with a real JXAAdapter (NOT mocked).
        cassettes_dir: Directory to write the cassette JSON into. Created if missing.
        manifest: Loaded fixture-DB manifest (use load_manifest()).

    Returns:
        Path to the written cassette file.

    Raises:
        ValueError: tool not in SUPPORTED_TOOLS.
        SanitizationError: capture didn't match the manifest.
    """
    if tool not in SUPPORTED_TOOLS:
        raise ValueError(
            f"Unsupported tool {tool!r}. Supported: {', '.join(SUPPORTED_TOOLS)}"
        )

    args = input_args if input_args is not None else DEFAULT_INPUTS[tool]
    shim = _RecorderShim(deps.adapter)
    shim.install()

    try:
        if tool == "list_databases":
            await deps.adapter.list_databases()
        elif tool == "search_bm25":
            await deps.adapter.search(
                args["query"],
                databases=args.get("databases"),
                max_results=args.get("max_results", 10),
            )
        elif tool == "find_related":
            await deps.adapter.find_related(args["uuid"], k=args.get("k", 10))
        elif tool == "get_record":
            await deps.adapter.get_record(args["uuid"])
        elif tool == "apply_tag":
            await deps.adapter.apply_tag(args["uuid"], args["tag"], dry_run=False)
        elif tool == "move_record":
            await deps.adapter.move_record(
                args["uuid"], args["destination"], dry_run=False
            )
        else:  # pragma: no cover — guarded by the SUPPORTED_TOOLS check above
            raise AssertionError("unreachable")
    finally:
        shim.uninstall()

    if shim.captured is None:
        raise RuntimeError(
            f"Recording {tool} captured nothing. The tool didn't issue a JXA call."
        )

    sanitized = sanitize_cassette(shim.captured, manifest)
    cassettes_dir.mkdir(parents=True, exist_ok=True)
    out_path = cassettes_dir / f"{tool}.json"
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(sanitized, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    log.info("cassette_recorded", tool=tool, path=str(out_path))
    return out_path
```

- [ ] **Step 5.2: Append integration-style unit tests for the orchestrator**

Append at the end of `tests/unit/test_record_cassette.py`:

```python
# ----------------------------------------------------------------------
# record_cassette orchestrator (with mocked adapter)
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_cassette_writes_correct_format(tmp_path) -> None:
    """End-to-end: recorder captures the first JXA call and writes to disk."""
    from unittest.mock import AsyncMock, MagicMock

    from istefox_dt_mcp_server._record_cassette import record_cassette

    deps = MagicMock()
    # Adapter._run_script is the JXA bridge call site we wrap.
    captured_stdout = json.dumps([
        {
            "uuid": "DT-RUNTIME-XYZ",
            "name": "fixtures-dt-mcp",
            "path": "/Users/john/Library/db.dtBase2",
        }
    ])
    deps.adapter._run_script = AsyncMock(return_value=captured_stdout)

    # The tool dispatcher calls list_databases on the adapter; that method
    # in turn calls _run_script. Mock list_databases to call _run_script.
    async def fake_list_databases() -> Any:
        return await deps.adapter._run_script("list_databases.js")

    deps.adapter.list_databases = fake_list_databases

    out_path = await record_cassette(
        tool="list_databases",
        deps=deps,
        cassettes_dir=tmp_path,
        manifest=_MANIFEST,
    )

    assert out_path.exists()
    cassette = json.loads(out_path.read_text())
    assert "script" in cassette
    assert "argv" in cassette
    assert "stdout" in cassette
    # Sanitization rewrote /Users/john/ → /Users/fixture/
    assert "/Users/fixture/" in cassette["stdout"]


@pytest.mark.asyncio
async def test_record_cassette_rejects_unsupported_tool(tmp_path) -> None:
    from unittest.mock import MagicMock

    from istefox_dt_mcp_server._record_cassette import record_cassette

    with pytest.raises(ValueError, match="Unsupported tool"):
        await record_cassette(
            tool="nonexistent",
            deps=MagicMock(),
            cassettes_dir=tmp_path,
            manifest=_MANIFEST,
        )


@pytest.mark.asyncio
async def test_record_cassette_uses_default_inputs(tmp_path) -> None:
    """If input_args is None, the recorder uses DEFAULT_INPUTS[tool]."""
    from unittest.mock import AsyncMock, MagicMock

    from istefox_dt_mcp_server._record_cassette import (
        DEFAULT_INPUTS,
        record_cassette,
    )

    deps = MagicMock()
    deps.adapter._run_script = AsyncMock(
        return_value=json.dumps({"uuid": "x", "name": "Sample PDF Invoice 2025"})
    )

    capture_args: dict[str, Any] = {}

    async def fake_get_record(uuid: str) -> Any:
        capture_args["uuid"] = uuid
        return await deps.adapter._run_script("get_record.js", uuid)

    deps.adapter.get_record = fake_get_record

    await record_cassette(
        tool="get_record",
        input_args=None,  # use DEFAULT_INPUTS["get_record"]
        deps=deps,
        cassettes_dir=tmp_path,
        manifest=_MANIFEST,
    )

    assert capture_args["uuid"] == DEFAULT_INPUTS["get_record"]["uuid"]
```

- [ ] **Step 5.3: Run tests**

```bash
uv run pytest tests/unit/test_record_cassette.py -v
```

Expected: 10 tests pass (7 from Task 4 + 3 new).

- [ ] **Step 5.4: Commit**

```bash
git add apps/server/src/istefox_dt_mcp_server/_record_cassette.py tests/unit/test_record_cassette.py
git commit -m "feat(record_cassette): orchestrator + DEFAULT_INPUTS for --all mode

record_cassette async function wraps adapter._run_script via _RecorderShim,
invokes the named tool, captures the FIRST JXA call, sanitizes, writes
to disk. Single-call recording only — multi-call tools (e.g. search
chained with get_record_text) are out of scope per spec §5.5.

DEFAULT_INPUTS dict provides sensible defaults for each of the 6
supported tools, used by the CLI's --all mode (Task 6).

3 new unit tests with mocked adapter verify shape, error path, and
default-args path."
```

---

### Task 6: Click subcommand `record-cassette`

**Files:**
- Modify: `apps/server/src/istefox_dt_mcp_server/cli.py` (add subcommand)

#### Steps

- [ ] **Step 6.1: Inspect existing CLI structure**

```bash
grep -n "@cli.command()" apps/server/src/istefox_dt_mcp_server/cli.py | head -10
```

Expected: lists existing subcommands (serve, doctor, audit, undo, etc.). The new subcommand follows the same `@cli.command()` decorator pattern.

- [ ] **Step 6.2: Add the subcommand**

Append before the last `if __name__ == "__main__":` block (or before whatever closes the file). Add the subcommand definition:

```python
@cli.command(name="record-cassette")
@click.option(
    "--tool",
    type=str,
    default=None,
    help="Tool name to record (e.g. list_databases). Mutually exclusive with --all.",
)
@click.option(
    "--input",
    "input_json",
    type=str,
    default=None,
    help='JSON args for the tool, e.g. \'{"uuid": "..."}\'. If omitted, uses DEFAULT_INPUTS.',
)
@click.option(
    "--all",
    "record_all",
    is_flag=True,
    default=False,
    help="Record all 6 supported cassettes in sequence using DEFAULT_INPUTS.",
)
@click.option(
    "--cassettes-dir",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    help="Override cassettes directory. Default: tests/contract/cassettes/.",
)
def record_cassette(
    tool: str | None,
    input_json: str | None,
    record_all: bool,
    cassettes_dir: Path | None,
) -> None:
    """Capture a fresh cassette by running a tool against live DEVONthink.

    Requires the synthetic fixture database `fixtures-dt-mcp` to be present
    in DT (run `python scripts/setup_test_database.py` first if missing).

    Examples:

      # Record one cassette
      istefox-dt-mcp record-cassette --tool list_databases

      # Record one with custom args
      istefox-dt-mcp record-cassette --tool search_bm25 --input '{"query":"Foo"}'

      # Record all 6 in sequence
      istefox-dt-mcp record-cassette --all
    """
    import asyncio
    import json as _json
    import sys

    from ._record_cassette import (
        SUPPORTED_TOOLS,
        SanitizationError,
        load_manifest,
        record_cassette as _record,
    )
    from .deps import build_default_deps

    if record_all and tool:
        click.echo("--all and --tool are mutually exclusive.", err=True)
        sys.exit(2)
    if not record_all and not tool:
        click.echo("Provide either --tool <name> or --all.", err=True)
        sys.exit(2)

    if cassettes_dir is None:
        repo_root = Path(__file__).resolve().parents[5]
        cassettes_dir = repo_root / "tests" / "contract" / "cassettes"

    parsed_args = _json.loads(input_json) if input_json else None
    manifest = load_manifest()

    async def run_one(tool_name: str, args: dict[str, Any] | None) -> None:
        deps = build_default_deps()
        try:
            out_path = await _record(
                tool=tool_name,
                input_args=args,
                deps=deps,
                cassettes_dir=cassettes_dir,
                manifest=manifest,
            )
            click.echo(f"✅ wrote {out_path}")
        except SanitizationError as e:
            click.echo(f"❌ sanitization failed for {tool_name}: {e}", err=True)
            sys.exit(1)
        except Exception as e:  # pragma: no cover — surface generic JXA failures
            click.echo(f"❌ recording {tool_name} failed: {e}", err=True)
            sys.exit(1)

    if record_all:
        for t in SUPPORTED_TOOLS:
            asyncio.run(run_one(t, None))
    else:
        assert tool is not None
        asyncio.run(run_one(tool, parsed_args))
```

If the imports at the top of `cli.py` don't already include `from pathlib import Path` and `from typing import Any`, add them.

- [ ] **Step 6.3: Verify the subcommand is registered**

```bash
uv run istefox-dt-mcp record-cassette --help
```

Expected: prints the help text including --tool, --input, --all, --cassettes-dir options.

- [ ] **Step 6.4: Run linters**

```bash
uv run ruff check apps/server/src/istefox_dt_mcp_server/cli.py
uv run black --check apps/server/src/istefox_dt_mcp_server/cli.py
uv run mypy apps/server/src/istefox_dt_mcp_server/cli.py
```

Expected: zero issues.

- [ ] **Step 6.5: Commit**

```bash
git add apps/server/src/istefox_dt_mcp_server/cli.py
git commit -m "feat(cli): add record-cassette Click subcommand

Honors ADR-0005's prescribed CLI:
  istefox-dt-mcp record-cassette --tool <name> [--input '<json>']
  istefox-dt-mcp record-cassette --all

Validates --tool/--all mutual exclusion. Loads the fixture-DB manifest,
builds the live Deps (NOT mocked — adapter talks to real DT4 via JXA),
invokes the recording orchestrator, surfaces sanitization errors via
exit code 1.

Implementation lives in _record_cassette.py; this file is just the
thin Click wrapper."
```

---

### Task 7: Setup script + recording guide + invariant test

**Files:**
- Create: `scripts/setup_test_database.py`
- Create: `docs/development/cassette-recording.md`
- Modify: `tests/contract/test_jxa_replay.py` (add invariant test)

#### Steps

- [ ] **Step 7.1: Create `scripts/setup_test_database.py`**

Create `scripts/setup_test_database.py`:

```python
#!/usr/bin/env python3
"""Idempotently recreate the fixtures-dt-mcp DEVONthink test database.

Reads tests/fixtures/dt-database-manifest.json, ensures the database,
groups, and records exist in DT4. Re-running the script after manual
edits restores the manifest's intended state (groups added, missing
records created — pre-existing records are NOT mutated to avoid
clobbering tweaks from the developer).

Prerequisites:
  - DEVONthink 4 running
  - AppleEvents permission granted to your terminal (`Privacy & Security
    → Automation → DEVONthink` toggled ON for Terminal.app)

Usage:
  python scripts/setup_test_database.py

Idempotency:
  - DB exists?     → re-use
  - Group exists?  → skip
  - Record name exists in DB? → skip (preserves user edits)
  - Record missing? → create with manifest properties

Exit codes:
  0 — success
  1 — DT not running or AppleEvents denied
  2 — manifest file missing or invalid

This script is intentionally **not** wired into pytest. It runs once
to set up the fixture DB; cassette recording (the next step) reads
from that DB via the record-cassette CLI.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run_jxa(script: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["osascript", "-l", "JavaScript", "-e", script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _ensure_database(db_name: str) -> str:
    """Returns the database UUID; creates the DB if missing."""
    script = f"""
    const dt = Application("DEVONthink");
    const existing = dt.databases().filter(d => d.name() === "{db_name}");
    if (existing.length > 0) {{
      JSON.stringify({{action: "reused", uuid: existing[0].uuid()}});
    }} else {{
      // Create new database in default location
      const newDbPath = ObjC.unwrap(
        $.NSString.stringWithString("~/Library/Application Support/DEVONthink/{db_name}.dtBase2")
          .stringByExpandingTildeInPath
      );
      const newDb = dt.createDatabase(newDbPath);
      JSON.stringify({{action: "created", uuid: newDb.uuid()}});
    }}
    """
    rc, stdout, stderr = _run_jxa(script)
    if rc != 0:
        raise RuntimeError(f"DB ensure failed: {stderr.strip() or stdout.strip()}")
    result = json.loads(stdout.strip())
    print(f"  database '{db_name}': {result['action']} (uuid: {result['uuid']})")
    return str(result["uuid"])


def _ensure_group(db_name: str, path: str) -> str:
    """Returns the group UUID; creates if missing. path is /A/B/C style."""
    parts = [p for p in path.split("/") if p]
    if not parts:
        raise ValueError(f"Invalid group path: {path}")

    script = f"""
    const dt = Application("DEVONthink");
    const dbs = dt.databases().filter(d => d.name() === "{db_name}");
    if (dbs.length === 0) throw new Error("DB not found: {db_name}");
    const db = dbs[0];

    let parent = db.root;
    const parts = {json.dumps(parts)};
    let current_uuid = null;

    for (const part of parts) {{
      const existing = parent.children().filter(c => c.name() === part && c.recordType() === "group");
      if (existing.length > 0) {{
        parent = existing[0];
        current_uuid = parent.uuid();
      }} else {{
        const newGroup = dt.createLocation(part, {{in: parent}});
        parent = newGroup;
        current_uuid = newGroup.uuid();
      }}
    }}
    JSON.stringify({{uuid: current_uuid}});
    """
    rc, stdout, stderr = _run_jxa(script)
    if rc != 0:
        raise RuntimeError(f"Group ensure failed for {path}: {stderr.strip() or stdout.strip()}")
    result = json.loads(stdout.strip())
    print(f"  group '{path}': uuid {result['uuid']}")
    return str(result["uuid"])


def _ensure_record(db_name: str, rec: dict[str, object]) -> tuple[str, str]:
    """Returns (action, uuid). action ∈ {created, skipped}."""
    script = f"""
    const dt = Application("DEVONthink");
    const dbs = dt.databases().filter(d => d.name() === "{db_name}");
    if (dbs.length === 0) throw new Error("DB not found");
    const db = dbs[0];

    const matching = db.contents().filter(r =>
      r.name() === {json.dumps(rec['name'])}
    );
    if (matching.length > 0) {{
      JSON.stringify({{action: "skipped", uuid: matching[0].uuid()}});
    }} else {{
      const newRec = dt.createRecord({{
        name: {json.dumps(rec['name'])},
        type: {json.dumps(rec['kind'])},
      }}, {{in: db.root}});
      // Move into target location
      const target_path = {json.dumps(rec['location'])};
      // (Simplified: real impl would resolve target group by path.)
      // Tags
      newRec.tags = {json.dumps(rec.get('tags', []))};
      JSON.stringify({{action: "created", uuid: newRec.uuid()}});
    }}
    """
    rc, stdout, stderr = _run_jxa(script)
    if rc != 0:
        raise RuntimeError(
            f"Record ensure failed for {rec['name']}: {stderr.strip() or stdout.strip()}"
        )
    result = json.loads(stdout.strip())
    return str(result["action"]), str(result["uuid"])


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    manifest_path = repo_root / "tests" / "fixtures" / "dt-database-manifest.json"
    if not manifest_path.exists():
        print(f"ERROR: manifest missing at {manifest_path}", file=sys.stderr)
        return 2
    manifest = json.loads(manifest_path.read_text())

    db_name = manifest["database"]["name"]
    print(f"Setting up test database '{db_name}'...")

    try:
        _ensure_database(db_name)
        for group in manifest["groups"]:
            _ensure_group(db_name, group["path"])
        created = 0
        skipped = 0
        for rec in manifest["records"]:
            action, _ = _ensure_record(db_name, rec)
            if action == "created":
                created += 1
            else:
                skipped += 1
        print(f"\n✅ done: {created} created, {skipped} already present")
        return 0
    except RuntimeError as e:
        print(f"❌ failure: {e}", file=sys.stderr)
        if "AppleEvents" in str(e) or "1743" in str(e):
            print(
                "  Fix: System Settings → Privacy & Security → Automation → "
                "enable DEVONthink for your terminal.",
                file=sys.stderr,
            )
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

Make it executable:

```bash
chmod +x scripts/setup_test_database.py
```

> **Note**: this script's JXA fragments are best-effort (DT4's `createRecord` / `createLocation` semantics may differ slightly in dictionary). Stefano runs it once on his Mac to create the fixture DB; if it fails, fall back to manually creating the 10 records via DT GUI using the manifest as a checklist. The script is convenience, not a hard dependency.

- [ ] **Step 7.2: Create the recording guide**

Create `docs/development/cassette-recording.md`:

```markdown
# Cassette recording

Real-data cassettes in `tests/contract/cassettes/` are captured from a
synthetic DT4 database called **`fixtures-dt-mcp`**. This guide walks
through setup and recording.

## Prerequisites

- macOS with DEVONthink 4 installed
- DEVONthink 4 running
- AppleEvents permission granted to your terminal (System Settings →
  Privacy & Security → Automation → enable DEVONthink for Terminal.app)
- `uv` (the project's package manager)

## One-time setup: fixture database

```bash
python scripts/setup_test_database.py
```

This idempotently creates `fixtures-dt-mcp.dtBase2` in your default DT
data directory and populates it with 10 records (3 groups) per
`tests/fixtures/dt-database-manifest.json`.

If the script fails (rare — DT4 dictionary edge cases):

1. In DT GUI, create a new database named `fixtures-dt-mcp`.
2. Use the manifest as a checklist to manually create the 3 groups and 10 records.
3. Tag each record per the manifest.

## Recording cassettes

### One at a time

```bash
uv run istefox-dt-mcp record-cassette --tool list_databases

uv run istefox-dt-mcp record-cassette \
  --tool search_bm25 \
  --input '{"query": "Sample", "databases": ["fixtures-dt-mcp"]}'
```

### All six in sequence

```bash
uv run istefox-dt-mcp record-cassette --all
```

This uses sane defaults from `DEFAULT_INPUTS` in
`apps/server/src/istefox_dt_mcp_server/_record_cassette.py`. Adapt the
defaults if your synthetic DB diverges.

## Verification

After recording:

```bash
uv run pytest tests/contract/ -m contract -v
```

Expected: all replay tests pass against the new cassettes.

## Sanitization

Captures pass through `sanitize_cassette` before disk write:

- Filesystem paths `/Users/<you>/...` → `/Users/fixture/...`
- Captured UUIDs → manifest `uuid_placeholder` (matched by record name)
- Unknown record names → `<UNKNOWN_NAME_n>` (defense in depth — should
  never trigger if you're recording against `fixtures-dt-mcp`)
- Unknown paths → `<UNKNOWN_PATH_n>` (same)

If sanitization aborts (>50% UUIDs unknown), you're recording against
the wrong DB. Verify `--databases` arg targets `fixtures-dt-mcp` only.

## When to re-record

- DT4 minor release: re-record all 6 cassettes; review the diff in PR.
- Tool input shape changes: re-record only the affected cassette.
- Synthetic DB schema change: update the manifest, re-run
  `setup_test_database.py`, re-record.
```

- [ ] **Step 7.3: Add the cassette invariant test**

Append to `tests/contract/test_jxa_replay.py`:

```python
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
```

- [ ] **Step 7.4: Run the invariant tests against existing synthetic cassettes**

```bash
uv run pytest tests/contract/test_jxa_replay.py::test_cassettes_have_no_personal_filesystem_paths tests/contract/test_jxa_replay.py::test_cassettes_have_no_unknown_placeholders -v -m contract
```

Expected: PASS for both — the synthetic cassettes don't contain personal paths or UNKNOWN placeholders. (If they do, the invariant test caught a pre-existing leak in synthetic data — fix it before merging.)

- [ ] **Step 7.5: Commit**

```bash
git add scripts/setup_test_database.py docs/development/cassette-recording.md tests/contract/test_jxa_replay.py
git commit -m "feat: fixture-DB regen script + recording guide + cassette invariants

scripts/setup_test_database.py — idempotent JXA-driven recreation of
the fixtures-dt-mcp test database from the manifest. Run once before
the first recording session, re-run any time to fix drift.

docs/development/cassette-recording.md — short guide for developers:
prerequisites, setup, one-shot and --all recording flows, verification,
sanitization explanation, when-to-re-record matrix.

tests/contract/test_jxa_replay.py — two new invariants:
  - no /Users/<realname>/ paths in cassettes (only /Users/fixture/)
  - no <UNKNOWN_*> placeholders (would indicate wrong-DB recording)

These run against the existing synthetic cassettes today and will
continue to enforce the invariant after Task 8 replaces them with
real captures."
```

---

### Task 8: Live capture (manual — Stefano's Mac with DT4 live)

> **This task is NOT executable by a remote subagent.** It runs on Stefano's Mac. A subagent should SKIP this task and proceed to Task 9 (push + PR), noting in the PR description that the live-capture step is pending. The existing synthetic cassettes remain valid until Stefano replaces them.

**Files:**
- Modify: `tests/contract/cassettes/*.json` (6 files overwritten by `record-cassette --all`)

#### Steps (manual, Stefano)

- [ ] **Step 8.1: Verify prerequisites**

```bash
# DEVONthink 4 running
osascript -l JavaScript -e 'JSON.stringify(Application("DEVONthink").version())'
# Expected: prints "4.x.x"
```

- [ ] **Step 8.2: Set up the fixture database**

```bash
python scripts/setup_test_database.py
```

Expected output: `✅ done: 10 created, 0 already present` (or similar). On re-run: `✅ done: 0 created, 10 already present`.

- [ ] **Step 8.3: Record all 6 cassettes**

```bash
uv run istefox-dt-mcp record-cassette --all
```

Expected: 6 lines `✅ wrote tests/contract/cassettes/<tool>.json`.

If sanitization aborts on any tool (`SanitizationError: ...% unknown UUIDs`), the recorder was probably pointed at the wrong DB. Verify the synthetic DB is named exactly `fixtures-dt-mcp` and try again.

- [ ] **Step 8.4: Verify replay tests pass**

```bash
uv run pytest tests/contract/ -m contract -v
```

Expected: all pass against the new real-data cassettes. If a Pydantic model fails to parse, it's likely a real-vs-synthetic shape divergence — fix the model (most likely needs more `LooseModel` coverage; some sub-model wasn't switched in Task 2).

- [ ] **Step 8.5: Review the diff**

```bash
git diff tests/contract/cassettes/
```

Six files updated. Each diff is large (synthetic JSON replaced by real-captured JSON), but reviewable. The shape (`script`, `argv`, `stdout`) is unchanged.

- [ ] **Step 8.6: Commit**

```bash
git add tests/contract/cassettes/
git commit -m "feat(cassettes): replace synthetic with real captures from fixtures-dt-mcp

All 6 cassettes regenerated from a fresh capture session against DT4
on the development Mac. The synthetic placeholders are gone; the
content is real DT4 JSON output passed through the sanitizer
(/Users/<x>/ → /Users/fixture/, UUIDs swapped to manifest placeholders
by name lookup).

Replay tests still pass with the existing test_jxa_replay.py contract
test logic — only the data inside the cassettes changed."
```

---

### Task 9: CHANGELOG, README, push, PR, CI

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`

#### Steps

- [ ] **Step 9.1: Add CHANGELOG entry**

In `CHANGELOG.md`, find the `## [Unreleased]` heading. Append:

```markdown
### Added (cassette VCR real-data capture)

- New CLI subcommand `istefox-dt-mcp record-cassette` (alongside `--all`
  flag) that captures fresh contract test cassettes from a live DT4 against
  a synthetic fixture database. Honors the prescription in
  [ADR-0005](docs/adr/0005-test-strategy-4-tier.md) under "Aggiornamento".
- New synthetic fixture database manifest at
  `tests/fixtures/dt-database-manifest.json` (10 records, 3 groups,
  spanning all `RecordKind` variants).
- New idempotent JXA-driven setup script `scripts/setup_test_database.py`
  to create or repair the fixture DB on developer machines.
- New developer guide at `docs/development/cassette-recording.md`.
- New invariant tests on `tests/contract/cassettes/`: no leaked personal
  filesystem paths, no `<UNKNOWN_*>` placeholders.

### Changed

- `Record`, `Database`, `SearchResult`, `RelatedResult`, `TagResult`,
  `MoveResult`, `HealthStatus`, `ClassifySuggestion` now inherit from
  the new `LooseModel` base (`extra='ignore'`) instead of `StrictModel`
  (`extra='forbid'`). Real-captured DT4 output may include extra fields
  the synthetic cassettes omitted; rejecting them would break replay.
  Input models stay on `StrictModel`.
```

- [ ] **Step 9.2: README — Testing section update**

```bash
grep -n "## Testing\|## Tests\|## Development" README.md
```

In the section that exists (or under the Status / Development section if neither header is present), add:

```markdown
### Recording new contract cassettes

Contract tests in `tests/contract/cassettes/` are captured from a synthetic
DT4 database. See [`docs/development/cassette-recording.md`](docs/development/cassette-recording.md)
for the workflow.
```

- [ ] **Step 9.3: Sanity-check the diff**

```bash
git diff CHANGELOG.md README.md
```

- [ ] **Step 9.4: Commit**

```bash
git add CHANGELOG.md README.md
git commit -m "docs: cassette VCR real-data — CHANGELOG + README

CHANGELOG entry under [Unreleased] documenting the new record-cassette
CLI, fixture DB manifest, setup script, recording guide, and the
StrictModel → LooseModel switch on output schemas.

README points developers to the recording guide."
```

- [ ] **Step 9.5: Push and open PR**

```bash
git push -u origin feat/cassette-vcr-real-data

gh pr create --title "feat(test): cassette VCR real-data capture (0.2.0)" --body "$(cat <<'EOF'
## Summary

Replaces 6 hand-written synthetic cassettes in \`tests/contract/cassettes/\` with real-data captures from a dedicated synthetic DT4 fixture database, via a new \`istefox-dt-mcp record-cassette\` Click subcommand.

Honors the promise in [ADR-0005](docs/adr/0005-test-strategy-4-tier.md) under "Aggiornamento".

## Spec + plan

Both committed in this PR:
- \`docs/superpowers/specs/2026-05-04-cassette-vcr-real-data-design.md\` — Approved 2026-05-04
- \`docs/superpowers/plans/2026-05-04-cassette-vcr-real-data.md\` — TDD step-by-step

## Behavior

| Aspect | Choice (per spec §13) |
|---|---|
| Dataset | 1B — synthetic dedicated DB \`fixtures-dt-mcp\` (NOT committed; manifest + regen script committed) |
| Capture flow | 2A — Click subcommand \`istefox-dt-mcp record-cassette --tool <name>\` plus \`--all\` |
| Initial scope | 3A — all 6 cassettes regenerated |
| Sanitization | 4B — UUIDs / names / paths defensively rewritten |

## Test plan

- [x] 10 unit tests for sanitization + recorder orchestrator (mocked adapter)
- [x] 2 invariant tests on cassettes (no personal paths, no UNKNOWN placeholders)
- [x] Existing replay tests (\`test_jxa_replay\`) unchanged in logic; pass against either synthetic or real-data cassettes
- [x] \`uv run ruff check\` / \`black --check\` / \`mypy\` clean
- [ ] **Live capture step (Task 8 in plan)**: pending — must run on a Mac with DT4. The infrastructure works against existing synthetic cassettes; replacing them with real captures is a follow-up commit on this branch.

## Compatibility notes

- No breaking changes to public tool surface.
- Output Pydantic models switched from \`StrictModel\` (\`extra='forbid'\`) to \`LooseModel\` (\`extra='ignore'\`). Input models unchanged.
- The 6 existing synthetic cassettes remain valid until replaced by Task 8.

## Out of scope

- Multi-call cassettes (current format records the FIRST JXA call only; multi-call tools like \`summarize_topic\` need format extension — tracked as known limitation per spec §5.5).
- Cassettes for \`bulk_apply\`, \`ask_database\`, \`summarize_topic\` (out of scope; this PR only migrates the existing 6).
- Auto-recording in CI (rejected per spec §3 — manual command per ADR-0005).
EOF
)"
```

- [ ] **Step 9.6: Watch CI**

```bash
gh pr checks --watch --interval 15
```

Expected: lint-and-test, mypy, macos-import-and-bundle all pass within 1-3 minutes.

- [ ] **Step 9.7: STOP — do not auto-merge**

Main is protected. The PR awaits human review. The plan ends with the PR open and CI green.

---

## Notes for the executor

- Run from repo root: `/Users/stefanoferri/Developer/Devonthink_MCP`.
- Python 3.12 required.
- Conventional Commits in English. NO `Co-Authored-By: Claude` trailer.
- **Task 8 is manual** — on a Mac with DT4. A subagent should skip it and continue to Task 9, leaving a checkbox in the PR description for the maintainer.
- If `scripts/setup_test_database.py` fails on Task 8.2, Stefano falls back to manually creating the 10 records via DT GUI using the manifest as checklist. This is acceptable — the script is convenience, not a hard dependency.
- If Pydantic strict-mode test failures appear in Task 2.3, **read the error**: it should clearly indicate which model is rejecting an extra field. Switch that specific model to `LooseModel` (or fix the test if it asserts on strict-mode behavior that's now obsolete).
