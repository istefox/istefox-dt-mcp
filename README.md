# istefox-dt-mcp

MCP server per DEVONthink 4 — outcome-oriented tools, RAG locale, production-grade. Stack Python 3.12 + FastMCP + ChromaDB + uv.

> **Stato**: W1-W2 in corso. Foundations + 3 tool read-only operativi. Vedi [`handoff.md`](handoff.md) per lo stato corrente, [`CLAUDE.md`](CLAUDE.md) per i vincoli, [`docs/adr/`](docs/adr/) per le decisioni consolidate.

---

## Cosa fa

Connector MCP per DEVONthink 4 che va oltre il wrapping 1:1 della scripting dictionary.

**MVP (5 tool, sequenza implementazione W1-W7)**:

| Tool | Tipo | Stato | Settimana |
|---|---|---|---|
| `list_databases` | read | ✅ implementato | W1-W2 |
| `search` | read (BM25 + semantic + hybrid RRF) | ✅ implementato | W1-W2, hybrid W5 |
| `find_related` | read (See Also/Compare) | ✅ implementato | W1-W2 |
| `ask_database` | read (vector + BM25 fallback) | ✅ implementato | W3, vector W5 |
| `file_document` | write con `dry_run` | ⏳ schema pronto | W7 |

Esclusi da MVP (post-W7): `summarize_topic`, `bulk_apply`, `create_smart_rule` — vedi [ADR-004](docs/adr/0004-mvp-tool-scope.md).

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

# Test unit (100 test, ~4s)
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

## RAG (vector search) — opt-in

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

## Integrazione Claude Desktop (W2 preview)

Aggiungi a `~/Library/Application Support/Claude/claude_desktop_config.json`:

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

Poi riavvia Claude Desktop. I 3 tool read-only (`list_databases`, `search`, `find_related`) sono disponibili.

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

---

## Vincoli legali

- **Implementazione clean-room**: nessun codice copiato da [`dvcrn/mcp-server-devonthink`](https://github.com/dvcrn/mcp-server-devonthink) (GPL-3.0).
- **Privacy by design**: nessun dato dell'utente esce dalla macchina per default. Embedding generati localmente, audit log locale.
- **Namespace personale**: `istefox` (progetto non lavorativo).

---

## Licenza

Proprietary © Stefano Ferri. Tutti i diritti riservati.
