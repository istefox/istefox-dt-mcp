# handoff.md — istefox-dt-mcp

> Documento di passaggio tra sessioni di lavoro. Aggiornato a fine sessione.

---

## Snapshot sessione corrente

- **Data**: 2026-04-30
- **Operatore**: Stefano Ferri + Claude Opus 4.7
- **Output**: W1-W2 milestone completata (foundations + 3 tool read operativi + CI + docs)

---

## Cosa è stato fatto in questa sessione

### Setup operativo (Step 1)
- Repo GitHub privato creato: https://github.com/istefox/istefox-dt-mcp
- `git push -u origin main` fatto
- `uv` 0.11.8 installato via brew
- Workspace `uv sync --all-packages`: 169 packages, lockfile generato

### ADR formali (Step 2)
- 5 ADR scritti in `docs/adr/`:
  - `0002-bridge-architecture-jxa-only.md`
  - `0003-rag-same-process.md`
  - `0004-mvp-tool-scope.md` (sostituisce decisione precedente "3 read-only")
  - `0005-test-strategy-4-tier.md`
  - `0007-dt4-only.md`

### Bridge layer (Step 3 — `libs/adapter/`)
- `contract.py` — `DEVONthinkAdapter` ABC
- `jxa.py` — `JXAAdapter` con pool async (semaphore 4), retry exponential backoff, timeout 5s
- `cache.py` — SQLite WAL cache con TTL
- `errors.py` — tassonomia errori (`AdapterError` + 10 sotto-classi)
- `scripts/*.js` — 6 template JXA (list, get, search, find_related, apply_tag, move)

### Schemas Pydantic v2 (Step 4 — `libs/schemas/`)
- `common.py` — domain models (Database, Record, SearchResult, ecc.) + `Envelope` generic
- `tools.py` — input/output per ogni tool MVP (con docstring inglese ≤2KB per tool description)
- `audit.py` — `AuditEntry`
- `errors.py` — `ErrorCode` enum + `StructuredError`

### Server core (Step 5 — `apps/server/`)
- `cli.py` — Click entrypoint `serve|doctor` con `--log-level`
- `server.py` — FastMCP 3.x bootstrap, registra 3 tool
- `logging.py` — structlog JSON su stderr (mai stdout)
- `audit.py` — `AuditLog` SQLite append-only con trigger anti-UPDATE/DELETE
- `i18n.py` + `locales/it.toml` — traduzione errori
- `deps.py` — DI container `Deps`
- `tools/_common.py` — `safe_call` wrapper (audit + i18n + duration)
- `tools/{list_databases,search,find_related}.py` — implementazioni concrete

### Test (Step 6 — `tests/`)
- `conftest.py` — fixture comuni (mock_adapter, audit_log, cache, deps)
- `tests/unit/`: 7 file di test, **43 test, 100% pass in ~0.7s**
- Coverage: schemas 100%, adapter cache 96%/contract 95%/errors 85%/jxa 53%, audit (server) 96%, i18n 100%, tools/_common 100%

### CI (Step 7 — `.github/workflows/`)
- `ci.yml` — ubuntu: ruff + black + pytest unit + mypy (advisory)
- `integration.yml` — macos-14, manual trigger (sarà attivato post-spike costi)
- `release.yml` — placeholder W11

### Documentazione (Step 8)
- `README.md` aggiornato (stato W2, quick-start, integrazione Claude Desktop, link ADR)
- `docs/architecture.md` nuovo — overview a layer post-review
- `CHANGELOG.md` nuovo — Keep a Changelog format, entry 0.0.1
- `handoff.md` (questo file) aggiornato

---

## Stato corrente del progetto

