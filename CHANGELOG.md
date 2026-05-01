# Changelog

Tutti i cambiamenti rilevanti a `istefox-dt-mcp` sono documentati qui.
Formato: [Keep a Changelog](https://keepachangelog.com/it/1.1.0/), versioning [SemVer](https://semver.org/lang/it/).

## [Unreleased]

### Added
- (W9) Test strategy completa Tier 2-4 — `ADR-005`
- (W11) Packaging `pipx` + `.mcpb`
- (post-MVP) After-state esplicito nell'audit log
- (post-MVP) Multi-step undo (chain audit_ids)
- (post-MVP) ADR-008 model selection benchmark MiniLM vs bge-m3

---

## [0.0.9] — 2026-05-01 — W9: hard preview_token enforcement con TTL

### Added
- **Hard enforcement del `confirm_token`** sui tool `file_document` e
  `bulk_apply`. Il flow apply (`dry_run=false`) ora rifiuta con
  `INVALID_PREVIEW_TOKEN` qualunque chiamata che non passi un token
  valido.
- **TTL 5 minuti** di default per i preview_token. Override via env
  var `ISTEFOX_PREVIEW_TTL_S=<secondi>` per script/test. Token
  scaduti rifiutati con `EXPIRED_PREVIEW_TOKEN`.
- **One-shot consumption**: un token può essere applicato esattamente
  una volta. Replay rifiutato con `CONSUMED_PREVIEW_TOKEN`.
- **Cross-tool isolation**: un token di `file_document` non può
  essere usato per applicare `bulk_apply` (e viceversa). Anche un
  token che riferisce un'apply (non un preview) viene rifiutato.
- Nuovi `ErrorCode`: `INVALID_PREVIEW_TOKEN`, `EXPIRED_PREVIEW_TOKEN`,
  `CONSUMED_PREVIEW_TOKEN` con messaggi italiani + recovery hint
  in `locales/it.toml`.
- Nuove eccezioni adapter: `InvalidPreviewTokenError`,
  `ExpiredPreviewTokenError`, `ConsumedPreviewTokenError` (sotto
  `AdapterError` per riusare la pipeline `safe_call` → envelope
  strutturato → translator i18n).
- **Tabella `preview_consumption`** append-only nello schema audit
  SQLite. PRIMARY KEY su `audit_id` garantisce atomicità e
  protezione race-condition. Trigger anti-UPDATE/DELETE come per
  `audit_log`. Mantiene `audit_log` 100% immutabile.
- `AuditLog.is_consumed(audit_id)` e `AuditLog.mark_consumed(audit_id)`.
- Helper condiviso `validate_confirm_token()` in `tools/_common.py`.

### Changed
- I docstring di `file_document` e `bulk_apply` aggiornati per
  riflettere l'enforcement (era "advisory in v0.0.7/0.0.8").
- Server bumped a v0.0.9.
- Test esistenti aggiornati: i test apply ora prima fanno un
  preview (per ottenere un token valido) e poi l'apply.

### Verified
- 127 test unit pass (era 121 W8, +6 nuovi: 4 file_document, 2 bulk_apply
  per casi token rejection)
- mypy strict + ruff + black puliti

---

## [0.0.8] — 2026-05-01 — W8: bulk_apply tool

### Added
- **`bulk_apply` MCP tool** (write batch, dry-run by default):
  - **Preview-then-apply** flow uguale a `file_document`:
    `dry_run=true` ritorna `BulkApplyResult` con `outcomes` (status
    `planned`/`failed`) + `preview_token` (audit_id). `dry_run=false`
    + `confirm_token=<token>` esegue gli op in ordine.
  - **Op supportati**: `add_tag` (payload `{tag}`), `remove_tag`
    (payload `{tag}`), `move` (payload `{destination}`).
  - **Failure semantics**: DEVONthink non ha transactions, quindi
    no auto-rollback. Default `stop_on_first_error=true` —
    halt al primo errore, `failed_index` riporta l'op fallita,
    `outcomes` riporta status per-op (`applied`/`failed`/`planned`).
    Con `stop_on_first_error=false` continua sugli errori.
  - **Limite batch**: max 500 op per chiamata.
  - **Validation pre-adapter**: op type sconosciuto o payload mancante
    diventano `failed` con `INVALID_INPUT` senza chiamare l'adapter.
  - **Audit `before_state`**: snapshot della lista ops con
    `{uuid, op, payload}` (no per-op record snapshot — bilanciamento
    spazio/utilità; selective undo per-op è post-MVP).
- **Schema esteso**: `BulkOpOutcome` (index, record_uuid, op, status,
  error_code, error_message), `BulkApplyResult.outcomes: list[...]`.

### Changed
- Server registra ora **6 MCP tool** (era 5): aggiunto `bulk_apply`.
- `BulkApplyInput` docstring riformulato: rimossa promessa di
  rollback atomico (non implementabile su DT4).

### Verified
- 121 test unit pass (112 W7 + 9 nuovi `test_bulk_apply.py`)
- mypy strict + ruff + black puliti

---

## [0.0.7] — 2026-05-01 — W7: file_document write tool + undo

### Added
- **`file_document` MCP tool** (write, dry-run by default):
  - **Preview-then-apply** flow: `dry_run=true` ritorna
    `FileDocumentPreview` + `preview_token` (audit_id)
  - Apply: `dry_run=false` (+ optional `confirm_token`) muove record
    + applica tag suggeriti. `confirm_token` advisory in v0.0.7
    (warning se mancante; hard enforcement post-MVP).
  - Logica preview: `destination_hint` override → DT4 native
    `classify_record` → no-op se classifica suggerisce posizione
    corrente. Tag heuristic: leaf segment della destination.
- **`adapter.classify_record(uuid, top_n)`** nel `DEVONthinkAdapter`
  ABC + impl `JXAAdapter` + script JXA `classify.js` defensive
  (wraps `DT.classify({record:r})`).
- **`adapter.remove_tag(uuid, tag, dry_run)`** nuovo metodo +
  script JXA `remove_tag.js`. Necessario per supportare undo
  (rimuove i tag aggiunti dal `file_document`).
- **`safe_call` accetta `before_state`** opzionale: write tools
  passano uno snapshot `{uuid, location, tags, name}` che viene
  persistito nell'audit log per undo selettivo.
- **`undo_audit(audit_id, dry_run, force)`** in `apps/server/undo.py`:
  - Legge audit entry + before_state
  - Drift detection: se record è stato modificato dopo l'op
    originale, blocca con `drift_detected=True` (override `--force`)
  - Reverse: move back + remove tags aggiunti
- **`undo <audit_id>` CLI command** con `--apply` (default dry-run)
  e `--force` (bypass drift check).

### Changed
- `safe_call` signature: aggiunto `before_state: dict[str, Any] | None`
- Server registra ora **5 MCP tool** (era 4): aggiunto `file_document`

### Verified
- 112 test unit pass (100 W6 + 12 nuovi: 6 file_document, 6 undo)
- mypy strict + ruff + black puliti

### Pending post-MVP
- `bulk_apply` impl (schema già pronto da W4)
- Hard enforcement `confirm_token` (TTL su preview tokens)
- After-state esplicito nell'audit (oggi inferito da diff)
- Multi-step undo (chain di audit_id)

---

## [0.0.6] — 2026-05-01 — W6: smart-rule sync + reconciliation

### Added
- **`reconcile_database`** in `apps/server/reindex.py`: walk DT,
  set-diff vs vector store, indicizza nuovi UUID, rimuove orfani.
  Idempotent. Foundation per smart rule + cron notturno.
- **`reconcile <database>` CLI command**: lancia reconciliation
  one-shot, output JSON counters
  `{dt_count, rag_count, indexed, removed, empty_text, errors}`.
- **`RAGProvider.list_uuids() -> set[str]`** nell'ABC + impl in
  `ChromaRAGProvider` (via `collection.get(include=[])` per ridurre
  payload). NoopRAGProvider torna set vuoto.
- **`ChromaRAGProvider.mark_reconciled()`** — aggiorna timestamp
  `last_reconcile_at` esposto via `stats()` e `doctor`.
- **`WebhookListener`** (`apps/server/webhook.py`): HTTP server
  stdlib loopback su `127.0.0.1:27205/sync-event`. Stdlib only,
  zero nuove deps.
  - Bounded queue (1024 events) → asyncio consumer
  - Optional Bearer auth via `ISTEFOX_WEBHOOK_TOKEN` env
  - Schema strict: `{action: created|modified|deleted, uuid, database}`
- **`process_sync_event`** in `apps/server/sync_handler.py`: applica
  un singolo evento webhook al RAG provider (index/remove + metadata
  fetch).
- **`watch` CLI command**: lancia daemon webhook + cron
  reconciliation:
  ```
  istefox-dt-mcp watch \\
      --port 27205 \\
      --databases Business --databases privato \\
      --reconcile-interval-s 21600
  ```
- **Smart rule template DT4** (`docs/smart-rules/sync_rag.md`):
  guida step-by-step utente per configurare 3 smart rule
  (Imported / Modified / Trashed) + AppleScript snippet che POSTa
  al webhook + esempio launchd plist per auto-start.

### Verified
- 100 test unit pass (84 W5 + 16 nuovi: 6 webhook handler, 6
  sync_handler, 4 reconcile)
- mypy strict + ruff + black puliti

### Pending
- ADR-008 model selection benchmark (MiniLM vs bge-m3 su corpus
  reale Stefano)
- Fingerprint-based reconciliation (modification_date diff per
  detectare modifiche, oggi solo set-diff)
- Smart-rule end-to-end test su DT4 reale di Stefano (richiede
  setup utente delle smart rule)

---

## [0.0.5] — 2026-05-01 — W5: ChromaRAGProvider + hybrid search + reindex

### Added
- **`ChromaRAGProvider`** (apps/sidecar) — implementazione concreta
  di `RAGProvider` su ChromaDB embedded (same-process, ADR-003).
  Lazy load del modello + del client (zero overhead startup quando
  RAG disabilitato). Asyncio.Lock su write per ChromaDB thread-safety.
- **Config-driven RAG selection** in `Deps`:
  - `ISTEFOX_RAG_ENABLED=1` attiva ChromaRAGProvider
  - `ISTEFOX_RAG_MODEL=...` override modello (default
    `paraphrase-multilingual-MiniLM-L12-v2`)
  - default = NoopRAGProvider (no overhead, BM25-only)
- **`reindex` CLI command**: `istefox-dt-mcp reindex <database>
  [--limit N] [--batch-size N]` — walk DT con `enumerate_records`
  (nuovo metodo adapter + script JXA `enumerate_db.js`), estrae
  text via `get_record_text`, batch-indexes nel vector store.
- **`enumerate_records(database, limit, offset)`** nel
  `DEVONthinkAdapter` ABC + `JXAAdapter` impl + script JXA defensive
  (DFS iterativo, salta groups/smart groups).
- **Hybrid search RRF** in tool `search`:
  - mode `bm25` (default): solo DT native (come prima)
  - mode `semantic`: solo vector (fallback bm25 se RAG noop)
  - mode `hybrid`: parallel BM25 + vector, fusione via Reciprocal
    Rank Fusion (k=60). Hydration metadata via `get_record` per
    UUID solo-vector.
- **`ask_database` upgraded a vector-first**: usa RAG provider
  per retrieval semantico quando disponibile, fallback BM25 altrimenti.
  Snippet preferito da ChromaDB; metadata da `get_record`.
- **`doctor` espanso** con stato RAG (`indexed_count`, `last_index_at`,
  `embedding_model`).

### Changed
- `Deps` ora ha campo `rag: RAGProvider` obbligatorio (era ABC)
- `apps/server` dipende da `apps/sidecar` (workspace member)
- `ask_database` snippet: prima preferiva DT plain text, ora
  preferisce snippet già fornito da ChromaDB (più veloce, no extra
  JXA call)

### Verified
- 84 test unit pass (68 W4 + 16 nuovi: RRF fusion, search modes,
  reindex, ask_database vector mode)
- mypy strict + ruff + black puliti
- ADR-003 spike PASS (50K record, p95 5.5ms, 0 errori)

### Pending W6
- Smart rule DT4 → webhook locale per sync incrementale
- Reconciliation notturna hash-based (full re-scan)
- Selezione modello finale (ADR-008): MiniLM vs bge-m3 benchmark

---

## [0.0.4] — 2026-05-01 — W4: logging refinement + write schemas + RAG ABC

### Added
- **Structured logging refinement**:
  - `safe_call` ora binda `request_id`, `tool`, `audit_id` al
    `structlog.contextvars` per la durata dell'op (auto-propagati a
    qualunque log nested)
  - Nuovo evento `tool_call_started` (DEBUG) con summary input
    sanitizzato — `query`, `question`, `snippet`, `answer` redatti
    a `<str len=N>` per non leakare contenuti via stderr/log sink
  - `unbind_contextvars` in `finally` previene bleed cross-request
