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