- **Fase**: W1-W2 milestone completata. Pronto per push su GitHub e GO/NO-GO checkpoint.
- **Codice**: 3 tool read-only implementati e testati. Bridge JXA pronto. Audit log operativo.
- **Test**: 43 unit pass, coverage core ≥80%.
- **CI**: workflow files committati ma non ancora pushati (verifica primo run dopo push).
- **DT4**: installato in `/Applications/DEVONthink.app` ma **non in esecuzione** durante la sessione → smoke JXA reale ancora da fare.

---

## W6 status (2026-05-01)

W6 chiuso in giornata. Aggiunto:
- **Reconciliation hash-based** (set-diff DT vs RAG): `reconcile_database`
  in `apps/server/reindex.py`. Indicizza nuovi UUID, rimuove orfani.
  Idempotent — safe per cron.
- **`reconcile <database>` CLI command**.
- **`WebhookListener`** stdlib loopback su `127.0.0.1:27205/sync-event`,
  bounded queue 1024, optional Bearer auth via env.
- **`process_sync_event`**: dispatcher webhook event → RAG provider.
- **`watch` CLI daemon**: webhook listener + cron reconciliation.
- **Smart rule template DT4** in `docs/smart-rules/sync_rag.md` con
  AppleScript snippet + launchd plist per auto-start.

100 test pass (84 W5 + 16 nuovi). mypy strict + ruff + black clean.
CHANGELOG v0.0.6 publishato.

**Per testare end-to-end** quando vuoi:
```bash
export ISTEFOX_RAG_ENABLED=1
uv run istefox-dt-mcp reindex Business --limit 50    # popolamento iniziale
uv run istefox-dt-mcp watch --databases Business     # daemon
# poi configura smart rule DT4 → vedi docs/smart-rules/sync_rag.md
```

**Prossimo (W7)**: write tools — `file_document` con dry_run + audit
before_state + confirm_token flow. Schema già pronto da W4. Anche:
- ADR-008 model selection (benchmark MiniLM vs bge-m3 su corpus reale)
- Fingerprint-based reconciliation (modification_date diff)

---

## W5 status (2026-05-01)

W5 chiuso in giornata. Aggiunto:
- **`ChromaRAGProvider`** (apps/sidecar): same-process ADR-003, lazy
  load model + client, asyncio.Lock su write
- **Config-driven RAG**: `ISTEFOX_RAG_ENABLED=1` + opzionale
  `ISTEFOX_RAG_MODEL=...`. Default NoopRAGProvider (no overhead)
- **`reindex` CLI**: walk DT (nuovo `enumerate_records` + script
  JXA), batch-index in vector store. One-shot manuale; smart rule
  sync W6.
- **Hybrid search RRF** in tool `search`: bm25/semantic/hybrid mode
  via Reciprocal Rank Fusion (k=60)
- **`ask_database` vector-first**: retrieval semantico se RAG attivo,
  fallback BM25 trasparente

84 test pass, mypy strict + ruff + black clean. CHANGELOG v0.0.5.

**Per testare end-to-end con dati reali**:
```bash
export ISTEFOX_RAG_ENABLED=1
uv run istefox-dt-mcp reindex Business --limit 50
uv run istefox-dt-mcp doctor   # vede indexed_count > 0
```

**Prossimo (W6)**: smart rule DT4 → webhook locale per sync
incrementale + reconciliation notturna. Anche ADR-008 (model
selection: MiniLM vs bge-m3) con benchmark su corpus reale.

---

## ChromaDB stress spike — ADR-003 PASS (2026-05-01)

Spike preventivo richiesto da ADR-003 §"Spike preventivo" eseguito
con esito **PASS con margine ~60x sulla latenza**:

| Metric | Misurato | Target | Margine |
|---|---|---|---|
| Query p95 | 5.5 ms | < 300 ms | 60x |
| Memory peak | 1147 MB | < 3000 MB | 38% del budget |
| Throughput query | 101.2 q/s | 100 q/s | over target |
| Errori (30K query + 3K write) | 0 | 0 | clean |

