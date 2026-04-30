# ADR 0001 — Stack tecnologico: Python 3.12 + FastMCP + ChromaDB + uv

- **Status**: Accepted (consolidata nel brief v0.1)
- **Date**: 2026-04-29
- **Decisori**: Stefano Ferri
- **Review pendente**: Cowork (review architetturale del brief)
- **Fonte**: `ARCH-BRIEF-DT-MCP.md` §7

---

## Contesto

Il connector deve scegliere un linguaggio + framework MCP + vector DB + package manager. I candidati realistici sono Python e TypeScript (gli unici due con SDK MCP first-class al 2026).

## Decisione

Stack:

| Componente | Scelta | Alternative considerate |
|---|---|---|
| Linguaggio | **Python 3.12** | TypeScript |
| Framework MCP | **FastMCP** (SDK ufficiale Python) | mcp-python low-level |
| Validazione schema | **Pydantic v2** | dataclasses + manuale, msgspec |
| Vector DB | **ChromaDB** embedded | Qdrant, LanceDB, sqlite-vss |
| Embedding | `sentence-transformers` con `bge-m3` o `multilingual-e5-large` | OpenAI/Anthropic API (rifiutato per privacy) |
| Cache | **SQLite WAL** | Redis (overkill single-user) |
| Bridge JXA | `osascript` via `asyncio.subprocess` | Node.js + `osascript` lib |
| Packaging | **`uv` + `pyproject.toml`** | poetry, pip + venv |
| Test | `pytest` + `pytest-asyncio` | unittest |
| Logging | `structlog` (JSON su stderr) | logging stdlib |
| Tracing | `opentelemetry-sdk` | manual |
| Distribuzione | `pipx` + `.mcpb` | Docker, Homebrew |

## Razionale

**Pro Python**:
- Ecosystem RAG ricchissimo (sentence-transformers, chromadb, qdrant-client, langchain-community)
- Allineato allo stack utente (Hub Gestionale FastAPI)
- Pydantic v2 superiore a Zod per schema MCP complessi (performance C-extension, richer constraints)
- Workflow utente = vibe coding in Python

**Contro Python**:
- Overhead del subprocess per chiamare `osascript` (vs Node.js che ha lib native)
- Packaging meno leggero per Claude Desktop rispetto a TypeScript

**Mitigazione contro**:
- Pool worker async con cache SQLite ammortizza l'overhead JXA
- `.mcpb` desktop extension format risolve il packaging in Claude Desktop

**Privacy first**:
- Embedding generati localmente con `sentence-transformers` → nessuna chiamata API esterna
- `bge-m3` è multilingue (IT/EN/FR/DE) e sufficiente per i casi d'uso utente

**ChromaDB vs Qdrant**:
- ChromaDB: zero-ops, perfetto single-user, embedded
- Qdrant: scala meglio, multi-collection, ma overkill per v1
- **Decisione**: ChromaDB v1 con interface astratta → swappable Qdrant in v2 se servirà

## Conseguenze

- ✅ Tempo di sviluppo MVP ridotto (riuso conoscenza utente)
- ✅ Privacy by design garantita (no API esterne per embedding)
- ✅ Estendibilità RAG semplice
- ⚠ Leggera latenza extra sulle chiamate JXA → mitigata da pool + cache
- ⚠ Distribuzione Claude Desktop richiede `.mcpb` packaging (Anthropic-specific)

## Validazione richiesta da Cowork

- Conferma performance JXA pool < 500ms p95 raggiungibile
- ChromaDB embedded davvero zero-ops in produzione single-user su macOS?
- `bge-m3` qualità sufficiente per documenti tecnici IT?
- `.mcpb` workflow stabile al 2026?

## Riferimenti

- Brief §5 (architettura), §7 (stack), §8.1 (ChromaDB vs Qdrant)
- [FastMCP](https://github.com/jlowin/fastmcp)
- [ChromaDB](https://docs.trychroma.com/)
- [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3)
- [uv](https://docs.astral.sh/uv/)
