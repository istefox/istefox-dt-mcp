# Architecture overview

Vista corrente dell'architettura **dopo W1-W2**, allineata agli ADR consolidati.
Riferimento storico: [`ARCH-BRIEF-DT-MCP.md`](../ARCH-BRIEF-DT-MCP.md), [`docs/adr/REVIEW_ADR.md`](adr/REVIEW_ADR.md).

---

## Vista a layer (post-review)

```
┌──────────────────────────────────────────────────────────────┐
│ Tier 1 — Client AI                                           │
│ Claude Desktop (stdio)                                       │
│ HTTP/OAuth → v2 (rinviato)                                   │
└────────────────────┬─────────────────────────────────────────┘
                     │ JSON-RPC 2.0 (stdio)
┌────────────────────┴─────────────────────────────────────────┐
│ Tier 2 — Transport                                           │
│  stdio (FastMCP run) — solo v1                               │
└────────────────────┬─────────────────────────────────────────┘
                     │
┌────────────────────┴─────────────────────────────────────────┐
│ Tier 3 — MCP Capabilities                                    │
│  Tools registrati: list_databases, search, find_related      │
│  (ask_database, file_document → schema pronto, impl W5/W7)   │
└────────────────────┬─────────────────────────────────────────┘
                     │
┌────────────────────┴─────────────────────────────────────────┐
│ Tier 4 — Service layer (apps/server)                         │
│  - safe_call wrapper (audit + i18n + duration + envelope)    │
│  - structured logging (structlog → stderr JSON)              │
│  - audit log SQLite append-only                              │
│  - i18n (errori italiano via locales/it.toml)                │
└────────────────────┬─────────────────────────────────────────┘
                     │
┌────────────────────┴─────────────────────────────────────────┐
│ Tier 5 — Bridge adapter (libs/adapter)                       │
│  - DEVONthinkAdapter ABC (multi-bridge ready)                │
│  - JXAAdapter: pool semaphore + retry + timeout              │
│  - SQLite WAL cache con TTL per categoria                    │
│  - Tassonomia errori strutturati con recovery_hint           │
│  - Script JXA in scripts/*.js (param via argv positional)    │
└────────────────────┬─────────────────────────────────────────┘
                     │ osascript -l JavaScript
┌────────────────────┴─────────────────────────────────────────┐
│ Tier 6 — Target                                              │
│  DEVONthink 4 (macOS, locale, in esecuzione)                 │
└──────────────────────────────────────────────────────────────┘
```

---

## Flusso di una chiamata `search`

1. Client (Claude Desktop) invia JSON-RPC `tools/call` con name=`search`.
2. FastMCP valida l'input contro `SearchInput` (Pydantic v2).
3. Il tool wrapper (`safe_call`) avvia il timer, invoca il bridge.
4. `JXAAdapter.search(...)` acquisisce il semaphore, spawn `osascript`, attende output JSON con timeout.
5. Output JXA parseato, validato contro `SearchResult`.
6. `safe_call` registra l'entry nell'`audit_log` (success o failure), ritorna `SearchOutput` envelope al client.
7. Logging strutturato emesso su stderr (mai stdout — corromperebbe stdio).

In caso di errore: `AdapterError` catturato, tradotto via `Translator` (it.toml), persistito nell'audit log con `error_code`, ritornato al client come envelope `success=False` con `recovery_hint` italiano.

---

## Componenti cross-cutting

### Audit log (`apps/server/audit.py`)

- SQLite append-only, location `~/.local/share/istefox-dt-mcp/audit.sqlite`
- Trigger SQL `BEFORE UPDATE` e `BEFORE DELETE` impediscono modifiche ex-post
- Schema: `audit_id, ts, principal, tool_name, input_json, output_hash, duration_ms, before_state, error_code`
- Hash output via SHA-256 su JSON sortato (deterministic)
- Retention configurabile (default 90 giorni — non ancora implementato)

### Cache (`libs/adapter/cache.py`)

- SQLite WAL, location `~/.local/share/istefox-dt-mcp/cache.sqlite`
- TTL per chiave (default 60s, override per categoria)
- `invalidate(key)`, `invalidate_prefix(prefix)`, `purge_expired()`
- Categorie attuali: `list_databases` (300s), `record:<uuid>` (invalidate on write)

### i18n (`apps/server/i18n.py`)

- Tool description, field doc, error code: **inglese** (LLM tool selection ottimizzata in EN)
- Messaggi user-facing (error_message + recovery_hint nell'envelope): **italiano** (locales/it.toml)
- Trigger: ogni `safe_call` failure → `Translator.message_it(code)` + `recovery_hint_it(code)`

### Logging (`apps/server/logging.py`)

- structlog → JSON su stderr (mai stdout)
- Schema: `{ts, level, event, tool, duration_ms, audit_id, error?}`
- Configurabile via `--log-level` (debug/info/warning/error)

---

## Decisioni rinviate (post-W2)

- **W3-W4**: Pydantic schemas extension, `ask_database` (BM25), structured logging refinement
- **W5-W6**: RAG same-process (ChromaDB + bge-m3), hybrid search, smart rule sync
- **W7**: `file_document` con dry_run, audit con before_state, undo
- **W8**: HTTP transport + OAuth (rinviato a v2 secondo decisione utente)
- **W9-W11**: Test strategy completa (Tier 2-3-4), OTel tracing, performance benchmark, packaging
- **W12**: `.mcpb` packaging, hardening, documentazione utente

Vedi [`docs/adr/REVIEW_ADR.md` §6](adr/REVIEW_ADR.md) per la roadmap revised.

---

## ADR consolidati (W1-W2)

| # | Titolo | Status |
|---|---|---|
| [0001](adr/0001-stack-python-fastmcp-chromadb.md) | Stack tecnologico | Accepted |
| [0002](adr/0002-bridge-architecture-jxa-only.md) | Bridge JXA-only v1 | Accepted |
| [0003](adr/0003-rag-same-process.md) | RAG same-process | Accepted (con spike) |
| [0004](adr/0004-mvp-tool-scope.md) | MVP 5 tool | Accepted |
| [0005](adr/0005-test-strategy-4-tier.md) | Test strategy 4-tier | Accepted (con spike) |
| [0007](adr/0007-dt4-only.md) | DT4-only, drop DT3 | Accepted |

ADR-006 (OAuth scope), ADR-008 (embedding model), ADR-009 (vector DB migration), ADR-010 (distribution), ADR-011 (telemetry), ADR-012 (i18n), ADR-013 (concurrency), ADR-014 (rate limiting) → da scrivere alle settimane indicate in REVIEW_ADR §7.