Setup: 50K record sintetici, 5 min sustained load, 8 query worker +
10 write/s. Modello `paraphrase-multilingual-MiniLM-L12-v2` (proxy
veloce per validare ChromaDB; `bge-m3` da ri-misurare in W5 con
delta atteso solo su encoding).

Report completo: [`docs/spikes/2026-05-01-chromadb-stress-test.md`](docs/spikes/2026-05-01-chromadb-stress-test.md).

**Conseguenza**: ADR-003 confermato. W5 può partire senza dubbi
architetturali — `ChromaRAGProvider` same-process è la scelta giusta.

---

## W4 status (2026-05-01)

W4 chiuso in giornata. Aggiunto:
- **Logging refinement**: `safe_call` binda `request_id+tool+audit_id`
  a `structlog.contextvars`; nuovo evento `tool_call_started` con
  input redatto (query/question/snippet/answer mascherati)
- **Schemas write tools** (impl W7+): `FileDocument.confirm_token`,
  `BulkApply` schema, `Undo` schema con `drift_detected`
- **RAGProvider ABC** + `NoopRAGProvider` registrato come default
  in `Deps` — permette di scrivere già adesso codice che usa il RAG
  layer (ritornerà liste vuote finché W5-6 non sostituisce con
  `ChromaRAGProvider`)

68 test pass, mypy strict + ruff verdi. CHANGELOG v0.0.4 pubblicato.

**Prossimo (W5-W6)**: RAG sidecar same-process — il salto di valore
vero. Plan: `ChromaRAGProvider`, embedding pipeline `bge-m3` lazy
load, smart rule DT4 → webhook, hybrid search in `search` e
`ask_database`. Spike preventivo ChromaDB stress-test 50K record
prima dell'implementazione (vedi ADR-003 §"Spike preventivo").

---

## W3 status (2026-05-01)

W3 **chiuso** in giornata. Aggiunto:
- `ask_database` tool (retrieval-only BM25, vector W5-6) +
  `get_record_text` adapter + script JXA defensive
- `pytest-benchmark` baseline (4 test, opt-in): bridge ~316 µs,
  cache hit 2.7 µs / miss 1.7 µs su mock subprocess

51 test unit pass, mypy strict + ruff verdi. CHANGELOG v0.0.3
pubblicato.

**Prossimo (W4)**: structured logging refinement + Pydantic schemas
estesi per write tool (preparatorio W7). Poi W5-W6 = RAG sidecar
(ChromaDB + bge-m3 + smart rule sync) — è il vero salto di valore.

---

## Latency thresholds W2 (revised)

Smoke E2E reale ha confermato: il target unico **read p95 < 500ms** del
brief originale è ottimistico per `find_related`. `DT.compare()` è
~1s+ anche dalla GUI (operazione semantica nativa di DT).

Threshold revisionati (in vigore da 2026-05-01):

| Categoria | Esempi | Target p95 |
|---|---|---|
| **Fast ops** | `list_databases`, `get_record`, `search` | < 500ms |
| **Compare ops** | `find_related`, in futuro `summarize_topic` | < 1500ms |

Mitigazione: `find_related` ora ha cache UUID-keyed (TTL 300s).
Seconda chiamata stesso seed → < 10ms warm. Cold path resta ~1s.

Numeri reali (run 2026-05-01 11:34 dal Mac di Stefano):
- `search 'isolatori'`: mean 110ms p95 138ms
- `search 'vibrazioni'`: mean 297ms p95 315ms
- `search 'progetto'`: mean 196ms p95 214ms
- `search 'report'`: mean 465ms p95 483ms (query generica)
- `search 'test'`: mean 474ms p95 488ms (query generica)
- `find_related` (cold): mean 1037ms p95 1088ms — sotto nuovo target
- `list_databases`: 0ms (cached) — cold ~200ms

Verdetto W2 GO/NO-GO: **PASS ✓** confermato (run 2026-05-01 11:38).
Fast ops p95 = 487ms (target < 500ms). Compare ops p95 = 1009ms
(target < 1500ms). Cache find_related riduce iter 2-N warm a ~0ms.