- **Pydantic schemas write tools** (schema only, impl W7+):
  - `FileDocumentInput.confirm_token` + `FileDocumentResult.preview_token`
    (preview-then-apply pattern)
  - `BulkApplyInput`/`BulkApplyOperation`/`BulkApplyResult`
    (atomic batch, dry_run mandatory, max 500 ops)
  - `UndoInput`/`UndoResult` (selective undo via audit_id +
    `drift_detected` flag)
- **RAGProvider ABC** (prep W5-6):
  - `libs/adapter/.../rag.py` con `RAGProvider` ABC + `NoopRAGProvider`
    fallback (registrato come default in `Deps`)
  - `libs/schemas/.../rag.py` con `RAGHit`, `RAGStats`, `RAGFilter`
  - Permette swap a `ChromaRAGProvider` (W5-6) senza refactor server

### Verified
- 68 test unit pass (62 W3 + 6 nuovi RAG/logging/schemas)
- mypy strict + ruff + black puliti

---

## [0.0.3] — 2026-05-01 — `ask_database` BM25 + benchmark baseline

### Added
- **`ask_database` tool** (retrieval-only mode, vector RAG arriva W5-6):
  - BM25 search sulla question, top-N hit + snippet plainText
  - Restituisce `{answer: placeholder, citations: [...]}` — il client
    Claude usa le citations come grounded context per generare la risposta
  - Privacy-first: question/contenuto restano on-device
