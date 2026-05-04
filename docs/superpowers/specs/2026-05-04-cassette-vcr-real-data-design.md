# Cassette VCR — Real-Data Capture Design Spec

- **Status**: **Approved** (2026-05-04 — decisions 1B + 2A + 3A + 4B locked in brainstorming)
- **Target version**: 0.2.0
- **Owner**: istefox
- **Scope**: replace synthetic cassettes in `tests/contract/cassettes/` with real-data captures from a synthetic DT4 fixture database, via a new `istefox-dt-mcp record-cassette` CLI
- **Out of scope**: capturing cassettes against the user's personal databases (privacy concern), automatic re-recording in CI (manual command, per ADR-0005), cassettes for write tools that don't have a synthetic counterpart yet

---

## 1. Context

ADR-0005 defined the 4-tier test strategy in 0.0.x. Tier 2 (contract VCR) currently has 6 cassettes in `tests/contract/cassettes/` (`search_bm25, list_databases, apply_tag, move_record, find_related, get_record`) that are **hand-written synthetic** — JSON files crafted to match the *expected* JXA output shape rather than recorded from a live DT.

The synthetic approach has two costs:

1. **False confidence**: if DT changes its output shape between releases, synthetic cassettes don't catch it because they were never derived from reality. The whole point of contract tests is to detect drift; synthetic cassettes can't.
2. **Maintenance burden**: every new tool needs a cassette author to *guess* the shape DT will produce. Faster and more reliable to capture once and replay.

The cassette JSON format itself is fine (see `tests/contract/test_jxa_replay.py`):

```json
{
  "script": "<script_name>.js",
  "argv": ["..."],
  "stdout": "<raw JSON string DT would return>"
}
```

ADR-0005 already prescribed the future-state CLI: `uv run istefox-dt-mcp test-record --tool=<name>` (subsection: "Aggiornamento"). This spec implements that promise.

## 2. Goals

- Add a new `istefox-dt-mcp record-cassette` Click subcommand that captures a fresh cassette JSON by running the named tool against a live DT and persisting `(script, argv, stdout)` to disk.
- Define a **synthetic test database** (DT4 `.dtBase2` directory) so the captured cassettes contain known-good UUIDs, names, and locations — no leakage of personal data.
- Provide a regen script that any developer with DT4 can run locally to recreate the fixture database from a manifest committed to the repo.
- Migrate **all 6 existing synthetic cassettes** to real-data captures in this PR (per decision 3A: scope-complete, not gradual).
- Apply post-capture sanitization (decision 4B): UUIDs replaced with stable placeholders, names and paths swapped to fixture-known strings — defense in depth even though decision 1B (synthetic dataset) makes leakage unlikely at the source.

## 3. Non-goals

- Cassettes against the user's personal DT databases (rejected: privacy, reproducibility).
- Automatic re-recording in CI when DT releases a new version (out of scope; CI runs replay-only on Linux).
- Replacing the synthetic-data fixtures used by Tier 1 unit tests in `tests/fixtures/jxa_outputs/*.json` — those are a different surface (mocked adapter calls, not cassette-replay).
- Adding cassettes for tools that don't have one yet (`bulk_apply`, `summarize_topic`, `ask_database`) — the focus is migrating the existing 6, not expanding coverage. Coverage expansion is a follow-up PR using the same CLI.

## 4. Synthetic test database

### 4.1 Identity

- **Database name**: `fixtures-dt-mcp`
- **File path on developer's Mac**: `~/Library/Application Support/DEVONthink/fixtures-dt-mcp.dtBase2/` (DT4 default DB location)
- **NOT committed to repo**: the `.dtBase2` directory is ~50-200 MB of binary DT internals, unsuitable for git. Only the manifest (next section) and the regen script are committed.

### 4.2 Manifest

Committed at `tests/fixtures/dt-database-manifest.json`. Describes the canonical state of `fixtures-dt-mcp`:

