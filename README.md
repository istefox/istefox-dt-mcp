# istefox-dt-mcp

MCP server "best-in-class" per DEVONthink 4 — dual-transport, multi-bridge, RAG-augmented.

> **Stato**: pre-implementazione. Brief architetturale v0.1 in attesa di review Cowork. Vedi [`CLAUDE.md`](CLAUDE.md), [`memory.md`](memory.md), [`handoff.md`](handoff.md).

---

## Cosa fa (target)

Un connector MCP per DEVONthink 4 che va oltre il wrapping 1:1 della scripting dictionary:

- **Outcome-oriented tools**: `search`, `ask_database`, `find_related`, `summarize_topic`, `file_document`, `bulk_apply`, `create_smart_rule`
- **RAG locale** con vector DB embedded (ChromaDB) per semantic search multilingue (IT/EN/FR/DE)
- **Multi-bridge** con failover (JXA primario, x-callback-url, DT Server)
- **Dual transport**: stdio (locale) + Streamable HTTP con OAuth 2.1 (remoto)
- **Production-grade**: audit log, dry-run mandatory, observability, recovery

---

## Stack

Python 3.12 + FastMCP + ChromaDB + uv. Vedi [`CLAUDE.md` §3](CLAUDE.md#3-stack-tecnologico-vincolato).

---

## Struttura repo

```
.
├── apps/
│   ├── server/      # MCP server FastMCP (stdio + http)
│   └── sidecar/     # RAG sidecar (ChromaDB + embeddings + IPC)
├── libs/
│   ├── adapter/     # Bridge layer (JXA, x-callback-url, DT Server)
│   └── schemas/     # Pydantic schemas condivisi
├── scripts/         # init, doctor, smart-rule installer
├── tests/           # pytest (mocking JXA + integration su DT reale)
├── docs/
│   └── adr/         # Architecture Decision Records
└── pyproject.toml   # uv workspace
```

---

## Setup (preliminare — richiede uv)

```bash
# Installa uv (se non presente)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Sync workspace
uv sync

# Run lint + test
uv run ruff check .
uv run pytest
```

---

## Documenti chiave

| File | Contenuto |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Vincoli obbligatori del progetto |
| [`memory.md`](memory.md) | Decisioni consolidate + decisioni aperte |
| [`handoff.md`](handoff.md) | Passaggio tra sessioni di lavoro |
| `docs/adr/` | Architecture Decision Records |
| `~/Downloads/ARCH-BRIEF-DT-MCP.md` | Brief architetturale completo (fonte di verità) |

---

## Vincoli legali

- **Implementazione clean-room**: nessun codice copiato da [`dvcrn/mcp-server-devonthink`](https://github.com/dvcrn/mcp-server-devonthink) (GPL-3.0).
- **Privacy by design**: nessun dato dell'utente esce dalla macchina per default.

---

## Licenza

Proprietary © Stefano Ferri. Tutti i diritti riservati.
