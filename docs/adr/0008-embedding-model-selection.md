# ADR 0008 — Embedding model selection (MiniLM vs bge-m3)

- **Status**: **Deferred to 0.2.0** — framework di benchmark pronto, decisione del default rinviata post-feedback early adopter
- **Date**: 2026-05-01 (created), 2026-05-01 (deferral lock-in per release 0.1.0)
- **Decisori**: Stefano Ferri
- **Related**: ADR-001 (stack), ADR-003 (RAG same-process)

---

## Contesto

ADR-001 lasciava la scelta del modello embedding tra:

- **`paraphrase-multilingual-MiniLM-L12-v2`** (default attuale, ~120MB, 384-dim)
- **`BAAI/bge-m3`** (~2.2GB, 1024-dim, multilingue)

ADR-003 ha rinviato la scelta a "W5 dopo benchmark su corpus reale". Siamo in W11+ e la decisione è ancora aperta. Stefano usa il bundle `.mcpb` con default MiniLM e non ha ancora un dataset di valutazione formale.

## Modelli candidati

### MiniLM-L12-v2 (paraphrase-multilingual)

| Aspetto | Valore |
|---|---|
| Dimensioni modello | ~120MB |
| Embedding dim | 384 |
| Inferenza CPU (M1) | ~5ms/passage |
| Lingue | 50+ (training corpus paraphrase) |
| Licenza | Apache 2.0 |
| Training data | Paraphrase, snli, qnli, ms-marco |
| Punto debole | Domain knowledge debole (training general-purpose) |

### bge-m3 (BAAI)

| Aspetto | Valore |
|---|---|
| Dimensioni modello | ~2.2GB |
| Embedding dim | 1024 |
| Inferenza CPU (M1) | ~25ms/passage (stimato) |
| Lingue | 100+ |
| Licenza | MIT |
| Training data | Wide multilingual + sparse + multi-vector |
| Punto debole | First-load 8-12s, footprint memoria 3-4GB peak |

## Criteri di valutazione

Per il caso d'uso istefox-dt-mcp (single-user, corpus DEVONthink misto IT/EN, tipicamente PDF tecnici/contratti/note):

1. **Recall@k** (k=5, k=10) su queries reali rispetto a un gold set di documenti
2. **MRR** (Mean Reciprocal Rank) — quanto velocemente il documento giusto sale in testa
3. **Latency p95** per query end-to-end (encode + chroma search)
4. **Memoria peak** durante encoding di 100 documenti consecutivi
5. **Cold start** (tempo dal lancio server alla prima query risolta)
6. **Qualità multilingue** (query IT vs documenti EN, e viceversa)

## Metodologia

Script `scripts/benchmark_embeddings.py` (incluso in questa ADR):

1. Reindex un corpus reale (es. 200-500 record dal DB `privato`) con entrambi i modelli, in due Chroma collections separate
2. Esegui un set di query gold (10-20 query manuali con doc atteso noto)
3. Misura recall@5/10, MRR, latency, memoria
4. Output: tabella comparativa + decisione

**Costo del run**:
- Download bge-m3 una tantum: ~5min su connessione media (2.2GB)
- Encoding 500 record × 2 modelli: ~5-10min su M1
- Query 20 × 2 modelli: ~30s
- Totale: ~15-20 minuti

## Decisione (pending)

A oggi, il default è MiniLM (zero-friction, già nel bundle). La promozione a bge-m3 verrà confermata se il benchmark mostra:

- **Recall@5 ≥ +15% assoluto** (esempio: da 0.65 a 0.80)
- **MRR ≥ +0.10**
- **Latency p95 < 500ms** end-to-end (vincolo non funzionale)

Se bge-m3 vince: aggiornare default in `apps/server/src/istefox_dt_mcp_server/deps.py`, documentare il primo-download (~2.2GB) nel README come "opzionale per qualità superiore". Lasciare MiniLM come fallback per dispositivi con poca RAM.

Se MiniLM vince o pareggia: confermarlo come default permanente, chiudere la valutazione, rimuovere l'ADR-008 dal `Proposed`.

## Fuori scope

- Modelli proprietary (OpenAI text-embedding-3, Cohere embed-v3) — esclusi per privacy by design (ADR-001 §"locale only")
- Re-rankers (es. ms-marco-MiniLM-L-6-v2) — feature post-MVP, valutazione separata
- Sparse retrieval (SPLADE, BGE-sparse) — Chroma embedded non li supporta nativamente

## Decisione per release 0.1.0 (Deferred)

Per la **0.1.0** (release pubblica iniziale) il benchmark è **rinviato a 0.2.0**. Razionale:

1. **Single-corpus bias**: un benchmark su un solo DB DEVONthink (quello dello sviluppatore) non è rappresentativo della varietà di workload utente. Decidere il default in base a un corpus solo rischia di scegliere male.
2. **GOLD_QUERIES manuali**: 10-20 coppie `(query, expected_uuid)` rappresentative richiedono ore di curation focused. Bloccare la 0.1.0 su questo lavoro è inefficiente quando il valore principale (i 6 tool MCP + audit + undo) è già pronto.
3. **Pattern feature flag**: il codice è già pronto per opt-in (`ISTEFOX_RAG_ENABLED=1` env var). Spedire **RAG opt-in experimental** in 0.1.0 e usare il feedback degli early adopter per costruire un dataset di valutazione cross-corpus per 0.2.0 è la strada più solida.

### Cosa entra in 0.1.0

- ✅ Tutto il codice RAG di W5-W6 (provider, hybrid RRF, ask_database vector path, reindex/reconcile/watch CLI, smart-rule template)
- ✅ MiniLM-L12-v2 come default (zero download, ~120MB, già nel bundle)
- ✅ Documentazione "RAG opt-in experimental" in README + tool description di `ask_database`
- ❌ Nessun benchmark eseguito, nessun verdict di default

### Cosa entra in 0.2.0 (criteri di sblocco)

- Benchmark eseguito su almeno **3 corpus distinti** (lo sviluppatore + 2 early adopter raccolti via GitHub issue)
- GOLD_QUERIES per ciascun corpus (10-20 query)
- Verdict scritto in questa ADR (status: Accepted)
- Se MiniLM vince o pareggia → resta default. Se bge-m3 vince con i criteri sotto → flip default
- ADR uscita da "Deferred", marcata "Accepted"

### Criteri di sblocco bge-m3 default (invariati)

- **Recall@5 ≥ +15% assoluto** (es. da 0.65 a 0.80, mediato sui 3 corpus)
- **MRR ≥ +0.10**
- **Latency p95 < 500ms** end-to-end
- **Memoria peak < 4GB** durante reindex 500 doc

## Status corrente

Framework di benchmark pronto in `scripts/benchmark_embeddings.py`. Il run effettivo è bloccato in attesa di:
1. Curation GOLD_QUERIES (sviluppatore: post-0.1.0)
2. Raccolta corpus + query da almeno 2 early adopter (issue GitHub: post-0.1.0)

Risultato + decisione finale aggiorneranno questa ADR per la 0.2.0.