```json
{
  "database_name": "fixtures-dt-mcp",
  "database_uuid": "FIXTURE-DB-0001-AAAA-AAAAAAAAAAAA",
  "groups": [
    {"path": "/Inbox", "uuid": "FIXTURE-GRP-INBOX-AAAA-AAAAAAAAAAAA"},
    {"path": "/Archive", "uuid": "FIXTURE-GRP-ARCHIVE-AAAA-AAAAAAAAA"},
    {"path": "/Archive/2025", "uuid": "FIXTURE-GRP-2025-AAAA-AAAAAAAAAA"}
  ],
  "records": [
    {
      "uuid": "FIXTURE-REC-0001-AAAA-AAAAAAAAAAAA",
      "name": "Sample PDF Invoice 2025",
      "kind": "PDF",
      "location": "/Inbox",
      "tags": ["invoices", "2025"],
      "creation_date": "2025-03-15T10:00:00Z",
      "modification_date": "2025-03-15T10:00:00Z"
    },
    {
      "uuid": "FIXTURE-REC-0002-AAAA-AAAAAAAAAAAA",
      "name": "Sample Markdown Note",
      "kind": "markdown",
      "location": "/Archive/2025",
      "tags": ["notes"],
      "creation_date": "2025-06-01T14:30:00Z",
      "modification_date": "2025-06-01T14:30:00Z"
    }
    // ...8 more records spanning kinds (HTML, RTF, plain text, image, group, smart group placeholder)
  ]
}
```

Total fixture size: **10-12 records** across **3 groups**, mixing all `RecordKind` values represented in `RecordKind` StrEnum so cassettes exercise the full kind-translation surface.

### 4.3 Regeneration script

`scripts/setup_test_database.py` — Python script that:

1. Reads `tests/fixtures/dt-database-manifest.json`.
2. Connects to DT via JXA (`Application("DEVONthink")`).
3. Creates the database `fixtures-dt-mcp` if missing.
4. Creates each group (idempotent: skip if exists).
5. Creates each record (`make new record`) with the manifest's properties.
6. Tags each record per the manifest.
7. Reports: ✅ created N, ⏭ skipped M, ❌ failed K.

Idempotent — running twice has the same effect as once. Re-running fixes drift if a developer accidentally edits the test DB by hand.

