# scripts/

Operational helpers for `istefox-dt-mcp`.

## `smoke_e2e.sh`

Final pre-tag smoke test (Tier 4). Exercises the actually-installed binary
via `uv run istefox-dt-mcp` rather than the test suite, so it catches
packaging and runtime-only regressions that unit tests cannot see.

**Steps:**

1. **Doctor** — `istefox-dt-mcp doctor` reports `dt_running` and `bridge_ready`.
2. **Raw JXA** — `osascript` calls `Application("DEVONthink").databases().length`
   directly to validate the AppleEvents path (independent of MCP).
3. **Audit log** — verifies `~/.local/share/istefox-dt-mcp/audit.sqlite` exists
   and has at least one row created today.
4. **Bundle artifact** — checks `dist/istefox-dt-mcp-<version>.mcpb` exists for
   the current version (warning, not failure — soft hint to run `build_mcpb.sh`).
5. **Server lifecycle** — spawns `serve`, sends an `initialize` request, waits
   up to 5s for a response, then closes stdin and verifies the process exits
   within 3s.

**Prerequisites:**

- DEVONthink 4 running with at least one open database
- AppleEvents permission granted to the terminal running the script
- `uv`, `osascript`, `python3`, `sqlite3` on `PATH`

**Usage:**

```sh
./scripts/smoke_e2e.sh
```

Exit codes: `0` pass, `1` doctor/JXA/audit failure, `2` server lifecycle failure.

**Run before every release tag.** If anything fails, do NOT tag.

## Other scripts

- `build_mcpb.sh` — packages the `.mcpb` desktop extension into `dist/`.
- `smoke_e2e.py` — Python latency smoke (W2 GO/NO-GO checkpoint, p95 targets).
- `benchmark_embeddings.py` — embedding-model throughput comparison.
- `spike_chromadb_stress.py` — ChromaDB stress spike for the sidecar design.
