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

## Cosa fare nella prossima sessione

### Priorità ALTA — chiusura W1-W2

- [ ] **Avvia DEVONthink 4** e fai smoke test reali:
  ```bash
  uv run istefox-dt-mcp doctor   # deve tornare {dt_running: true, dt_version: "4.x.x", ...}
  ```
- [ ] **Test E2E manuale** dei 3 tool tramite Claude Desktop:
  - Aggiungi config a `claude_desktop_config.json` (vedi README §"Integrazione Claude Desktop")
  - Riavvia Claude Desktop
  - Prova: `list_databases`, `search` su query reale, `find_related` su un UUID noto
- [ ] **Commit + push** di tutto (>50 file nuovi):
  ```bash
  git add .
  git commit -m "feat: W1-W2 foundations + 3 read-only tools + CI + docs"
  git push
  ```
- [ ] **Verifica primo run CI** su GitHub Actions: deve essere verde su `ubuntu-latest`
- [ ] **GO/NO-GO checkpoint W2** (vedi REVIEW_ADR §6):
  - Latenza JXA p95 < 500ms? Misura con `pytest-benchmark` su `tests/integration/`
  - Compatibilità DT4 confermata? (smoke test sopra)

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