- **`JXAAdapter.get_record_text(uuid, max_chars)`** + script JXA
  `get_record_text.js` (defensive, gestisce record kind senza testo)
- **Cache UUID-keyed** anche per `get_record_text` (TTL 300s)
- **`pytest-benchmark` baseline** (`tests/benchmark/`, opt-in):
  - bridge inline call ~316 µs, script call ~322 µs (mock subprocess)
  - cache hit ~2.7 µs, miss ~1.7 µs
  - Overhead bridge < 0.2 % rispetto a JXA reale (~200ms)

### Changed
- `DEVONthinkAdapter` ABC estesa con `get_record_text(uuid, *, max_chars)`
- `tests/benchmark/` escluso dalla default test session (opt-in via
  `pytest tests/benchmark --benchmark-enable`)

### Verified
- 51 test unit pass (44 W2 + 7 nuovi su `ask_database` + `get_record_text`)
- mypy strict 0 issues, ruff 0 issues
- 4 benchmark pass

---

## [0.0.2] — 2026-05-01 — W2 GO/NO-GO PASS

### Added
- `AutomationPermissionError` con caller process detection — mappa
  AppleScript `-1743` (errAEEventNotPermitted) a errore strutturato
  con `recovery_hint` che nomina l'app GUI da autorizzare