---

## ⚠️ Issue noto: macOS Automation permission denied

**Stato (2026-05-01)**: lo smoke E2E reale è bloccato da AppleScript `-1743`
("Not authorized to send Apple events"). DT4 4.2.2 risponde a property
read banali (`.version()`, `.running()`) ma rifiuta qualunque Apple Event
significativo (`.databases()`, `.search()`).

Causa: né **Warp** (terminale dev) né **Claude.app** sono nella lista
"Automation → DEVONthink" di System Settings. `tccutil reset AppleEvents
dev.warp.Warp-Stable` non ha forzato il dialog di consenso. Claude.app
non ha `NSAppleEventsUsageDescription` nel suo `Info.plist` (verificato),
quindi non può richiedere il consent flow standard.

**Workaround possibili (richiedono UI utente)**:

1. **Aggiungi manualmente Warp/Claude alla lista TCC**: non possibile da
   GUI senza popup. Serve modifica diretta a `~/Library/Application
   Support/com.apple.TCC/TCC.db` (richiede Full Disk Access alla shell).
2. **Pre-autorizza tramite Script Editor**: apri ScriptEditor.app
   (autorizzato di default), esegui `tell application "DEVONthink" to
   get name of databases`, accetta il dialog. Questo NON aiuta Warp
   direttamente.
3. **Lancia osascript via launchd** con bundle dedicato: complesso.
4. **Soluzione cleanest** (TBD): packaging `.mcpb` con bundle proprio
   `Info.plist` + `NSAppleEventsUsageDescription` → al primo uso da
   Claude Desktop il consent flow funziona.

**Impatto su milestone W1-W2**: tutti i 44 test unit pass (mock JXA
funzionante), il bridge layer è verificato a livello di codice,
`AutomationPermissionError` è stato aggiunto al taxonomy con
`recovery_hint` esplicito. Manca solo la verifica end-to-end su DT
reale, che è bloccata dal permesso macOS.

**Config Claude Desktop**: `claude_desktop_config.json` è stato
aggiornato (entry `istefox-dt-mcp`, backup salvato in
`.bak`). Riavvia Claude Desktop per attivarlo. Probabile che il primo
tool call mostri `PERMISSION_DENIED` finché non risolto il TCC.

---

## Cosa fare nella prossima sessione

### Priorità ALTA — chiusura W1-W2

- [ ] **Risolvere TCC permission** (vedi sezione sopra). Quando fatto:
  ```bash
  uv run istefox-dt-mcp doctor   # deve tornare {dt_running: true, ...}
  uv run python -c "import asyncio; from istefox_dt_mcp_adapter.jxa import JXAAdapter; \
    print(asyncio.run(JXAAdapter().list_databases()))"
  ```
- [ ] **GO/NO-GO checkpoint W2** (REVIEW_ADR §6):
  - Latenza JXA p95 < 500ms? Misura con `pytest-benchmark` (da scrivere)
  - Compatibilità DT4 confermata? (richiede TCC fix)
- [ ] **Test E2E via Claude Desktop**: dopo restart, prova
  `list_databases`, `search`, `find_related` da chat Claude

### Priorità MEDIA — preparazione W3-W4

- [ ] **Scrivere ADR-006 (OAuth)** in versione "rinviato a v2" (placeholder formale)
- [ ] **Spike costi CI macOS GHA** (1 giorno) → finalizzazione `integration.yml`
- [ ] **Cassette VCR** (Tier 2 test): generare 5-10 cassette con DT reale, committarle in `tests/contract/cassettes/`
- [ ] **Branch protection** su `main` post-CI verde
- [ ] **Pre-commit hooks** (ruff + black + check uv lock): `uvx pre-commit install`

### Priorità BASSA — quando arriva il momento (W3+)