Failure modes:
- DT not running: print clear error, exit 1.
- AppleEvents denied: print TCC fix instructions, exit 1.
- Manifest UUID conflicts (DT rejects pre-set UUIDs): warn but continue with DT-assigned UUIDs (the manifest UUIDs are *desired* labels; if DT4 doesn't allow setting them, the cassette captures whatever DT chose, then the sanitization step in capture replaces them with the manifest UUIDs).

## 5. `record-cassette` CLI

### 5.1 Invocation

```bash
uv run istefox-dt-mcp record-cassette --tool <tool_name> [--input '<json-args>']
```

Examples:

```bash
# No-arg tool
uv run istefox-dt-mcp record-cassette --tool list_databases

# Tool with args
uv run istefox-dt-mcp record-cassette --tool search --input '{"query": "Sample", "databases": ["fixtures-dt-mcp"]}'

uv run istefox-dt-mcp record-cassette --tool get_record --input '{"uuid": "FIXTURE-REC-0001-AAAA-AAAAAAAAAAAA"}'
```

### 5.2 Behavior

1. Validate `--tool` is one of the supported tool names. (Mapping: `list_databases, search, find_related, get_record, apply_tag, move_record`.)
2. Build the dependency graph (`build_default_deps()`) but with the **real** `JXAAdapter` (not mocked).
3. Wrap `adapter._run_script` to capture every JXA invocation: `(script_name, argv, stdout)`.
4. Invoke the tool through its normal code path with the parsed `--input` args.
5. The wrapper logs the *first* JXA call's `(script, argv, stdout)` triple — most tools issue exactly one JXA call. For tools that issue multiple (e.g., `search` followed by `get_record_text`), document this in the cassette: cassettes are **single-call recordings**; multi-call tools need their own pattern (see §5.5).
6. Apply sanitization (§6).
7. Write the result to `tests/contract/cassettes/<tool_name>.json`, overwriting any existing.

### 5.3 Output format (unchanged)

Same shape `tests/contract/test_jxa_replay.py` already expects:

```json
{
  "script": "<script_name>.js",
  "argv": ["..."],
  "stdout": "<raw JSON string DT returned>"
}
```

### 5.4 Implementation location

- `apps/server/src/istefox_dt_mcp_server/cli.py` — add the `record_cassette` Click subcommand
- `apps/server/src/istefox_dt_mcp_server/_record_cassette.py` (new module) — the recording logic, kept out of the CLI module to keep the latter slim

### 5.5 Multi-call tools

Tools that issue >1 JXA call (e.g., `search` may chain `get_record_text` for snippets) are out of scope for v1 of the CLI — the recorder captures only the first call. The 6 current cassettes are all single-call tools. For future multi-call coverage, the cassette format will need extension to a list of triples (`tests/contract/cassettes/<tool>.json` becomes an array). Tracked as known limitation in §11.

## 6. Sanitization

Even though decision 1B (synthetic database) reduces leakage risk to near-zero, defense in depth: every captured cassette is run through a sanitizer before being written to disk.

### 6.1 Rules

1. **UUIDs**: replace any UUID in the captured `stdout` JSON with the corresponding manifest UUID by name lookup.
   - If a record's `name` matches a manifest entry, its UUID is rewritten to the manifest UUID.
   - If no name match (e.g. a generated audit_id, a transient UUID), leave as-is — but log a warning (could indicate leakage, manual review needed).
2. **Names**: any record name not in the manifest is replaced with `"<UNKNOWN_RECORD_<n>>"` where `<n>` is a stable counter per cassette. This is unreachable if the test DB is the synthetic one, but defends against accidental capture against the wrong DB.
3. **Paths (location)**: any path not starting with one of the manifest's known group paths (`/Inbox`, `/Archive`, etc.) is replaced with `"<UNKNOWN_PATH_<n>>"`. Same defense-in-depth motivation.
4. **Filesystem paths**: any absolute path containing `/Users/<username>/` is rewritten to `/Users/fixture/`.

### 6.2 Implementation

`apps/server/src/istefox_dt_mcp_server/_record_cassette.py` exposes a pure function `sanitize_cassette(raw: dict, manifest: dict) -> dict` for unit-testability.

### 6.3 Failure mode

If the sanitizer flags >50% of UUIDs as "no manifest match" or any `<UNKNOWN_*>` placeholder appears, the CLI **aborts** with an error: "Captured cassette doesn't match the synthetic fixture database. Are you running the recorder against `fixtures-dt-mcp`?". Prevents committing a cassette captured against the wrong DB.

## 7. Replay engine compatibility

The current `tests/contract/test_jxa_replay.py` parses cassettes already in the target format (`script`, `argv`, `stdout`). It needs **no changes** to consume the new real-data cassettes — the format is identical, only the data inside changes.

Risk: real-captured `stdout` may contain fields the synthetic cassette omitted (extra metadata DT returns that the parser ignores). The Pydantic models use `model_config = ConfigDict(extra='ignore')` (verified in `StrictModel` definition? — need to verify; if not, the test may fail on extra fields and we add `extra='ignore'` as part of this PR).

If verification reveals `StrictModel` is `extra='forbid'`, switch to `extra='ignore'` for the *output* models (Record, Database, etc.) — input models stay strict because they validate user/LLM input.

## 8. Migration strategy

All 6 cassettes regenerated **in a single PR** (decision 3A). Order of operations:

1. Set up the synthetic database (`scripts/setup_test_database.py`) on the developer's Mac.
2. Run `record-cassette` for each of the 6 tools — capture the new JSON in place, overwriting the synthetic.
3. Run the contract tests (`uv run pytest tests/contract/ -v -m contract`). Verify all pass against the new cassettes.
4. If a Pydantic model fails to parse the new captured `stdout`, that's the contract test catching real drift between synthetic and reality — fix the model (likely `extra='ignore'` per §7) and re-run.

The 6 cassettes diff in the PR will be large (each replaces the old synthetic JSON with a real capture) but reviewable as 6 independent file changes.

## 9. Test plan

### 9.1 New unit tests

In `tests/unit/test_record_cassette.py`:

1. `test_sanitize_replaces_known_uuids` — cassette with a known fixture UUID gets stable replacement.
2. `test_sanitize_flags_unknown_uuids` — cassette with non-fixture UUID triggers the `<UNKNOWN_*>` placeholder.
3. `test_sanitize_rewrites_filesystem_paths` — `/Users/john/...` → `/Users/fixture/...`.
4. `test_sanitize_aborts_on_too_many_unknowns` — sanitize raises if >50% of records are unknown.
5. `test_record_cassette_writes_correct_format` — end-to-end with mocked adapter, verify the JSON file written matches the expected schema (script + argv + stdout fields).

### 9.2 Updated contract tests

Existing `tests/contract/test_jxa_replay.py` continues to work — only data changes. Add a new sanity test:

6. `test_cassettes_pass_sanitization_invariants` — for each cassette in `tests/contract/cassettes/`, assert no `<UNKNOWN_*>` placeholder appears and no `/Users/<realname>/` paths leak.

### 9.3 Manual integration

Stefano runs `setup_test_database.py` once, then `record-cassette --tool <each>` 6 times. Documented in `docs/development/cassette-recording.md` (new file, brief 1-page guide).

## 10. Documentation

- New file `docs/development/cassette-recording.md` — short guide: prerequisites, step-by-step recording flow, troubleshooting.
- CHANGELOG `[Unreleased]` entry.
- README: add a one-line under "Testing" pointing to the recording guide.

## 11. Risks & open questions

- **Risk**: DT4 may not honor pre-set UUIDs in `make new record`. Mitigation: the regen script accepts whatever UUID DT assigns, the manifest is updated to match, the cassettes contain the DT-assigned UUIDs (sanitization replaces them with stable manifest values for diff-friendliness). If this hypothesis fails (DT randomizes UUIDs every run), we accept random-but-stable-per-recording UUIDs — sanitization still replaces them with manifest equivalents based on `name` lookup.
- **Open**: should `record-cassette` also support a `--all` flag to record all 6 cassettes in one shot? Decision: **yes**, add it. Saves the developer 6 invocations. Implementation: just iterate the supported tool list with sane default `--input` for each (read from a static map in `_record_cassette.py`).
- **Open**: should we commit the `.dtBase2` directory after all? Decision: **no** — too large, binary, unsuitable for git. Manifest + regen script is the canonical approach.
- **Risk**: Pydantic `StrictModel` may forbid extra fields; real captures might include them. §7 covers the mitigation. Confirmed during implementation by running the contract tests post-capture.

## 12. Implementation note (handoff to writing-plans)

- New files (estimate):
  - `apps/server/src/istefox_dt_mcp_server/_record_cassette.py` — recording + sanitization (~150 LoC)
  - `tests/fixtures/dt-database-manifest.json` — canonical manifest (~3 KB)
  - `scripts/setup_test_database.py` — fixture DB regen (~120 LoC)
  - `docs/development/cassette-recording.md` — recording guide (~50 lines)
  - `tests/unit/test_record_cassette.py` — unit tests (~150 LoC)
- Modified files:
  - `apps/server/src/istefox_dt_mcp_server/cli.py` — add `record_cassette` subcommand (~30 LoC)
  - 6× `tests/contract/cassettes/*.json` — replace synthetic with real-captured JSON
  - `CHANGELOG.md` and `README.md` — minimal updates
  - Possibly `libs/schemas/.../common.py` — `extra='ignore'` config on output models (only if §7 verification reveals it's needed)
- Estimated effort: ~3 sessions of work, ~500 LoC + ~3 KB manifest.

## 13. Decision summary (for traceability)

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Dataset | **B** Synthetic dedicated DB | Eliminates privacy concern at the source |
| 2 | Capture flow | **A** CLI `istefox-dt-mcp record-cassette` | Honors ADR-0005 prescribed name; no new infra |
| 3 | Initial scope | **A** All 6 cassettes regenerated in 1 PR | Clean state; no synthetic+real mixing |
| 4 | Sanitization | **B** UUID + names + paths | Defense in depth even with synthetic DB |
