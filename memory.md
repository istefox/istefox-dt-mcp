# memory.md — DEVONthink MCP Connector

> Memoria di sessione del progetto. Aggiornare ad ogni sessione di lavoro significativa con fatti, decisioni, contesto.
> Le entry sono ordinate cronologicamente (più recenti in alto). Mai cancellare entry vecchie senza motivo: marcare come `[OUTDATED]` se non più valide.

---

## Stato corrente

- **Fase**: Produzione. v0.4.0 rilasciata end-to-end (2026-05-09) — HTTP transport + OAuth 2.1 PKCE multi-device + scope enforcement + ConsentStore.
- **Versione live**: v0.4.0 su GitHub Releases (bundle `.mcpb` 332 KB) + MCP Registry `io.github.istefox/dt-mcp`. Repo pubblico, MIT, solo `istefox` come contributor.
- **Annuncio 0.4.0**: pubblicato (r/devonthink + forum DEVONtechnologies "AI").
- **Prossimo deliverable atteso**: nessuno schedulato. Opzioni aperte: token refresh + key rotation (0.5.0), RAG benchmark cross-corpus (ADR-008, bloccato su early adopter), smart rule #47 (DEFERRED, gap SDK DT4).
- **Bloccanti**: nessuno.
- **Nota**: lo storico operativo dettagliato vive in `handoff.md` + auto-memory; questo file tiene le decisioni architetturali consolidate e lo stato di alto livello.

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

## Decisioni aperte del brief — RISOLTE in implementazione

Riferimento originale: brief §8 e §12. Tutte risolte nel ciclo 0.1.0–0.4.0:

1. **MVP scope**: ✅ RISOLTO — 7 tool inclusi write op (`file_document`, `bulk_apply`) con dry-run pattern mandatory.
2. **DT Server bridge**: ✅ RISOLTO — non astratto in v1 (evitato over-design); JXA bridge primario, difensivo (safe wrapper).
3. **Strategia test JXA**: ✅ RISOLTO — mocking via fixture + cassette VCR (PR #49–#60) + integration test live skip-default; CI Ubuntu + macOS-14.
4. **Tool versioning**: ✅ RISOLTO — nessun suffisso `_v2`; breaking changes gestiti via `SERVER_VERSION` + CHANGELOG (Keep a Changelog).
5. **OAuth scope**: ✅ RISOLTO — ADR-006 (Accepted): 3 scope (non 5), database-scoping server-side, error code `RECONSENT_REQUIRED`.

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
- **2026-05-16**: allineamento allo stato reale. Progetto in produzione (v0.4.0 rilasciata 2026-05-09, annuncio pubblicato). "Decisioni aperte" del brief marcate RISOLTE con riferimento all'implementazione. Storico operativo delegato a `handoff.md` + auto-memory.
