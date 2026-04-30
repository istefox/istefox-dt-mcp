# memory.md — DEVONthink MCP Connector

> Memoria di sessione del progetto. Aggiornare ad ogni sessione di lavoro significativa con fatti, decisioni, contesto.
> Le entry sono ordinate cronologicamente (più recenti in alto). Mai cancellare entry vecchie senza motivo: marcare come `[OUTDATED]` se non più valide.

---

## Stato corrente

- **Fase**: Pre-implementazione. Brief architetturale v0.1 redatto, in attesa di review Cowork.
- **Prossimo gate**: ADR finale → scaffold repo → MVP W1-W2.
- **Prossimo deliverable atteso**: feedback Cowork sul brief.
- **Bloccanti**: nessuno. Possiamo procedere con scaffold repo e CI in parallelo al review.

---

## Decisioni prese (consolidate)

| Data | Decisione | Motivazione | Rif. brief |
|---|---|---|---|
| 2026-04-29 | Stack Python 3.12 + FastMCP + ChromaDB + uv | Ecosystem RAG, allineato Hub Gestionale FastAPI, Pydantic v2 | §7 |
| 2026-04-29 | Architettura a 6 layer con bridge multi-channel | Failover JXA/x-callback-url/DT Server, single codebase dual-transport | §5 |
| 2026-04-29 | Implementazione clean-room (no copy da `dvcrn/mcp-server-devonthink`) | Vincolo licenza GPL-3.0 | §10 |
| 2026-04-29 | RAG sidecar come processo separato | Crash isolation, ma IPC complexity tollerata | §8.2 |
| 2026-04-29 | Sync via smart-rule + reconciliation notturno | Smart rule event-driven nativo DT, hash-based fallback | §8.3 |
| 2026-04-29 | ChromaDB embedded in v1, swappable in v2 verso Qdrant | Zero-ops single-user | §8.1 |
| 2026-04-29 | Tool naming compatto (es. `search` non `search_documents_in_database`) | Ergonomia, contesto in description ≤ 2KB | §8.5 |
| 2026-04-29 | Distribuzione dual: `.mcpb` + `pipx` | Coverage Claude Desktop + dev workflow | §8.6 |
| 2026-04-29 | DT4 primario, DT3 best-effort | App name cambiato dalla 3.x | §8.7 |

---

## Decisioni aperte (da validare nel review)

Riferimento: brief §8 e §12.

1. **MVP scope**: 3 tool read-only o 5 con almeno una write op (per validare il dry-run pattern)?
2. **DT Server bridge**: progettare astrazione anche se non implementato in v1? Risk over-design.
3. **Strategia test JXA**: mocking + integration su DT reale. Come automatizzare CI?
4. **Tool versioning**: header version o suffisso `_v2` nel nome?
5. **OAuth scope**: 5 attualmente proposti (`dt:read`, `dt:write`, `dt:delete`, `dt:bulk`, `dt:admin`). Granularità giusta?

---

## Vincoli ricordati (riferimento rapido)

- macOS-only (dipendenza JXA + DEVONthink)
- DEVONthink Pro deve essere running per JXA bridge
- JXA single-threaded → semaphore pool 4-8 worker
- stdio: mai scrivere su `stdout` (rompe JSON-RPC)
- Tool description ≤ 2KB, resource ≤ 25K token
- Dry-run mandatory per write ops
- Audit log append-only obbligatorio
- Privacy by design: tutto locale
- Implementazione clean-room: zero codice da `dvcrn/mcp-server-devonthink`

---

## Contesto utente

- **Stefano Ferri** (progetto personale, namespace `istefox`)
- Macchina di sviluppo: macOS 26 (Tahoe), Terminal + Raycast
- Database DT4 esistenti: "Business" e "Privato" già strutturati
- Infra remota: **SATURNO** con Cloudflare Tunnel (riusabile per HTTP transport in v2)
- Stack preferito allineato: Python (Hub Gestionale FastAPI), workflow vibe coding
- Uso DEVONthink quotidiano per ricerca tecnica, archiviazione clienti, briefing progetti

---

## Glossario rapido (specifico progetto)

- **Brief**: il documento `ARCH-BRIEF-DT-MCP.md` (architecture brief v0.1)
- **ADR**: Architecture Decision Record, output del review Cowork
- **Sidecar**: processo Python separato per RAG/embeddings, IPC via Unix socket
- **Bridge**: layer che traduce service layer → operazioni concrete su DT (JXA, x-callback-url, DT Server)
- **JXA**: JavaScript for Automation, alternativa a AppleScript
- **MVP**: 3-5 tool funzionanti con stdio transport + sidecar RAG attivo
- **SATURNO**: infra Cloudflare Tunnel di Stefano (riuso per HTTP transport)

---

## Log modifiche memory.md

- **2026-04-30**: prima inizializzazione del file. Estratto stato dal brief v0.1.
