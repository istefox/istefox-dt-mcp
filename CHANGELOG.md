# Changelog

Tutti i cambiamenti rilevanti a `istefox-dt-mcp` sono documentati qui.
Formato: [Keep a Changelog](https://keepachangelog.com/it/1.1.0/), versioning [SemVer](https://semver.org/lang/it/).

## [Unreleased]

### Added (summarize_topic)

- New read-only MCP tool **`summarize_topic`** that retrieves records related
  to a topic and groups them server-side by user-selected dimensions:
  `date`, `tags`, `kind`, `location`. Default `cluster_by = ["date", "tags"]`.
- Adaptive date granularity: year-only labels for ranges > 24 months, year-month
  otherwise. Reverse-chronological cluster ordering.
- Bounded output (configurable): default 50 records retrieved, 10 clusters per
  dimension, 10 records per cluster. All bounds adjustable via `max_records`,
  `max_clusters`, `max_per_cluster`.
- Retrieval reuses the `ask_database` path: vector if `ISTEFOX_RAG_ENABLED=1`,
  BM25 fallback otherwise. BM25 mode synthesizes rank-based scores so within-
  cluster ordering remains meaningful.
- Empty clusters are omitted from the response (no `count: 0` placeholder).
- See [`docs/superpowers/specs/2026-05-03-summarize-topic-design.md`](docs/superpowers/specs/2026-05-03-summarize-topic-design.md)
  for the full design.

### Added (drift detection 3-state)

- `undo` of `file_document` now classifies drift into three states instead of
  two: `no_drift`, `already_reverted`, `hostile_drift`. Response gains a new
  `drift_state` field next to the legacy `drift_detected: bool`.
- `already_reverted` (record matches `before_state` strictly): undo returns a
  successful no-op and **does not require `--force`**. If `--force` is passed
  it's logged as `force_unused` and surfaced in the response as
  `force_ignored: true`.
- `--force` semantics narrowed: only relevant for `hostile_drift` (record in
  a state that matches neither `before_state` nor `after_state`).
- `compute_drift_state(current, before_state, after_state)` exposed as a pure
  helper in `istefox_dt_mcp_server.undo` for testing and downstream tooling.

### Compatibility

- No `AuditEntry` schema change; existing audit rows in `audit.sqlite` work
  as-is. Legacy entries written before W10 (no `after_state`) continue under
  the binary fallback (only `no_drift` / `hostile_drift` reachable).
- Existing `drift_detected: bool` semantics preserved: `true` only for
  `hostile_drift`.
- Scope limited to `file_document` undo. `bulk_apply` undo is unchanged
  (deferred to 0.3.0+).

### Planned for 0.2.0
- RAG benchmark cross-corpus (3+ corpus, 2+ early adopter) + flip default modello (ADR-008)
- Drift detection 3-state ("no drift" / "already partially undone" / "hostile drift")
  per ridurre il falso positivo che richiede `--force` quando il record e' gia'
  allineato a `before_state`
- HTTP transport + OAuth (multi-device) — ADR-006
- `summarize_topic`, `create_smart_rule` tool aggiuntivi
- Captures GIF (install + demo + architecture) per il README
- Cassette VCR catturate da DT vivo (oggi sintetiche)

---

## [0.1.0] — 2026-05-02 — First public release

Prima release pubblica del connettore MCP per DEVONthink 4.
Repo GitHub public, license MIT, .mcpb desktop extension installabile
direttamente in Claude Desktop.

### Highlight

- **6 MCP tool end-to-end**: `list_databases`, `search` (BM25 + opt-in
  vector hybrid RRF), `find_related`, `ask_database` (BM25 + opt-in
  vector), `file_document` (preview-then-apply con `confirm_token`),
  `bulk_apply` (batch ops con per-op outcomes).
- **Audit log SQLite append-only** di OGNI tool call, con
  `before_state`/`after_state` per write op e **undo selettivo**
  via `audit_id`. Drift detection con `drift_details` per debug
  visibile.
- **Distribuzione dual**: bundle `.mcpb v0.1.0` (raccomandato per
  Claude Desktop) + `pipx install` (CLI standalone) + source / dev
  install via `uv`.
- **`user_config` MCPB**: 4 env var configurabili dalla UI di
  Claude Desktop (`fast_list_databases`, `preview_ttl_s`,
  `rag_enabled`, `rag_model`).
- **CLI `audit list --recent N`** per recuperare audit_id e
  ispezionare lo storico delle operazioni.
- **CLI `doctor` a 2 stage** che rileva precocemente AppleEvents
  permission denied (-1743) con `recovery_hint` actionable.

### Test strategy 4-tier (ADR-005)

- **Tier 1 unit**: 157 test, 100% pass, mypy strict + ruff + black clean.
- **Tier 2 contract VCR**: 6 cassette JSON con output JXA realistici
  per ogni script + replay test framework.
- **Tier 3 integration su DT reale**: 6 smoke (uno per tool) + 1
  latency benchmark (`get_record` mean < 500ms target W2). Marker
  `@pytest.mark.integration`, autouse `dt_running` fixture skip
  clean se DT non running o AppleEvents -1743.
- **Tier 4 smoke E2E pre-tag**: `scripts/smoke_e2e.sh` con 5 step
  (doctor + raw JXA + audit DB + bundle artifact + server lifecycle
  via JSON-RPC initialize).

### CI/CD

- **`ci.yml`** ubuntu: lint + black + mypy + unit + contract on PR
- **`integration.yml`** macos-14: nightly + on-PR-of-relevant-paths,
  valida import + bundle build (DT non installabile in GHA, real
  integration resta manuale via smoke script)
- **`release.yml`** workflow_dispatch: validazione + build .mcpb +
  tag + GitHub Release con .mcpb attached + release notes da
  CHANGELOG

### Privacy & sicurezza

- **Tutto locale**: nessun dato esce dalla macchina (no telemetry,
  no cloud embeddings, no analytics)
- **Audit log append-only** con triggers SQLite anti-UPDATE/DELETE
- **Tool di scrittura** sempre dry_run di default + preview-then-apply
  con `confirm_token` (TTL 5min, one-shot, cross-tool isolation)
- **Implementazione clean-room**: nessun codice copiato da
  `dvcrn/mcp-server-devonthink` (GPL-3.0)
- License **MIT**, repo **public**

### Stato RAG (vector search) — opt-in experimental

Il codice RAG (W5-W6) e' completo e testato a livello unit
(ChromaRAGProvider, hybrid RRF, ask_database vector path,
reindex/reconcile/watch CLI, smart-rule template). Default
`ISTEFOX_RAG_ENABLED=false` perche' il modello embedding non e'
ancora benchmarkato cross-corpus — vedi **ADR-008** per criteri di
sblocco 0.2.0 (>=3 corpus, >=2 early adopter, MRR/recall/latency
threshold). Se attivi RAG ora, sappi che la qualita' dipende
fortemente dal tuo corpus.

### Decisioni esplicitamente rinviate

- HTTP transport + OAuth -> 0.2.0 (ADR-006)
- RAG benchmark + default flip -> 0.2.0 (ADR-008)
- Drift detection 3-stati -> 0.2.0
- Tool aggiuntivi (`summarize_topic`, `create_smart_rule`) -> 0.2.0+

### Compatibilita'

- macOS 14+
- DEVONthink 4.0+ (Pro o standard)
- Python 3.12+ (gestito automaticamente da `uv` per il bundle)
- Claude Desktop 0.7+ (manifest_version 0.3)

### Discovery dalla sessione di validazione 2026-05-01

15 PR di polish (0.0.21 -> 0.0.28) emergono dal real-world E2E testing
prima del tag pubblico. Ogni bug e' stato scoperto da un test reale,
non immaginato. La test strategy 4-tier ha fatto esattamente il suo
lavoro: Tier 1 valida la logica, Tier 3-4 valida la realta'.

---

## [0.0.28] — 2026-05-01 — Smoke step 5 hang fix (FIFO -> SIGPIPE pattern)

Discovery dal terzo run smoke (Stefano, 2026-05-01 22:25, dopo
v0.0.27): Step 1-4 verdi, Step 5 (server lifecycle) hang oltre 4
minuti, mai esce.

Root cause: il design originale di Step 5 usava FIFO + fd 3 per
gestire stdin del server. `uv run` spawn un Python subprocess che
EREDITA i file descriptor del parent shell. Anche dopo
`exec 3>&-` nel parent, il Python child manteneva fd 3 aperto
(write-side della FIFO) -> read-side della FIFO non riceveva mai
EOF -> server bloccato in attesa di altro input -> il loop
`kill -0` poll-30-iter timeout, ma probabilmente anche il `wait`
finale dopo era stuck per qualche path che non avevamo previsto.

Fix: rewrite di Step 5 con il pattern Unix canonico:

    echo INIT_REQUEST | timeout 10 server | head -1

- echo invia il request e chiude stdin
- head -1 legge la prima linea di response e chiude stdin del
  prossimo stage
- server riceve SIGPIPE su prossimo write a stdout -> exit clean
  via FastMCP shutdown path
- timeout (se disponibile) caps tutto a 10s come safety net

macOS portability: detection di `timeout`/`gtimeout` con fallback
a SIGPIPE-only (provato a funzionare con FastMCP). Rimossi tutti
i `mkfifo`, `exec 3>`, manual PID polling, `kill -0` loop.

Verificato standalone: il pipe pattern produce JSON-RPC initialize
response in <1s, exit code 0, server termina clean.

Verifiche:
- 163 unit + contract pass
- bash -n smoke_e2e.sh OK
- Standalone test: pipeline produce response valida

---

## [0.0.27] — 2026-05-01 — Integration test fixes round 2: get_record + smoke step 3

Discovery dal secondo run E2E (Stefano, 2026-05-01 22:13, Terminal.app):
- Latency PASS (mean 313ms, well under 500ms target)
- 6/7 integration smoke pass; 1 fail: `test_get_record_round_trip`
  perche' il fix di v0.0.26 era applicato solo a search_bm25.js,
  non a get_record.js -> mismatch search.reference_url (con fallback)
  vs get_record.reference_url (empty)
- Smoke step 3 fail: query SQL con table `audit` invece di
  `audit_log` e column `timestamp` invece di `ts`. Inoltre
  l'invariante "1+ row created today" e' irrealistica per fresh
  install + audit list (read op, doesn't append).

### Fixed
- **`get_record.js`**: stessa fallback `"x-devonthink-item://"+uuid`
  di search_bm25 quando referenceUrl() ritorna empty. Garantisce
  consistency search vs get_record round-trip.
- **`find_related.js`**: stessa fallback per consistency su tutti
  i 3 script che emettono reference_url.
- **`scripts/smoke_e2e.sh` step 3**:
  - Query corretta: `audit_log` (era `audit`), `ts` (era `timestamp`)
  - Schema check invece di "rows today" check (piu' robusto per
    fresh install)
  - Output mostra total rows (informational), non blocking

### Verified
- 163 unit + contract pass
- mypy + ruff + black clean
- bash -n smoke_e2e.sh OK

---

## [0.0.26] — 2026-05-01 — Integration test fixes (search reference_url + bench skip)

Discovery dal primo run E2E real degli integration test (Stefano,
2026-05-01 21:51, Terminal.app con TCC granted, DB Inbox aperto):
5/7 PASS, 2 FAIL — entrambi bug reali.

### Fixed
- **`search_bm25.js` reference_url empty**: per record di tipo
  speciale (smart group, feed item, missing file placeholder), DT
  ritorna empty/null da `r.referenceUrl()` anche se l'uuid e'
  valido. Il safe() wrapper lasciava passare `""`, lo schema
  Pydantic lo accetta, ma i caller si aspettavano un deep link
  utilizzabile.
  Fix: fallback a `"x-devonthink-item://" + uuid` quando
  `referenceUrl()` ritorna empty. Garantisce sempre un link
  funzionale.
- **`test_get_record_latency_p95_under_500ms` AttributeError**:
  pyproject.toml ha `--benchmark-disable` in addopts (sano per
  unit/contract). Quando la latency test era invocata con
  `pytest -m integration` SENZA `--benchmark-enable`,
  `benchmark.stats` restava `None` e il test crashava con
  AttributeError invece di skippare clean.
  Fix: detection di `benchmark.stats is None` con `pytest.skip()`
  e messaggio actionable che indica il flag corretto.
- **`tests/integration/README.md`**: aggiunte 2 note di setup
  (richiede `--benchmark-enable` per latency, Warp/Tabby falliscono
  TCC).

### Verified
- 163 unit + contract pass (no regression)
- mypy + ruff + black clean
- Test integration sara' validato da Stefano con bundle 0.0.26 +
  Terminal.app (atteso: 6 PASS smoke + 1 latency con `mean<500ms`
  quando lanciato con `--benchmark-enable`)

---

## [0.0.25] — 2026-05-01 — Doctor + smoke: detection precoce TCC permission

### Added
- **`HealthStatus.permission_denied: bool`** + `recovery_hint: str | None`
  per discriminare il caso DT-running-but-AppleEvents-denied dal
  caso DT-not-running. Prima il doctor ritornava `dt_running:true,
  bridge_ready:true` anche con permission denied, perche' testava
  solo `running()` (proprietà che NON richiede permission).
- **Doctor now does a 2-stage probe**: stage 1 `running()` (no
  permission), stage 2 `databases().length` (DOES require
  permission). Se stage 2 fallisce con -1743, ritorna
  `permission_denied:true` + `recovery_hint` con istruzioni
  specifiche per il fix (System Settings + tccutil).
- **`bridge_ready`** ora richiede AND fra `dt_running` e
  `not permission_denied` — riflette la realta' (un bridge senza
  permesso non puo' fare nulla di utile).

### Changed
- **`scripts/smoke_e2e.sh` Step 2**: intercetta `-1743` nel
  stderr di osascript e stampa il blocco recovery hint con le
  3 strade di fix (Settings UI, tccutil reset, change terminal).
  Prima ritornava un opaco `JXA returned non-numeric: 'ERR'`.

### Verified
- 157 unit pass (HealthStatus schema additivo, no breaking change)
- ruff + mypy + black clean
- bash -n smoke_e2e.sh OK
- Discovery: il primo E2E real-world (2026-05-01 21:30) ha rivelato
  che il terminale Warp di Stefano non aveva AppleEvents permission
  per DT, ma doctor ritornava OK. Questa e' la fix.

---

## [0.0.24] — 2026-05-01 — Undo: drift_details per debug visibile

### Added
- **`drift_details` nel response di `undo`** quando `drift_detected: true`.
  Mostra ESATTAMENTE cosa è cambiato:
  ```json
  "drift_details": {
    "tags": {
      "expected": ["Triage"],
      "current": ["Triage", "auto-added-by-DT"],
      "added": ["auto-added-by-DT"],
      "removed": []
    }
  }
  ```
  Sblocca il debug dei false positive senza dover ispezionare l'audit
  log SQLite a mano. Triggered dall'E2E test 2026-05-01 dove drift
  era misterioso (after_state coerente con apply, ma drift segnalato).

### Verified
- 12 test test_undo.py ancora passing (drift_details è additivo, non
  cambia il path principale di drift detection)

---

## [0.0.23] — 2026-05-01 — CLI `audit list` per recuperare audit_id

### Added
- **`istefox-dt-mcp audit list --recent N`**: nuovo comando CLI
  che lista gli ultimi N audit con `audit_id`, timestamp, tool,
  preview/APPLY, hint sull'input. Sblocca il workflow undo per
  gli utenti che non vedono l'`audit_id` nella response del tool
  in Claude Desktop (UX bug E2E confermato 2026-05-01: utente
  passa `record_uuid` a `undo` invece di `audit_id` → "audit_id
  not found").
- Opzioni: `--recent N` (default 10), `--tool <name>` filter,
  `--json` per output strutturato.
- Esempio output:
  ```
  1b919e75-…  2026-05-01T18:31:49Z  file_document  APPLY   A7385787-…
  4f4e586a-…  2026-05-01T18:30:45Z  file_document  preview A7385787-…
  ```
- Backed by nuovo metodo `AuditLog.list_recent(limit, tool_name)`
  con projection lightweight (no `before_state`/`after_state`).

### Verified
- 14 test `test_audit.py` pass (era 10, +4: newest-first ordering,
  tool filter, error_code surfacing, empty log)
- 157 test totali (era 153)
- Smoke CLI: `uv run istefox-dt-mcp audit list --recent 5`
  ritorna i 5 audit più recenti correttamente
- Server bumped a v0.0.23

---

## [0.0.22] — 2026-05-01 — `user_config` MCPB → env vars (UI configurabile da Claude Desktop)

### Added
- **Claude Desktop UI configurabile per 4 env var** via blocco
  `user_config` nel `manifest.json` (manifest_version 0.3, sintassi
  `${user_config.<key>}` confermata da claude-task-master 27k⭐).
  Le 4 var sono ora esposte come campi form in Settings → Extensions
  → istefox-dt-mcp → Configure:
  - `fast_list_databases` (boolean, default false) → `ISTEFOX_FAST_LIST_DATABASES`
  - `preview_ttl_s` (number, default 300, range 1-3600) → `ISTEFOX_PREVIEW_TTL_S`
  - `rag_enabled` (boolean, default false) → `ISTEFOX_RAG_ENABLED`
  - `rag_model` (string, default MiniLM) → `ISTEFOX_RAG_MODEL`
  Sblocca il workflow utente dove era richiesto editare manualmente
  `~/Library/Application Support/Claude/claude_desktop_config.json`.

### Changed
- **Permissive boolean parsing** in `JXAAdapter.list_databases` per
  `ISTEFOX_FAST_LIST_DATABASES`. Accetta `1`, `true`, `yes`, `on`
  (case-insensitive) — Claude Desktop serializza i boolean del
  `user_config` come stringhe `"true"`/`"false"`, non `"1"`/`"0"`.
  Allineato al pattern già usato in `deps.py` per `ISTEFOX_RAG_ENABLED`.
- README sezione "Performance tuning (env vars)" aggiornata: nota
  esplicita che le var sono configurabili dalla UI per `.mcpb`.

### Verified
- 153 unit test pass (era 141, +12: parametrize per truthy/falsy
  values di FAST_LIST_DATABASES)
- Bundle `.mcpb v0.0.22` build OK, manifest valido
- Server bumped a v0.0.22

---

## [0.0.21] — 2026-05-01 — Pre-0.1.0 polish: server-side validation, perf, portability

Bundle di fix non funzionali in vista della release 0.1.0 pubblica.
Tutti retro-compatibili (no breaking changes nei tool MCP).

### Added
- **`destination_hint` validato server-side** in `file_document`.
  Hint malformati come `/Triage` (manca DB prefix) ora vengono
  rifiutati immediatamente in dry_run con `DATABASE_NOT_FOUND` e
  un `recovery_hint` che include la lista dei database aperti +
  esempio formato corretto. Niente più round-trip JXA inutile.
- **`safe_call` rispetta `recovery_hint` per-instance** delle
  AdapterError; il translator i18n statico resta fallback per
  errori senza contesto. Permette messaggi d'errore arricchiti
  con dati di runtime.
- **`ISTEFOX_FAST_LIST_DATABASES=1` env var**: salta il computo di
  `record_count` in `list_databases` (ritorna `null`). Mitigation
  per database con >10k record dove `d.contents().length` è lento
  alla cold cache. Cache key separato. Default invariato.
- **Bundle uv detection esteso**: aggiunti path mise (shim +
  installs glob) e asdf shim. Override esplicito via
  `ISTEFOX_UV_BIN` env var. Messaggio d'errore install include
  istruzioni mise/cargo/curl + lista path probati per debug.

### Documentation
- **ADR-008 status: Proposed → Deferred to 0.2.0**. Razionale del
  rinvio (single-corpus bias, GOLD_QUERIES manuali expensive,
  pattern feature flag) + criteri di sblocco 0.2.0 (≥3 corpus,
  ≥2 early adopter, MRR/recall/latency invariati).
- **README**: nuova sezione "Performance tuning (env vars)" che
  documenta `ISTEFOX_FAST_LIST_DATABASES`, `ISTEFOX_PREVIEW_TTL_S`,
  `ISTEFOX_RAG_*`. Disclaimer pre-release in cima. Sezione RAG
  marcata "experimental in 0.1.0".
- **`AskDatabaseInput` docstring**: rimosso riferimento obsoleto
  a "v1 BM25-only, vector in W6"; ora riflette stato reale 0.0.x
  (BM25 default, vector opt-in via env var).

### Changed
- **License: Proprietary → MIT**. `LICENSE` file creato, `manifest.json`
  aggiornato, README sezione "Licenza" riscritta. Sblocca
  submission a `modelcontextprotocol/servers` e accettazione PR
  esterne. Repo GitHub flippato a `public`.

### Verified
- 141 test unit pass (era 137, +4: 2 destination_hint validation +
  2 list_databases env var)
- mypy strict + ruff + black puliti
- License MIT indicizzata da GitHub
- Server bumped a v0.0.21

---

## [0.0.20] — 2026-05-01 — Fix: undo bulk drift falso positivo (after_state refetch)

### Fixed
- **Undo `file_document` ritornava `drift_detected: true` falso
  positivo dopo un apply riuscito**. Causa: `file_document.py`
  salvava in `after_state.location` il `destination_hint` passato
  in input (es. `/Inbox/MCP-Test`, formato assoluto con DB prefix),
  mentre `undo` rilegge il record e DT ritorna
  `record.location = "/MCP-Test/"` (relativo al DB, no prefix).
  Mismatch → `drift_detected: true` legittimo dal punto di vista
  del codice ma errato dal punto di vista semantico (record
  non era stato modificato esternamente).
- **Discovery**: l'E2E test apply effettivo della sessione 2026-05-01
  ha fatto `file_document` apply OK su `Test MCP apply.md` →
  spostato in `/Inbox/MCP-Test/`. Tentativo di undo ritornava
  `drift_detected: true` con messaggio "record moved/edited since
  the original write; pass --force". Workaround temporaneo:
  `--force` (sicuro perché sapevamo che il drift era falso).

### Changed
- `file_document.py` ora **refetcha il record dopo l'apply** con
  `await deps.adapter.get_record(uuid)` e salva in `after_state`
  esattamente quello che DT ritorna (location e tags).
- Costo: 1 chiamata `get_record` extra per ogni apply (~150ms warm
  con cache). Trade-off accettabile per undo affidabile.
- Se la refetch fallisce (raro), si scrive un debug log e undo
  cade nell'euristica legacy invece di crashare.

### Verified
- 137 test unit pass (test esistente
  `test_audit_log_persists_after_state_on_apply` aggiornato per
  riflettere la nuova semantica refetch)
- mypy strict + ruff + black puliti
- Server bumped a v0.0.20

### Note metodologiche
Quinto bug E2E in sessione (record_count, score, find_related self,
JXA defensive, destination_hint doc, ora drift falso positivo).
Pattern ricorrente: i test unit con mock_adapter non catturano
bug di formato/convenzione tra layer (Pydantic input vs output di
DT). Tier 4 testing su DT reale resta indispensabile.

---

## [0.0.19] — 2026-05-01 — Doc: chiarito formato `destination_hint` (database prefix obbligatorio)

### Fixed (UX/docs only — niente cambio di runtime)

- **Tool descriptions di `file_document` e `bulk_apply` non documentavano**
  che il primo segmento di `destination_hint` / `payload.destination`
  deve essere il **nome di un database aperto**. Il LLM passava
  paths come `/MCP-Test` interpretando come group puro, ma il
  bridge JXA ricevuto `dbName="MCP-Test"` cercava un database con
  quel nome → `DATABASE_NOT_FOUND`.
- **Bug scoperto durante E2E apply effettivo** (sessione 2026-05-01):
  Step 3 del test apply ha fallito con DATABASE_NOT_FOUND legittimo
  ma confuso. Il LLM (Claude) ha interpretato "diagnostico errore
  database" senza realizzare che il path era malformato.

### Changed
- `FileDocumentInput.destination_hint`: aggiunto Field(description=...)
  con esempio esplicito (`/Inbox/Triage`, `/privato/Fatture/2026`)
  e contro-esempio (`/Triage` → DATABASE_NOT_FOUND).
- Docstring di `FileDocumentInput`: aggiunta sezione "Path format
  for `destination_hint`" con regola chiara.
- Docstring di `BulkApplyOperation`: chiarito formato per op `move`.
  `payload.destination` description aggiornato.
- Esempio aggiunto in FileDocumentInput.examples che usa
  `destination_hint`.

### Verified
- 137 test unit pass invariati (modifica solo descriptions Pydantic)
- mypy strict + ruff + black puliti
- Server bumped a v0.0.19

### Note metodologiche
Bug catturabile solo via E2E reale, già la quarta volta in questa
sessione (record_count, score, find_related self, JXA defensive,
ora destination_hint). Conferma il valore del Tier 4 testing
(ADR-005). I unit test mockano l'adapter quindi non vedono
problemi semantici di output strutturato verso il LLM.

Follow-up post-MVP: validation server-side del primo segmento di
destination contro `list_databases` con cache, fail-fast con
INVALID_INPUT + suggerimento. Trade-off: 1 chiamata extra
adapter per file_document/bulk_apply move.

---

## [0.0.18] — 2026-05-01 — Multi-step undo + uv detection portatile + ADR-008 framework

Tre miglioramenti post-MVP consolidati in una release.

### Added — Multi-step undo per `bulk_apply`
- **`undo_audit` ora gestisce `tool_name=bulk_apply`**:
  - Legge `after_state.applied` (lista ops applicate con payload)
  - Legge `after_state.pre_move_snapshots` (locazioni originali per ops `move`)
  - Calcola gli inversi: `add_tag↔remove_tag` (mechanico via payload),
    `move↔move-back` (richiede snapshot)
  - Applica in ordine **LIFO** (l'ultima op applicata è la prima
    revertita — coerente con interazioni locali tra op)
  - `dry_run=True` mostra il piano inverso senza mutare; `dry_run=False`
    applica best-effort (un fallimento non aborta gli altri)
- **`bulk_apply` ora cattura `pre_move_snapshots`** prima di ogni op
  `move`: chiama `get_record(uuid)` per leggere la location attuale,
  la salva. Costo: una `get_record` extra per op move (acceptable).
  Se la snapshot fallisce, l'op viene marcata `failed` invece di
  applicata-senza-undo (safety: niente apply senza undo possibile).
- **4 test unit nuovi** in `test_undo.py`:
  - `test_undo_bulk_apply_dry_run_returns_inverse_plan` — verifica LIFO + payload completo
  - `test_undo_bulk_apply_applies_inverse_ops` — apply test con mock adapter
  - `test_undo_bulk_apply_skips_move_without_snapshot` — safety per move senza snap
  - `test_undo_bulk_apply_no_applied_ops_reports_nothing` — graceful empty case

### Added — `uv` detection runtime portatile
- **`bundle_main.sh`** wrapper bash: cerca `uv` in path standard
  (`/opt/homebrew/bin/uv`, `/usr/local/bin/uv`, `~/.cargo/bin/uv`,
  `~/.local/bin/uv`, `~/.local/share/pipx/venvs/uv/bin/uv`),
  fallback a `command -v uv` su PATH. Errore esplicito con istruzioni
  di install se nessun candidato è trovato.
- **`manifest.json` aggiornato**: `command: "/bin/bash"` +
  `args: ["${__dirname}/bundle_main.sh"]`. Sostituisce il path
  hardcoded `/opt/homebrew/bin/uv` di v0.0.15-0.0.17 (Apple Silicon
  Homebrew only) → portatile su Intel Mac, cargo install, pipx install.
- **Build script aggiornato**: include `bundle_main.sh` nella bundle.

### Added — ADR-008 + benchmark embedding model
- **`docs/adr/0008-embedding-model-selection.md`** (Status: Proposed):
  documenta la scelta MiniLM vs bge-m3, criteri di valutazione
  (recall@k, MRR, latency, memory), metodologia, criteri di
  promozione (`recall@5 ≥ +15%`, `MRR ≥ +0.10`, `latency p95 < 500ms`).
- **`scripts/benchmark_embeddings.py`**: framework per il benchmark.
  L'esecuzione richiede DT4 in esecuzione + un gold set di 10-20
  query manuali con expected_uuid noti (`GOLD_QUERIES` da popolare
  prima del run). Output: tabella comparativa side-by-side + JSON
  report. Costo: ~15-20min totale (bge-m3 download ~2.2GB).

### Verified
- 137 test unit pass (era 133, +4 multi-step undo)
- mypy strict + ruff + black puliti
- Server bumped a v0.0.18

---

## [0.0.17] — 2026-05-01 — Fix: script JXA write defensive (no più JXA_ERROR opaco)

### Fixed
- **`get_record.js`, `apply_tag.js`, `remove_tag.js`, `move_record.js`**
  non erano defensivi: chiamavano `DT.getRecordWithUuid(uuid)`
  direttamente. Quando il UUID non resolve (record cancellato, DB
  chiuso, UUID inventato dal LLM, …) lo script crasha →
  `osascript exit 1` → il caller riceve un `JXA_ERROR` opaco con
  messaggio "Errore interno del bridge JXA". Diagnosi
  difficile per l'utente.
- Fix consolidato: tutti gli script ora wrappano `getRecordWithUuid`
  in `safe()` (stesso pattern già usato da `find_related.js`,
  `search_bm25.js`, `classify.js`). Risultato strutturato:
  `{"error": "RECORD_NOT_FOUND"}` invece di crash.
- Anche le altre property accessor (`record.tags()`,
  `destGroup.location()`, ecc.) e le `record.tags = updated`
  assignments sono ora wrapped in try/catch — se DT lancia, la
  chiamata ritorna un errore strutturato invece di crashare.
- Verifica diretta: tutti e 4 gli script ora ritornano
  `{"error":"RECORD_NOT_FOUND"}` su UUID inesistente (testato
  con `osascript -l JavaScript script.js FAKE-UUID`).

### Discovery
Il bug è emerso durante l'E2E test del `file_document` in
Claude Desktop con un UUID placeholder che non esisteva in DT.
Il tool ritornava `JXA_ERROR` invece di `RECORD_NOT_FOUND`,
causando diagnosi confusa (Claude ha suggerito problemi di TCC
permission, mentre era semplicemente un UUID inventato).

### Verified
- 133 test unit pass invariati
- mypy strict + ruff + black puliti
- Test JXA diretto con UUID inesistente → `RECORD_NOT_FOUND` su
  tutti e 4 gli script
- Server bumped a v0.0.17

---

## [0.0.16] — 2026-05-01 — Fix: bug raccolti dall'E2E v0.0.15

Tre bug raccolti durante il test E2E in Claude Desktop. Tutti
non bloccanti, ma noti dal test reale: vale la pena chiuderli
prima di proseguire con altre feature.

### Fixed
- **`record_count: null` in `list_databases`** — era hardcoded a
  null in `list_databases.js`. Ora popola con
  `d.contents().length` (count ricorsivo dei record nel DB),
  wrapped in `safe()` con default null se la chiamata fallisce o è
  troppo lenta.
- **`score: null` in `search`** — era hardcoded null. Ora prova
  `r.score()` (relevance 0..1 esposta da DT4 sui risultati di
  search), fallback null se non disponibile. `snippet` resta null
  per design — `r.plainText()` è I/O bloccante per PDF grandi e
  l'utente può usare il tool dedicato `get_record_text` on demand.
- **`similarity: null` in `find_related`** — stesso pattern: prova
  `r.score()` su risultati `compare()`, fallback null.
- **`find_related` includeva il record seed nei risultati** — la
  DT API `compare()` restituisce anche il record di partenza. Fix
  doppio (defense in depth):
  1. JXA `find_related.js` skippa `if (ru === uuid) continue;`
  2. Python `JXAAdapter.find_related` filtra di nuovo
     `r.get("uuid") != uuid` prima della validation Pydantic
- Test unit nuovo: `test_find_related_drops_seed_record` —
  mocka un raw output con il seme nei risultati e verifica che
  l'adapter lo rimuova.

### Verified
- 133 test unit pass (era 132, +1 nuovo per il filtro seed)
- mypy strict + ruff + black puliti
- Server bumped a v0.0.16

### Note metodologiche
Tutti questi bug erano emersi solo durante l'E2E reale in Claude
Desktop con DEVONthink — non sarebbero stati catturati dalla
test suite unit perché riguardavano valori di default JXA e
quirk dell'API DT (compare incluso seed). Conferma del valore
del Tier 4 testing nella ADR-005.

---

## [0.0.15] — 2026-05-01 — Fix: manifest .mcpb compatibile con Claude Desktop installato

Bundle .mcpb v0.0.12 era rifiutato/non installabile da Claude
Desktop. Tre fix iterativi consolidati in questa release dopo aver
ispezionato i manifest delle extension già installate in
`~/Library/Application Support/Claude/Claude Extensions/*/manifest.json`
e aver fatto E2E test concreto in Claude Desktop.

### Fixed
- **(v0.0.13) Schema manifest 0.3, non 0.4**: Claude Desktop
  installato segue la spec **0.3** (non la 0.4 della doc online).
  Errore visibile: `Failed to preview extension: Invalid manifest:
  server: Required`. Tutti i manifest installati usano
  `manifest_version: "0.3"` + `server.mcp_config` esplicito anche
  per type uv. Aggiornato:
  - `manifest_version`: `"0.4"` → `"0.3"`
  - `server.type`: `"uv"` → `"python"`
  - `server.mcp_config` aggiunto con `command` + `args`
- **(v0.0.14) Path assoluto a uv**: macOS GUI app (Claude Desktop)
  non ereditano il PATH dello shell — vedono solo
  `/usr/bin:/bin:/usr/sbin:/sbin`. `uv` installato via Homebrew
  Apple Silicon è in `/opt/homebrew/bin/uv` → invisibile a Claude.
  `command: "uv"` → `command: "/opt/homebrew/bin/uv"`.
- **(v0.0.15) Rimosso `compatibility.runtimes.python`**: era un
  bloccante dell'install (bottone "Installa" disabilitato con
  tooltip "Questa estensione richiede Python >=3.12,<4.0"). Claude
  Desktop non riusciva a verificare il Python di sistema. Tanto
  `uv` può scaricare Python in autonomia se serve — togliere il
  vincolo dichiarativo non fa perdere safety.

### Verified
- 132 test unit pass invariati (`uv run pytest tests/unit -q`)
- mypy strict + ruff + black puliti
- **E2E install in Claude Desktop**: tutti e 6 i tool MCP visibili
  e abilitati nella sezione Connettori → Desktop
- Server bumped a v0.0.15

### Limitations note
- Path assoluto a `/opt/homebrew/bin/uv` funziona solo per macOS
  Apple Silicon con Homebrew. Intel Mac (`/usr/local/bin/uv`) o
  altre installazioni (cargo, pipx, ecc.) richiedono override
  manuale del manifest (issue post-MVP: detection runtime di uv).

---

## [0.0.12] — 2026-05-01 — Fix: bundle .mcpb installa il server package

### Fixed
- **Bundle .mcpb v0.0.11 era non funzionante**: il `pyproject.toml`
  workspace root non dichiarava `istefox-dt-mcp-server` come
  dependency, quindi `uv sync` (eseguito dall'host MCPB) non
  installava il package nel venv. Risultato: `ImportError: No module
  named 'istefox_dt_mcp_server'` al lancio.
- Aggiunto `dependencies = ["istefox-dt-mcp-server"]` + relativo
  `[tool.uv.sources]` workspace mapping in `pyproject.toml` root.
  Pull transitivo di adapter, schemas, sidecar via path-deps.
- Bug scoperto via preflight test: extract `.mcpb` in dir temp →
  `uv sync` → `uv run python bundle_main.py --help`. Verifica che
  ora il workflow MCPB risolve i moduli correttamente.

### Verified
- Preflight bundle.mcpb da dir estratta: `uv sync` + bundle_main
  `--help` mostrano i 6 sub-command (`serve`, `doctor`, `reindex`,
  `reconcile`, `undo`, `watch`).
- 132 test unit pass (invariati).
- Server bumped a v0.0.12. Manifest version 0.0.12.

---

## [0.0.11] — 2026-05-01 — W11: .mcpb desktop extension packaging

### Added
- **Bundle `.mcpb`** per installazione one-click in Claude Desktop:
  - `manifest.json` (manifest_version 0.4) con `server.type=uv` e
    `entry_point=bundle_main.py`. Compatibility: macOS, Python 3.12+.
  - `bundle_main.py` — wrapper standalone che invoca `cli` defaultando
    a `serve` se nessun sub-command è passato.
  - `scripts/build_mcpb.sh` — build script bash (zero deps oltre
    `bash`/`zip`/`unzip`): assembla staging dir, esclude
    `__pycache__`/`.DS_Store`/caches, produce `dist/istefox-dt-mcp-<v>.mcpb`
    (~270 KB, 78 file).
  - Bundle layout: il workspace monorepo intero viene zippato così
    che il host esegue `uv sync` su `pyproject.toml` workspace e
    risolve i path-deps locali (`apps/`, `libs/`).
- **README sezione Claude Desktop** riscritta con due opzioni:
  - Opzione A — `.mcpb` (consigliata, no setup utente)
  - Opzione B — config JSON manuale (workflow di sviluppo)
- **Doc TCC permission**: la prima invocazione di un tool DT mostra
  il dialog macOS Automation per Claude → DEVONthink. Risolve il
  blocker della sessione iniziale (Warp/Terminal stuck).

### Changed
- Server bumped a v0.0.11.
- Manifest version coincide con `SERVER_VERSION`.

### Verified
- Build script produce bundle valido (78 file, 268 KB)
- `uv run python bundle_main.py --help` mostra tutti i sub-command
- 132 test unit ancora pass; mypy strict + ruff + black clean

### Limitations (consapevoli)
- `user_config` MCPB non wired alle env vars `ISTEFOX_*` del server
  (richiede E2E test con Claude Desktop per validare semantica per
  `server.type=uv`). Workaround: env vars settate manualmente.
- Nessun code signing del bundle (single-user personal use; firma
  richiede Apple Developer ID).

---

## [0.0.10] — 2026-05-01 — W10: after-state esplicito nell'audit log

### Added
- **`AuditEntry.after_state: dict | None`** — snapshot dello stato
  del record subito dopo un'apply riuscita. Persistito in tabella
  separata `audit_after_state` (PRIMARY KEY su audit_id, append-only,
  triggers anti-UPDATE/DELETE come per `audit_log` e
  `preview_consumption`). `audit_log` resta 100% immutabile.
- **`AuditLog.set_after_state(audit_id, state) -> bool`** — INSERT
  one-shot. Ritorna False se già impostato (PK collision).
- **`AuditLog.get(audit_id)`** ora include `after_state` via LEFT JOIN.
- **`file_document` popola after_state** dopo apply riuscita: usa
  `before_state + preview` per ricostruire il post-stato senza
  refetch (location finale, tags = before ∪ added − removed).
- **`bulk_apply` popola after_state** con la lista di op effettivamente
  applicate (filtrate da `outcomes` con status `applied`).
- **`undo_audit` usa `after_state` per drift detection precisa**
  (W10+): drift = `current` ≠ `after_state`. Fallback all'euristica
  legacy se after_state mancante (entry pre-W10).

### Changed
- Server bumped a v0.0.10.
- Docstring di `undo.py` aggiornato per documentare la nuova logica.

### Verified
- 132 test unit pass (era 127, +5: 2 audit, 1 file_document, 2 undo)
- mypy strict + ruff + black puliti

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
