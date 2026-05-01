# Changelog

Tutti i cambiamenti rilevanti a `istefox-dt-mcp` sono documentati qui.
Formato: [Keep a Changelog](https://keepachangelog.com/it/1.1.0/), versioning [SemVer](https://semver.org/lang/it/).

## [Unreleased]

### Added
- (W3+) Pool worker JXA con benchmark p95
- (W3+) Pydantic schemas estesi per write tool
- (W4+) `ask_database` BM25 mode
- (W5-6) RAG same-process (ChromaDB + bge-m3) — `ADR-003`
- (W7) `file_document` con `dry_run` mandatory + audit before_state
- (W9) Test strategy completa — `ADR-005`
- (W11) Packaging `pipx` + `.mcpb`

---

## [0.0.1] — 2026-04-30 — Foundations W1-W2

### Added
- Scaffold monorepo `uv` workspace: `apps/server`, `apps/sidecar`, `libs/adapter`, `libs/schemas`
- ADR formali: 0001 (stack), 0002 (bridge), 0003 (RAG), 0004 (MVP scope), 0005 (test strategy), 0007 (DT4-only)
- Bridge layer JXA-only:
  - `DEVONthinkAdapter` ABC astratta (multi-bridge ready)
  - `JXAAdapter`: pool semaphore (default 4), timeout 5s, retry exponential backoff (max 3)
  - `SQLiteCache` WAL con TTL per categoria
  - Tassonomia errori strutturati (`AdapterError`, 11 sotto-classi)
  - Script JXA template: `list_databases.js`, `get_record.js`, `search_bm25.js`, `find_related.js`, `apply_tag.js`, `move_record.js`
- Schemi Pydantic v2 (`libs/schemas`):
  - Domain: `Database`, `Record`, `SearchResult`, `RelatedResult`, `TagResult`, `MoveResult`, `HealthStatus`, `Envelope`
  - Tool I/O: `ListDatabases`, `Search`, `FindRelated`, `AskDatabase`, `FileDocument`
  - Audit: `AuditEntry`
  - Errors: `ErrorCode` enum, `StructuredError`
- Server core (`apps/server`):
  - FastMCP 3.x bootstrap con 3 tool read-only registrati
  - `safe_call` wrapper (audit + i18n + duration + envelope)
  - Audit log SQLite append-only con trigger anti-modifica
  - i18n italiano via `locales/it.toml` (11 codici tradotti)
  - structlog JSON su stderr (mai stdout)
  - CLI Click: `istefox-dt-mcp serve|doctor`
- Test:
  - 43 test unit, 100% pass
  - Coverage: schemas 100%, adapter cache 96%, audit (server) 96%, i18n 100%, tools/_common 100%
- CI minima:
  - `.github/workflows/ci.yml` ubuntu (ruff + black + pytest)
  - `.github/workflows/integration.yml` macos-14 (manual trigger placeholder)
  - `.github/workflows/release.yml` (placeholder W11)
- Documentazione: README aggiornato, `docs/architecture.md`, ADR

### Decisions
- Repo GitHub privato `istefox/istefox-dt-mcp`
- MVP 5 tool (read-only `list_databases`, `search`, `find_related`, `ask_database` + write `file_document`)
- HTTP transport + OAuth → v2 (single-device v1)
- Tool description in inglese, error messages user-facing in italiano

### Pending (W2 verification)
- Smoke JXA reale su DT4 (richiede DT in esecuzione)
- Spike costi CI macOS GHA (1 giorno) → input ADR-005 finalizzazione
- Spike stress-test ChromaDB (1-2 giorni) → input ADR-003 finalizzazione
- Spike licenza fixture DT (`.dtBase2` committable?) → input ADR-005

---

[Unreleased]: https://github.com/istefox/istefox-dt-mcp/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/istefox/istefox-dt-mcp/releases/tag/v0.0.1