- JXA scripts difensivi: `safe(fn, default)` wrapper per ogni
  property access; record che falliscono individualmente vengono
  saltati invece di abortire la call (fix `-1700` errAECoercionFail)
- Cache UUID-keyed su `find_related` (TTL 300s) — iter 2-N stesso
  seed scendono da ~1s a <10ms
- `scripts/smoke_e2e.py`: benchmark E2E con warmup, stderr capture,
  threshold a due tier (fast < 500ms / compare < 1500ms)
- `mypy --strict` ora bloccante in CI (rimosso `continue-on-error`)

### Changed
- `safe_call` generic signature `[T, OutT: Envelope[Any]]` — preserva
  tipo concreto end-to-end (no più collapse a `Envelope[Any]`)
- `tool.uv.dev-dependencies` → `dependency-groups.dev` (deprecato in uv)
- `uv.lock` ora committato (best practice repro builds)

### Fixed
- snippet rimosso da `search_bm25.js` (era principale colpevole `-1700`
  via `r.plainText()`); enrichment lazy on-demand in tool dedicato post-MVP
- `move_record` `location_after` sempre `str` (no più `Any | None` leak)

### Verified (real DEVONthink 4.2.2 on macOS Tahoe)
- Health check, `list_databases`, `search` (5 query reali),
  `find_related` tutti operativi end-to-end
- Fast ops p95: 487ms (target 500ms) ✅
- Compare ops p95: 1009ms (target 1500ms) ✅
- Tutti i 44 test unit passano + CI verde su 5 commit consecutivi

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
