# ADR 0003 — RAG same-process Python con threading isolation

- **Status**: Accepted (con spike di validazione preventivo)
- **Date**: 2026-04-30
- **Decisori**: Stefano Ferri
- **Supersedes**: brief §6.1, §8.2 (sidecar processo separato)
- **Fonte**: REVIEW_ADR §2 P2, §7 ADR-002

---

## Contesto

Il brief proponeva un RAG sidecar come processo Python separato dal server MCP, con IPC via Unix socket. La review ha identificato l'IPC come complessità ingiustificata per single-user single-device su macOS: socket lifecycle, error handling sulla connessione, deployment con due processi orchestrati, complicazioni nel `.mcpb` packaging.

## Decisione

In v1, il RAG vive **nello stesso processo Python del server MCP**, con isolamento via:

- **`concurrent.futures.ThreadPoolExecutor`** dedicato (1-2 worker) per le operazioni embedding
- **Caricamento lazy** del modello al primo `search` o `ask_database`
- **Lock interno** attorno alle write su ChromaDB (non thread-safe per writes)
- **Try/except esplicito** attorno alle chiamate RAG con **fallback graceful a BM25-only**
- **Astrazione `RAGProvider`** come interfaccia, swappable in v2

## Razionale

- **Riduzione delivery time**: ~1 settimana risparmiata (review §2 P2)
- **Deployment unico**: niente orchestration, packaging `.mcpb` semplice
- **Debugging unificato**: un solo log, un solo crash dump
- **Reversibilità**: `RAGProvider` astratto permette migrazione a processo separato in v2 con refactor contenuto

## Criteri di promozione a sidecar separato (v2)

Migrare a processo separato solo se metriche di production lo richiedono:

- **Memory**: embedding model + ChromaDB sustained > 4 GB sul processo MCP (impatta UX su Mac con 16GB)
- **Crash rate**: ≥ 2 OOM per mese in produzione attribuiti al RAG
- **Update independence**: necessità di hot-swap del modello senza restart del server MCP
- **Multi-tenant**: scenario v2 con utenti multipli (fuori scope v1)

## Spike preventivo (W4-W5, prima di W5)

**Obiettivo**: validare assunzione critica che ChromaDB embedded resti stabile sotto carico realistico.

**Setup**:
- 50K record sintetici (testo italiano + metadata)
- Embedding model `bge-m3` o `multilingual-e5-large`
- 100 query concorrenti (read) + 10 insert/update (write) al secondo per 5 minuti

**Criteri pass**:
- Latenza p95 query < 300ms
- No deadlock né corruption ChromaDB
- Memory footprint sustained < 3 GB
- Audit log integro

Se fail: rivalutare ADR-002, possibile early-promotion a sidecar separato in W5-6.

### ✅ Esito spike (2026-05-01)

**PASS con margine ampio.** Misure: query p95 5.5 ms (60x sotto target),
memory peak 1147 MB (38% del budget), 0 errori su 30K query + 3K write.
Modello usato come proxy: `paraphrase-multilingual-MiniLM-L12-v2`
(384-dim). Bge-m3 da ri-misurare in W5 (delta atteso solo su encoding).
Report completo: [`docs/spikes/2026-05-01-chromadb-stress-test.md`](../spikes/2026-05-01-chromadb-stress-test.md).
**ADR-003 confermato**, procedere con `ChromaRAGProvider` in W5.

## Conseguenze

- ✅ Packaging `.mcpb` più semplice
- ✅ Tempo di delivery ridotto
- ✅ Debugging unificato
- ⚠ Crash isolation perso: OOM dell'embedding model porta giù il server MCP → mitigato con memory limit configurabile + supervisor restart logic
- ⚠ Aggiornamento modello richiede restart server → accettabile per single-user (manuale)
- ⚠ Stress test dependent: la decisione si basa su un'assunzione di stabilità che va validata con spike

## Riferimenti

- REVIEW_ADR.md §2 P2, §7 ADR-002, §9 (assunzione A2)
- Brief §6.1 (proposta originale sidecar separato)
- ADR 0001 (ChromaDB embedded)
