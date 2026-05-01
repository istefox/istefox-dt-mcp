# istefox-dt-mcp

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Platform: macOS](https://img.shields.io/badge/platform-macOS-lightgrey.svg)](https://www.apple.com/macos/)
[![Status: Pre-release](https://img.shields.io/badge/status-pre--release-orange.svg)](#stato)

MCP server per DEVONthink 4 — outcome-oriented tools, RAG locale opzionale, privacy-first. Stack Python 3.12 + FastMCP + ChromaDB + uv.

> **⚠️ Pre-release (0.0.x)**: l'API dei tool è considerata stabile; possono esserci breaking change minori prima di **0.1.0** (target metà maggio 2026). RAG vector è opt-in experimental. Vedi [`handoff.md`](handoff.md) per lo stato corrente, [`CLAUDE.md`](CLAUDE.md) per i vincoli, [`docs/adr/`](docs/adr/) per le decisioni consolidate.

---

## Quick Install (3 strade)

| Strada | Per chi | Prerequisiti |
|---|---|---|
| **A — `.mcpb` desktop extension** (raccomandato) | Utenti Claude Desktop, zero-config | Claude Desktop ≥ 0.8 |
| **B — `pipx install`** (CLI standalone) | CLI users, altri host MCP | Python 3.12, `pipx` |
| **C — Source / dev install** | Contributor, debug | `uv`, git |

### A — `.mcpb` desktop extension (raccomandato)

Drag-and-drop in Claude Desktop, 1-click. Il bundle gestisce runtime + dipendenze.

1. Scarica l'ultimo `.mcpb` da [GitHub Releases](https://github.com/istefox/istefox-dt-mcp/releases/latest)
2. Trascinalo sulla finestra di Claude Desktop (oppure **Settings → Developer → Install Bundle**)
3. Al primo uso macOS chiederà il permesso AppleEvents — accetta

### B — `pipx install` (CLI standalone)

```bash
pipx install git+https://github.com/istefox/istefox-dt-mcp
```

Poi aggiungi a `~/Library/Application Support/Claude/claude_desktop_config.json`:

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

Vedi [Setup](#setup) per i dettagli completi (permessi macOS, troubleshooting installazione).

<!-- TODO before 0.1.0 tag:
     - docs/assets/install.gif (Claude Desktop install .mcpb, ~5s loop, ≤5MB)
     - docs/assets/demo.gif (chat → file_document preview → apply → undo, ~15s)
     - docs/assets/architecture.svg (diagramma a layer)
     Capturer: kap.app o Gifox; ottimizzazione: gifsicle -O3
-->

---

## Prerequisiti

- **macOS 14+** (Sonoma o successivi)
- **DEVONthink 4** (Pro o standard, qualsiasi licenza) installato e in esecuzione
- **Spazio disco**: ~300MB per il bundle, **+2GB** se attivi RAG con `bge-m3`
- **AppleEvents permission** al terminale (per pipx/dev) o a Claude Desktop (per `.mcpb`) — viene richiesto automaticamente al primo uso

---

## Cosa puoi chiedere a Claude

Esempi di prompt naturali e tool MCP che si attivano. Tutti gli esempi assumono Claude Desktop con il connector installato e DEVONthink in esecuzione.

- *"Cerca tutto su 'isolatori antivibranti' negli ultimi 2 anni"*
  → `search` (BM25 di default, hybrid se RAG attivo)
- *"Cosa abbiamo proposto a Cliente X?"*
  → `ask_database` (BM25 + sintesi; vector se RAG opt-in — vedi [RAG](#rag-vector-search--opt-in-experimental))
- *"Trovami documenti simili a questo PDF"* (con un record selezionato in DT)
  → `find_related` (See Also/Compare nativo DT)
- *"Filemi questo allegato nella cartella `/Inbox/Triage` e taggalo come `urgente`"*
  → `file_document` con preview, ti mostra cosa farà, poi conferma con `confirm_token`
- *"Sposta tutti i PDF di marzo dalla `Inbox` a `/Archivio/2026`"*
  → `bulk_apply` (batch dry-run + apply selettivo per record)
- *"Quali database sono aperti in DT?"*
  → `list_databases` (read-only, cache 5min)

I tool write (`file_document`, `bulk_apply`) sono **dry-run by default**: la prima chiamata produce sempre una preview. L'apply richiede un `confirm_token` esplicito. L'`audit_id` restituito permette `undo` selettivo via CLI.

<!-- TODO before 0.1.0 tag:
     - docs/assets/demo.gif posizionata qui (chat → file_document preview → apply → undo)
-->

---

## Privacy & sicurezza

Il connector è progettato **privacy-first** e **local-only**:

- **Tutto resta sulla tua macchina**: nessun dato esce. Niente telemetry, niente embedding cloud, niente analytics. Il modello embedding (se attivi RAG) gira locale via `sentence-transformers`.
- **Audit log SQLite append-only** di **ogni** operazione (read incluse) in `~/.local/share/istefox-dt-mcp/audit.db`. Retention default 90 giorni, configurabile.
- **Tool di scrittura sempre `dry_run=true` by default**, pattern preview-then-apply con `confirm_token` a TTL breve (5 min default).
- **Undo selettivo via `audit_id`**: ogni write op salva il before-state, ripristinabile con `istefox-dt-mcp audit undo <audit_id>`.
- **Implementazione clean-room**, **license MIT**: nessun codice copiato da progetti GPL (vedi [Vincoli legali](#vincoli-legali)).
- **Adatto a dati sensibili**: contratti, fatture, note personali, corrispondenza cliente.

---

## Roadmap

| Versione | Cosa | Riferimenti |
|---|---|---|
| **0.1.0** (questo release, mag 2026) | 6 tool MCP, audit + undo, bundle `.mcpb`, BM25-only retrieval | — |
| **0.2.0** (Q3 2026) | RAG benchmark cross-corpus + flip default modello, drift detection 3-stati | [ADR-008](docs/adr/0008-embedding-model-selection.md) |
| **0.3.0+** (Q4 2026) | HTTP transport + OAuth multi-device, tool aggiuntivi (`summarize_topic`, `create_smart_rule`) | [ADR-006](docs/adr/0006-transport-stdio-only.md), [ADR-004](docs/adr/0004-mvp-tool-scope.md) |

Backlog completo in [`handoff.md`](handoff.md).

---

## Troubleshooting top 5

| Errore | Sintomo | Fix |
|---|---|---|
| `DT_NOT_RUNNING` | Tutti i tool falliscono all'avvio | DEVONthink non è in esecuzione — avvialo (Spotlight: `DEVONthink`) |
| `PERMISSION_DENIED` (`-1743`) | Errore al primo Apple Event | **System Settings → Privacy & Security → Automation** → abilita il check verso `DEVONthink` per il terminale o per Claude Desktop |
| `DATABASE_NOT_FOUND` | `file_document` o `bulk_apply` rifiuta il path | `destination_hint` senza prefix database — usa `/Inbox/<group>` (con leading slash), non `/<group>` |
| `uv binary not found` | Bundle `.mcpb` non parte al primo run | `brew install uv` (oppure `curl -LsSf https://astral.sh/uv/install.sh \| sh`), poi disable + enable l'extension in Claude Desktop |
| `drift_detected: true` (su undo) | Undo rifiuta il rollback | Il record è stato modificato dopo l'apply originale. Usa `istefox-dt-mcp audit list --recent` per vedere il contesto, poi `--force` se sei sicuro che il rollback sia ancora desiderato |

Per errori non listati: `uv run istefox-dt-mcp doctor` produce un report diagnostico completo (DT in esecuzione, permessi, cache, RAG).

---

## Stato

**MVP completo + estensioni W8-W11**: 6 tool MCP operativi end-to-end, validati in Claude Desktop con dati reali (v0.0.20). 137 test unit verdi. Bundle `.mcpb` distribuibile. Audit log + undo selettivo funzionanti.

---

## Cosa fa

Connector MCP per DEVONthink 4 che va oltre il wrapping 1:1 della scripting dictionary.

**MVP (5 tool, sequenza implementazione W1-W7)** + estensioni post-MVP:

| Tool | Tipo | Stato | Settimana |
|---|---|---|---|
| `list_databases` | read | ✅ implementato | W1-W2 |
| `search` | read (BM25 + semantic + hybrid RRF) | ✅ implementato | W1-W2, hybrid W5 |
| `find_related` | read (See Also/Compare) | ✅ implementato | W1-W2 |
| `ask_database` | read (vector + BM25 fallback) | ✅ implementato | W3, vector W5 |
| `file_document` | write con `dry_run` + undo | ✅ implementato | W7 |
| `bulk_apply` | write batch con `dry_run` (post-MVP) | ✅ implementato | W8 |

**MVP completo + estensione W8**: 6 tool MCP operativi end-to-end.
I tool write seguono il pattern preview-then-apply: chiamarli con
`dry_run=true` ritorna un preview + `preview_token` (audit_id), poi
con `dry_run=false` + `confirm_token=<preview_token>` viene applicato
e l'`audit_id` permette `undo` selettivo via CLI.

Esclusi da MVP (post-W8): `summarize_topic`, `create_smart_rule` — vedi [ADR-004](docs/adr/0004-mvp-tool-scope.md).

---

## Stack

| Componente | Tecnologia | Riferimento |
|---|---|---|
| Linguaggio | Python 3.12 | [ADR-001](docs/adr/0001-stack-python-fastmcp-chromadb.md) |
| Framework MCP | FastMCP 3.x | [ADR-001](docs/adr/0001-stack-python-fastmcp-chromadb.md) |
| Validazione | Pydantic v2 | [ADR-001](docs/adr/0001-stack-python-fastmcp-chromadb.md) |
| Bridge DT | JXA-only v1 (astrazione multi-bridge ready) | [ADR-002](docs/adr/0002-bridge-architecture-jxa-only.md) |
| Vector DB | ChromaDB embedded | [ADR-003](docs/adr/0003-rag-same-process.md) |
| Embedding | `bge-m3` o `multilingual-e5-large` (W5) | [ADR-001](docs/adr/0001-stack-python-fastmcp-chromadb.md) |
| Cache | SQLite WAL | — |
| Test | pytest + 4-tier strategy | [ADR-005](docs/adr/0005-test-strategy-4-tier.md) |
| Packaging | `uv` workspace + hatchling | — |
| Logging | structlog (JSON su stderr) | — |
| Distribuzione | `pipx` + `.mcpb` (W11) | — |

Versione minima DT: **DEVONthink 4.0**. DT3 non supportato — vedi [ADR-007](docs/adr/0007-dt4-only.md).

---

## Struttura repo

```
.
├── apps/
│   ├── server/      MCP server FastMCP (stdio v1; HTTP+OAuth → v2)
│   └── sidecar/     RAG sidecar (ChromaDB + embeddings) — placeholder
├── libs/
│   ├── adapter/     Bridge JXA + cache + errors + script JXA
│   └── schemas/     Pydantic v2 condivisi (common, tools, audit, errors)
├── tests/
│   ├── unit/        Test unit (43 test, 100% pass)
│   ├── contract/    VCR-style cassette (placeholder)
│   └── fixtures/    Fixture condivisi
├── docs/
│   └── adr/         7 ADR consolidati
├── .github/workflows/  CI (ubuntu) + integration (macos-14, manual) + release (placeholder)
├── pyproject.toml   uv workspace + ruff + black + mypy + pytest
├── CLAUDE.md        Vincoli obbligatori
├── memory.md        Decisioni + contesto
└── handoff.md       Passaggi tra sessioni
```

---

## Setup

```bash
# Prerequisiti: macOS, DEVONthink 4 installato

# Install uv (se assente — alternativa: brew install uv)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone + sync workspace
git clone https://github.com/istefox/istefox-dt-mcp.git
cd istefox-dt-mcp
uv sync --all-packages
```

### macOS Automation permission (obbligatorio)

DEVONthink risponde alle Apple Events solo se l'app che le invia ha
il permesso esplicito. Al primo `uv run istefox-dt-mcp doctor` con
DT in esecuzione, macOS mostrerà un dialog "X vuole controllare
DEVONthink": clicca **OK**.

Se non vedi il dialog (cliccato in passato "Non consentire"):

1. Apri **System Settings → Privacy & Security → Automation**
2. Trova il terminale o app da cui esegui (Warp, iTerm, Terminal, Claude Desktop)
3. Abilita il check verso **DEVONthink**

Errore tipico in caso di permesso negato: `PERMISSION_DENIED` con
codice AppleScript `-1743`. Il connector lo intercetta e suggerisce
l'app coinvolta nel `recovery_hint`.

---

## Quick start

```bash
# Lint + format check
uv run ruff check .
uv run black --check .

# Test unit (112 test, ~4s)
uv run pytest tests/unit -v

# Test con coverage
uv run pytest tests/unit --cov=apps --cov=libs --cov-report=term

# Micro-benchmark (opt-in: cache + bridge overhead)
uv run pytest tests/benchmark --benchmark-enable --benchmark-only

# CLI
uv run istefox-dt-mcp --help
uv run istefox-dt-mcp doctor       # health check (richiede DT in esecuzione)
uv run istefox-dt-mcp serve        # avvia server stdio (per Claude Desktop)
```

## Performance tuning (env vars)

| Variabile | Default | Effetto |
|---|---|---|
| `ISTEFOX_FAST_LIST_DATABASES` | `false` | Se truthy (`1`/`true`/`yes`/`on`): `list_databases` salta il computo di `record_count` (ritorna `null`). Utile su database con decine di migliaia di record dove `d.contents().length` può richiedere secondi alla prima invocazione (la cache 5min ammortizza le successive). Default: count incluso, comportamento invariato. |
| `ISTEFOX_PREVIEW_TTL_S` | `300` | Override TTL in secondi del `preview_token` (default 5 minuti). Range valido: 1-3600. |
| `ISTEFOX_RAG_ENABLED` | `false` | Se truthy: abilita il provider vector RAG (vedi sezione successiva). |
| `ISTEFOX_RAG_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | Override modello embedding (es. `BAAI/bge-m3`). Solo se RAG abilitato. |

**Per installazioni `.mcpb` (Claude Desktop)**: dalla v0.0.22 le 4 variabili sono configurabili dalla UI di Claude Desktop senza editare file. Vai su **Settings → Extensions → istefox-dt-mcp → Configure** e troverai un form con label umani per ciascuna opzione. Modifica + Save + riavvia il server.

**Per `pipx`/dev install**: imposta le env var nel tuo shell profile (`~/.zshrc`) o nel comando di lancio.

## RAG (vector search) — opt-in **experimental**

> **⚠️ Experimental in 0.1.0**: il codice RAG è completo e testato a
> livello unit, ma il default del modello embedding non è ancora
> validato cross-corpus. Vedi [ADR-008](docs/adr/0008-embedding-model-selection.md)
> per i criteri di promozione a default in 0.2.0. Se attivi RAG ora,
> sappi che la qualità dipende fortemente dal tuo corpus — feedback
> via GitHub issue molto graditi.

Il server gira in modalità BM25-only di default (zero overhead, no
modelli da scaricare). Per attivare la ricerca vettoriale:

```bash
# 1. Abilita il RAG provider (env var)
export ISTEFOX_RAG_ENABLED=1

# 2. (Opzionale) Override modello — default MiniLM-L12-v2
export ISTEFOX_RAG_MODEL=BAAI/bge-m3   # ~2.2GB, qualità superiore

# 3. Indicizza un database DT (one-shot — sync automatico W6)
uv run istefox-dt-mcp reindex Business
uv run istefox-dt-mcp reindex privato --limit 100   # test parziale

# 4. Verifica stato indice
uv run istefox-dt-mcp doctor
# {... "rag": {"indexed_count": N, "embedding_model": "..."}}

# 5. Avvia server e usa search mode=hybrid o ask_database
uv run istefox-dt-mcp serve
```

ChromaDB embedded persistente in `~/.local/share/istefox-dt-mcp/vectors/`.
Lazy load: il modello viene scaricato/caricato al primo uso di
`search` o `ask_database` con mode semantico, non all'avvio.

### Sync automatico (W6 — opt-in)

Per indicizzazione incrementale in tempo reale via DT4 smart rule
+ reconciliation periodica:

```bash
# 1. (Opz.) genera token webhook
export ISTEFOX_WEBHOOK_TOKEN="$(openssl rand -hex 16)"

# 2. Avvia il daemon
uv run istefox-dt-mcp watch \
    --port 27205 \
    --databases Business --databases privato \
    --reconcile-interval-s 21600   # ogni 6h

# 3. Configura le smart rule DT4 (vedi docs/smart-rules/sync_rag.md)
# 4. Reconciliation manuale ogni tanto:
uv run istefox-dt-mcp reconcile Business
```

Per auto-start a boot: vedi `docs/smart-rules/sync_rag.md` §"Avvio
automatico (launchd)".

---

## Integrazione Claude Desktop (dev)

Per gli utenti finali vedi [Quick Install](#quick-install-3-strade). Questa sezione copre il workflow dev (build del bundle e config manuale per source install).

**Build del bundle `.mcpb`** (richiede solo `bash + zip + unzip`):

```bash
./scripts/build_mcpb.sh
# Output: dist/istefox-dt-mcp-<version>.mcpb (~270 KB)
```

Il bundle usa `server.type=uv`: Claude Desktop gestisce il lifecycle Python + `uv sync` al primo avvio.

**Config manuale `claude_desktop_config.json` (source install)**:

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

Path: `~/Library/Application Support/Claude/claude_desktop_config.json`. Riavvia Claude Desktop. Tutti i 6 tool sono disponibili.

> RAG e altre opzioni: via env var nel processo che lancia `claude` (config manuale) o via UI **Settings → Extensions → Configure** per il bundle (dalla v0.0.22).

---

## Documenti chiave

| File | Contenuto |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Vincoli obbligatori del progetto (legali, MCP, DT, safety) |
| [`memory.md`](memory.md) | Decisioni consolidate + decisioni aperte + contesto |
| [`handoff.md`](handoff.md) | Stato corrente + prossimi passi |
| [`docs/architecture.md`](docs/architecture.md) | Overview a layer della soluzione |
| [`docs/adr/`](docs/adr/) | 7 ADR consolidati (stack, bridge, sidecar, MVP, test, DT4, ecc.) |
| [`docs/adr/REVIEW_ADR.md`](docs/adr/REVIEW_ADR.md) | Architecture review v1.0 (input degli ADR formali) |
| `ARCH-BRIEF-DT-MCP.md` | Brief architetturale v0.1 (fonte di verità storica) |

<!-- TODO before 0.1.0 tag:
     - docs/assets/architecture.svg posizionata qui (diagramma a layer della soluzione)
-->

---

## Vincoli legali

- **Implementazione clean-room**: nessun codice copiato da [`dvcrn/mcp-server-devonthink`](https://github.com/dvcrn/mcp-server-devonthink) (GPL-3.0).
- **Privacy by design**: nessun dato dell'utente esce dalla macchina per default. Embedding generati localmente, audit log locale.
- **Namespace personale**: `istefox` (progetto non lavorativo).

---

## Licenza

[MIT License](LICENSE) © 2026 Stefano Ferri.

Puoi usare, modificare e ridistribuire il codice (anche commercialmente) mantenendo il copyright notice. Vedi [`LICENSE`](LICENSE) per il testo completo.