- [ ] Pool worker async benchmark + tuning (`pytest-benchmark`)
- [ ] `ask_database` BM25 mode (W4)
- [ ] RAG sidecar same-process (W5-6) — preceduto da spike ChromaDB stress-test
- [ ] `file_document` con dry_run (W7)
- [ ] Spike licenza fixture DT (`.dtBase2` committable?)
- [ ] Spike licenza `bge-m3` (verifica MIT)

---

## Domande aperte per l'utente

1. **Smoke test JXA**: vuoi avviare DT4 ora per chiudere W1-W2? (oppure rinviato a prossima sessione)
2. **Pre-commit hooks**: installiamo subito `pre-commit` per impedire commit con lint sporco?
3. **Branch protection**: la attiviamo subito su `main` (richiede CI green) o aspettiamo qualche commit?
4. **Cassette VCR**: vuoi che io le generi dalla console quando DT4 è in esecuzione, oppure le fai tu interattivamente?

---

## Comandi utili (cheatsheet)

```bash
# Sync workspace dopo cambi a pyproject.toml
uv sync --all-packages

# Lint + format
uv run ruff check .
uv run ruff check . --fix       # safe fix
uv run black .

# Test
uv run pytest tests/unit -v
uv run pytest tests/unit --cov=apps --cov=libs --cov-report=term

# CLI server
uv run istefox-dt-mcp --help
uv run istefox-dt-mcp doctor    # health check (DT richiesto)
uv run istefox-dt-mcp serve     # avvia stdio server
```

---

## Note operative per chi riprende

- **Vincoli obbligatori** in `CLAUDE.md` §2 — leggere PRIMA di proporre design alternativi
- **Stack lock-in** in `CLAUDE.md` §3 — non sostituire componenti senza ADR
- **Niente codice GPL**: prima di importare libreria, verifica licenza
- **DT4 only**: `Application("DEVONthink")` non `Application("DEVONthink 3")`
- **stdio**: MAI `print()` o `stdout` — solo `stderr` via `structlog`
- **Namespace**: `istefox-*` (progetto personale)
- **Tool description**: inglese (sezioni "When to use", "Don't use for", "Examples", ≤ 2KB)
- **Error message user-facing**: italiano (via `i18n.py` + `locales/it.toml`)
- **Audit log**: append-only, mai UPDATE/DELETE
- **Write op**: `dry_run=True` di default, mai exception

---

## File chiave

| File | Scopo |
|---|---|
| `CLAUDE.md` | Regole + vincoli obbligatori |
| `memory.md` | Decisioni + contesto |
| `handoff.md` | Questo file |
| `ARCH-BRIEF-DT-MCP.md` | Brief storico (fonte di verità originale) |
| `docs/adr/REVIEW_ADR.md` | Architecture review v1.0 (input ADR formali) |
| `docs/adr/0001-0007*.md` | 6 ADR consolidati |
| `docs/architecture.md` | Overview a layer corrente |
| `pyproject.toml` | Workspace uv (root) |

---

## Log handoff

- **2026-04-30 — Setup iniziale**: 3 file di project meta creati. Nessun codice scritto.
- **2026-04-30 — Scaffolding**: namespace `vibrofer→istefox`, monorepo `uv`, ADR 0001, bozza Cowork email (poi scartata), git init + primo commit (`72c9fc4`).
- **2026-04-30 — Plan W1-W2**: brief reviewato (REVIEW_ADR.md), 4 domande di scope risposte (5 tool, single-device, CI da decidere, EN+IT), piano `quiet-shimmying-dragonfly.md` approvato.
- **2026-04-30 — Implementazione W1-W2**: 8 step eseguiti — repo GitHub creato, 5 ADR formali, bridge layer + schemas + server core (~1600 LoC nuove), 43 test unit (100% pass), CI workflow YAML, README/architecture/CHANGELOG aggiornati. Pronto per commit + push + smoke E2E.
