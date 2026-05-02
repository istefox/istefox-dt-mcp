# istefox-dt-mcp

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Platform: macOS](https://img.shields.io/badge/platform-macOS-lightgrey.svg)](https://www.apple.com/macos/)
[![Release: v0.1.0](https://img.shields.io/badge/release-v0.1.0-brightgreen.svg)](https://github.com/istefox/istefox-dt-mcp/releases/latest)

MCP server for DEVONthink 4 — outcome-oriented tools, optional local RAG, privacy-first. Stack: Python 3.12 + FastMCP + ChromaDB + uv.

> **0.1.0 — first public release (May 2026)**. Six MCP tools end-to-end, preview-then-apply with audit log + selective undo, `.mcpb` bundle installable in Claude Desktop. Vector RAG is opt-in experimental — see [ADR-008](docs/adr/0008-embedding-model-selection.md). For day-to-day status, see [`handoff.md`](handoff.md); for project constraints, see [`CLAUDE.md`](CLAUDE.md); for design decisions, see [`docs/adr/`](docs/adr/).

---

## Quick Install (3 ways)

| Path | Best for | Prerequisites |
|---|---|---|
| **A — `.mcpb` desktop extension** (recommended) | Claude Desktop users, zero-config | Claude Desktop ≥ 0.8 |
| **B — `pipx install`** (standalone CLI) | CLI users, other MCP hosts | Python 3.12, `pipx` |
| **C — Source / dev install** | Contributors, debugging | `uv`, `git` |

### A — `.mcpb` desktop extension (recommended)

Drag-and-drop into Claude Desktop, one-click. The bundle handles its own runtime and dependencies.

1. Download the latest `.mcpb` from [GitHub Releases](https://github.com/istefox/istefox-dt-mcp/releases/latest).
2. Drag it onto the Claude Desktop window (or **Settings → Developer → Install Bundle**).
3. On first use, macOS will ask for AppleEvents permission — click **Allow**.

### B — `pipx install` (standalone CLI)

```bash
pipx install git+https://github.com/istefox/istefox-dt-mcp
```

Then add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "istefox-dt-mcp": {
      "command": "istefox-dt-mcp",
      "args": ["serve"]
    }
  }
}
```

### C — Source / dev install

```bash
git clone https://github.com/istefox/istefox-dt-mcp.git
cd istefox-dt-mcp
uv sync --all-packages
uv run istefox-dt-mcp doctor
```

See [Setup](#setup) for full details (macOS permissions, install troubleshooting).

<!-- TODO before next release:
     - docs/assets/install.gif (Claude Desktop install of .mcpb, ~5s loop, ≤5MB)
     - docs/assets/demo.gif (chat → file_document preview → apply → undo, ~15s)
     - docs/assets/architecture.svg (layered architecture diagram)
     Capture: kap.app or Gifox; optimize: gifsicle -O3
-->

---

## Prerequisites

- **macOS 14+** (Sonoma or later)
- **DEVONthink 4** (Pro or standard, any license) installed and running
- **Disk space**: ~300 MB for the bundle, **+2 GB** if you enable RAG with `bge-m3`
- **AppleEvents permission** for the terminal (pipx/dev) or for Claude Desktop (`.mcpb`) — requested automatically on first use

---

## What you can ask Claude

Examples of natural prompts and the MCP tool each one triggers. All examples assume Claude Desktop with the connector installed and DEVONthink running.

- *"Find everything about 'antivibration mounts' from the last 2 years"*
  → `search` (BM25 by default; hybrid if RAG is enabled)
- *"What did we propose to Customer X?"*
  → `ask_database` (BM25 + synthesis; vector if RAG opt-in is on — see [RAG](#rag-vector-search--opt-in-experimental))
- *"Find documents similar to this PDF"* (with a record selected in DT)
  → `find_related` (DT's native See Also/Compare)
- *"File this attachment in `/Inbox/Triage` and tag it `urgent`"*
  → `file_document` with preview, shows what it will do, then commit with `confirm_token`
- *"Move every March PDF from the `Inbox` to `/Archive/2026`"*
  → `bulk_apply` (batch dry-run + per-record selective apply)
- *"Which databases are open in DT?"*
  → `list_databases` (read-only, 5-min cache)

Write tools (`file_document`, `bulk_apply`) are **dry-run by default**: the first call always returns a preview. Apply requires an explicit `confirm_token`. The returned `audit_id` enables selective `undo` via the CLI.

<!-- TODO before next release:
     - docs/assets/demo.gif belongs here (chat → file_document preview → apply → undo)
-->

---

## Privacy & security

The connector is designed **privacy-first** and **local-only**:

- **Everything stays on your machine**: no data leaves it. No telemetry, no cloud embeddings, no analytics. The embedding model (if you enable RAG) runs locally via `sentence-transformers`.
- **Append-only SQLite audit log** for **every** operation (reads included) at `~/.local/share/istefox-dt-mcp/audit.sqlite`. Default 90-day retention, configurable.
- **Write tools always default to `dry_run=true`**, with a preview-then-apply pattern guarded by a short-TTL `confirm_token` (5 min default).
- **Selective undo via `audit_id`**: every write op stores the before-state and is restorable with `istefox-dt-mcp undo <audit_id>`.
- **Clean-room implementation**, **MIT license**: no code copied from GPL-licensed projects (see [Legal constraints](#legal-constraints)).
- **Suitable for sensitive data**: contracts, invoices, personal notes, customer correspondence.

---

## Roadmap

| Version | What | References |
|---|---|---|
| **0.1.0** (this release, May 2026) | 6 MCP tools, audit + undo, `.mcpb` bundle, BM25-only retrieval by default | — |
| **0.2.0** (Q3 2026) | RAG benchmark cross-corpus + flip default model, 3-state drift detection | [ADR-008](docs/adr/0008-embedding-model-selection.md) |
| **0.3.0+** (Q4 2026) | HTTP transport + OAuth multi-device, additional tools (`summarize_topic`, `create_smart_rule`) | [ADR-004](docs/adr/0004-mvp-tool-scope.md) |

Full backlog in [`handoff.md`](handoff.md).

---

## Troubleshooting top 5

| Error | Symptom | Fix |
|---|---|---|
| `DT_NOT_RUNNING` | All tools fail at startup | DEVONthink isn't running — launch it (Spotlight: `DEVONthink`) |
| `PERMISSION_DENIED` (`-1743`) | First Apple Event errors out | **System Settings → Privacy & Security → Automation** → enable the toggle for `DEVONthink` under your terminal or Claude Desktop |
| `DATABASE_NOT_FOUND` | `file_document` or `bulk_apply` rejects the path | `destination_hint` is missing the database prefix — use `/Inbox/<group>` (with leading slash), not `/<group>` |
| `uv binary not found` | The `.mcpb` bundle won't start on first run | `brew install uv` (or `curl -LsSf https://astral.sh/uv/install.sh \| sh`), then disable + re-enable the extension in Claude Desktop |
| `drift_detected: true` (on undo) | Undo refuses to roll back | The record was modified after the original apply. Run `istefox-dt-mcp audit list --recent` for context, then add `--force` if the rollback is still what you want |

For anything not listed: `uv run istefox-dt-mcp doctor` produces a full diagnostic report (DT running, permissions, cache, RAG state).

---

## Status

**0.1.0 first public release**: 6 MCP tools end-to-end, validated in Claude Desktop with real data. **163 unit + contract tests** green. `.mcpb` bundle distributable. Audit log + selective undo working. CI on Ubuntu (lint + mypy + unit + contract) and macOS-14 (import + bundle smoke + nightly).

---

## What it does

A DEVONthink 4 connector for MCP that goes beyond a 1:1 wrapper of the scripting dictionary.

**The six tools:**

| Tool | Type | Notes |
|---|---|---|
| `list_databases` | read | Open databases, with 5-min cache |
| `search` | read | BM25 (default) + optional vector hybrid (RRF) when RAG is enabled |
| `find_related` | read | Wraps DT's native See Also / Compare |
| `ask_database` | read | BM25 + synthesis (default) + optional vector retrieval |
| `file_document` | write | `dry_run` by default + preview-then-apply + selective undo |
| `bulk_apply` | write | Batch ops with `dry_run` + per-op outcomes |

The two write tools follow the preview-then-apply pattern: calling them with `dry_run=true` returns a preview plus a `preview_token` (the audit_id of the dry-run); a second call with `dry_run=false` plus `confirm_token=<preview_token>` actually applies the change. The returned `audit_id` enables selective `undo` via the CLI.

Out of MVP scope (post-0.1.0): `summarize_topic`, `create_smart_rule` — see [ADR-004](docs/adr/0004-mvp-tool-scope.md).

---

## Stack

| Component | Tech | Reference |
|---|---|---|
| Language | Python 3.12 | [ADR-001](docs/adr/0001-stack-python-fastmcp-chromadb.md) |
| MCP framework | FastMCP 3.x | [ADR-001](docs/adr/0001-stack-python-fastmcp-chromadb.md) |
| Validation | Pydantic v2 | [ADR-001](docs/adr/0001-stack-python-fastmcp-chromadb.md) |
| DT bridge | JXA-only in v1 (multi-bridge-ready abstraction) | [ADR-002](docs/adr/0002-bridge-architecture-jxa-only.md) |
| Vector DB | ChromaDB embedded | [ADR-003](docs/adr/0003-rag-same-process.md) |
| Embedding | `paraphrase-multilingual-MiniLM-L12-v2` (default), `BAAI/bge-m3` opt-in | [ADR-008](docs/adr/0008-embedding-model-selection.md) |
| Cache | SQLite WAL | — |
| Tests | pytest + 4-tier strategy | [ADR-005](docs/adr/0005-test-strategy-4-tier.md) |
| Packaging | `uv` workspace + hatchling | — |
| Logging | structlog (JSON to stderr) | — |
| Distribution | `pipx` + `.mcpb` desktop extension | — |

Minimum DT version: **DEVONthink 4.0**. DT3 is not supported — see [ADR-007](docs/adr/0007-dt4-only.md).

---

## Repository structure

```
.
├── apps/
│   ├── server/      MCP server (FastMCP, stdio in v1; HTTP+OAuth → v2)
│   └── sidecar/     RAG sidecar (ChromaDB + embeddings)
├── libs/
│   ├── adapter/     JXA bridge + cache + errors + JXA scripts
│   └── schemas/     Shared Pydantic v2 models (common, tools, audit, errors)
├── tests/
│   ├── unit/        Unit tests (157 tests)
│   ├── contract/    VCR-style replay against captured JXA outputs (6 tests)
│   ├── integration/ Real-DT smoke + latency benchmark (7 tests, opt-in)
│   └── benchmark/   Micro-benchmarks (opt-in)
├── docs/
│   └── adr/         Architecture decision records
├── .github/workflows/   CI (Ubuntu) + Integration (macOS-14) + Release (manual) + Publish-Registry
├── scripts/             build_mcpb.sh + smoke_e2e.sh
├── server.json          MCP Registry manifest
├── manifest.json        .mcpb bundle manifest
├── pyproject.toml       uv workspace + ruff + black + mypy + pytest
├── CLAUDE.md            Mandatory project constraints
├── memory.md            Decisions + context
└── handoff.md           Session-to-session handover
```

---

## Setup

```bash
# Prerequisites: macOS, DEVONthink 4 installed

# Install uv (if missing — alternative: brew install uv)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone + sync workspace
git clone https://github.com/istefox/istefox-dt-mcp.git
cd istefox-dt-mcp
uv sync --all-packages
```

### macOS Automation permission (mandatory)

DEVONthink only responds to Apple Events from apps that have explicit permission. On the first `uv run istefox-dt-mcp doctor` with DT running, macOS will show a "X wants to control DEVONthink" dialog: click **OK**.

If you don't see the dialog (because you clicked "Don't Allow" earlier):

1. Open **System Settings → Privacy & Security → Automation**.
2. Find the terminal or app you're running from (Warp, iTerm, Terminal, Claude Desktop).
3. Enable the toggle for **DEVONthink**.

Typical error when permission is denied: `PERMISSION_DENIED` with AppleScript code `-1743`. The connector intercepts it and suggests the affected app in the `recovery_hint`.

If your terminal doesn't appear in the Automation list, try `tccutil reset AppleEvents <bundle-id>` (e.g. `com.apple.Terminal`, `com.googlecode.iterm2`) and re-run the probe so macOS can prompt fresh.

---

## Quick start

```bash
# Lint + format check
uv run ruff check .
uv run black --check .

# Unit + contract tests (~6s)
uv run pytest tests/unit tests/contract -v

# Tests with coverage
uv run pytest tests/unit --cov=apps --cov=libs --cov-report=term

# Integration tests against real DT (opt-in; requires DT running + AppleEvents)
uv run pytest tests/integration -m integration --benchmark-enable -v

# Micro-benchmarks (opt-in: cache + bridge overhead)
uv run pytest tests/benchmark --benchmark-enable --benchmark-only

# CLI
uv run istefox-dt-mcp --help
uv run istefox-dt-mcp doctor       # health check (requires DT running)
uv run istefox-dt-mcp serve        # stdio server (for Claude Desktop)
uv run istefox-dt-mcp audit list --recent 5   # last 5 audit entries
```

## Performance tuning (env vars)

| Variable | Default | Effect |
|---|---|---|
| `ISTEFOX_FAST_LIST_DATABASES` | `false` | If truthy (`1`/`true`/`yes`/`on`): `list_databases` skips computing `record_count` (returns `null`). Useful on databases with tens of thousands of records, where `d.contents().length` can take seconds on the first call (the 5-min cache amortizes subsequent calls). Default: count included, behavior unchanged. |
| `ISTEFOX_PREVIEW_TTL_S` | `300` | Override TTL in seconds for `preview_token` (default 5 minutes). Valid range: 1–3600. |
| `ISTEFOX_RAG_ENABLED` | `false` | If truthy: enables the vector RAG provider (see next section). |
| `ISTEFOX_RAG_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | Override the embedding model (e.g. `BAAI/bge-m3`). Only used when RAG is enabled. |

**For `.mcpb` installs (Claude Desktop)**: since v0.0.22 these four variables are configurable from the Claude Desktop UI without editing files. Open **Settings → Extensions → istefox-dt-mcp → Configure** and you'll see a form with human-readable labels for each option. Edit + Save + restart the server.

**For `pipx`/dev installs**: set the env vars in your shell profile (`~/.zshrc`) or in the launch command.

## RAG (vector search) — opt-in **experimental**

> **⚠️ Experimental in 0.1.0**: the RAG code is complete and unit-tested, but the embedding model default has not been validated cross-corpus yet. See [ADR-008](docs/adr/0008-embedding-model-selection.md) for the criteria to promote it as the 0.2.0 default. If you enable RAG now, be aware that quality depends heavily on your corpus — feedback via GitHub issues is very welcome.

The server runs in BM25-only mode by default (zero overhead, no models to download). To enable vector search:

```bash
# 1. Enable the RAG provider (env var)
export ISTEFOX_RAG_ENABLED=1

# 2. (Optional) Override the model — default is MiniLM-L12-v2
export ISTEFOX_RAG_MODEL=BAAI/bge-m3   # ~2.2 GB, higher quality

# 3. Index a DT database (one-shot — automatic sync covered below)
uv run istefox-dt-mcp reindex <your-database-name>
uv run istefox-dt-mcp reindex <your-database-name> --limit 100   # partial test

# 4. Verify the index
uv run istefox-dt-mcp doctor
# {... "rag": {"indexed_count": N, "embedding_model": "..."}}

# 5. Start the server and use search mode=hybrid or ask_database
uv run istefox-dt-mcp serve
```

ChromaDB is embedded and persisted at `~/.local/share/istefox-dt-mcp/vectors/`. Lazy load: the model is downloaded/loaded on the first call to `search` or `ask_database` in semantic mode, not at startup.

### Automatic sync (opt-in)

For real-time incremental indexing via DT4 smart rules + periodic reconciliation:

```bash
# 1. (Optional) generate a webhook token
export ISTEFOX_WEBHOOK_TOKEN="$(openssl rand -hex 16)"

# 2. Start the daemon
uv run istefox-dt-mcp watch \
    --port 27205 \
    --databases <your-database-name> \
    --reconcile-interval-s 21600   # every 6h

# 3. Configure the DT4 smart rule (see docs/smart-rules/sync_rag.md)
# 4. Manual reconciliation now and then:
uv run istefox-dt-mcp reconcile <your-database-name>
```

For auto-start at boot: see `docs/smart-rules/sync_rag.md` §"launchd auto-start".

---

## Claude Desktop integration (dev)

For end users, see [Quick Install](#quick-install-3-ways). This section covers the dev workflow (bundle build and manual config for source installs).

**Build the `.mcpb` bundle** (only requires `bash + zip + unzip`):

```bash
./scripts/build_mcpb.sh
# Output: dist/istefox-dt-mcp-<version>.mcpb (~290 KB)
```

The bundle uses `server.type=python` with a bash wrapper (`bundle_main.sh`) that detects `uv` across common install locations (Homebrew, cargo, pipx, mise, asdf, plus the `ISTEFOX_UV_BIN` override). Claude Desktop manages the runtime lifecycle.

**Manual `claude_desktop_config.json` (source install)**:

```json
{
  "mcpServers": {
    "istefox-dt-mcp": {
      "command": "uv",
      "args": ["--directory", "/path/to/istefox-dt-mcp", "run", "istefox-dt-mcp", "serve"]
    }
  }
}
```

Path: `~/Library/Application Support/Claude/claude_desktop_config.json`. Restart Claude Desktop. All six tools become available.

> RAG and other options: via env vars in the process that launches `claude` (manual config) or via the **Settings → Extensions → Configure** UI for the bundle (since v0.0.22).

---

## Key documents

| File | Contents |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Mandatory project constraints (legal, MCP, DT, safety) |
| [`memory.md`](memory.md) | Consolidated decisions + open questions + context |
| [`handoff.md`](handoff.md) | Current state + next steps |
| [`docs/architecture.md`](docs/architecture.md) | Layered overview of the solution |
| [`docs/adr/`](docs/adr/) | Architecture decision records (stack, bridge, sidecar, MVP, tests, DT4, RAG model) |
| [`docs/adr/REVIEW_ADR.md`](docs/adr/REVIEW_ADR.md) | Architecture review v1.0 (input to the formal ADRs) |
| [`ARCH-BRIEF-DT-MCP.md`](ARCH-BRIEF-DT-MCP.md) | Original architecture brief v0.1 (historical source of truth) |

<!-- TODO before next release:
     - docs/assets/architecture.svg belongs here (layered diagram of the solution)
-->

---

## Legal constraints

- **Clean-room implementation**: no code copied from [`dvcrn/mcp-server-devonthink`](https://github.com/dvcrn/mcp-server-devonthink) (GPL-3.0).
- **Privacy by design**: no user data leaves the machine by default. Embeddings are generated locally; the audit log is local.
- **Personal namespace**: `istefox` (this is a personal project, not a work project).

---

## License

[MIT License](LICENSE) © 2026 Stefano Ferri.

You may use, modify, and redistribute the code (including commercially) as long as you keep the copyright notice. See [`LICENSE`](LICENSE) for the full text.
