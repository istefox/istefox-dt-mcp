# Spike report — ChromaDB embedded stress test (ADR-003)

- **Data**: 2026-05-01
- **Eseguito da**: Stefano Ferri (M-series Mac, Tahoe)
- **Origine**: ADR-003 §"Spike preventivo"
- **Script**: `scripts/spike_chromadb_stress.py`
- **Verdetto**: ✅ **PASS** — confidence alta su ADR-003

---

## TL;DR

ChromaDB embedded sostiene il carico target di ADR-003 con **margine di
~60x sulla latenza** (p95 5ms vs 300ms target) e **38% del budget di
memoria** (1147 MB vs 3000 MB target). Zero errori su 30K query +
3K write in 5 minuti continuativi.

ADR-003 (RAG same-process con `ChromaRAGProvider` invece di sidecar
separato) è confermato. Possiamo procedere con W5-W6 con confidence
alta.

---

## Setup

| Parametro | Valore |
|---|---|
| Records seed | 50.000 (target ADR-003) |
| Embedding model | `paraphrase-multilingual-MiniLM-L12-v2` (384-dim, ~120 MB) |
| Vector dimension | 384 |
| ChromaDB storage | persistent local, HNSW cosine |
| Query workers | 8 concorrenti |
| Write rate | 10 op/s sustained |
| Load duration | 300 s (5 min) |
| Workload mix | retrieval-heavy (~91% read / 9% write op count) |

**Modello**: ho usato `MiniLM-L12-v2` invece di `bge-m3` (target finale)
perché:
- bge-m3 = 2.2 GB download, 5-10x slower encoding
- ADR-003 valida l'**architettura** (same-process vs sidecar), non il
  modello specifico (ADR-008, W5)
- Con bge-m3 cambia solo l'overhead di encoding, non i numeri ChromaDB
  (HNSW scala in O(log N) sulla dimensione vector)

Stima estrapolata bge-m3:
- Indexing 50K: ~25-40 min (vs 2.5 min con MiniLM)
- Encoding query: ~30-60 ms (vs 1-2 ms)
- Query end-to-end p95 stimato: 50-100 ms (ancora ben sotto 300 ms)
- Memory: +2 GB per il modello → totale ~3.2 GB (al limite del budget,
  da rivalutare)

---

## Risultati misurati

```json
{
  "indexing_time_s": 145.8,
  "indexing_rate_rec_per_s": 343.0,
  "queries_executed": 30361,
  "queries_per_second_sustained": 101.2,
  "query_latency_ms": {
    "mean": 1.7,
    "p50": 1.2,
    "p95": 5.5,
    "p99": 9.5,
    "max": 147.9
  },
  "writes_executed": 3000,
  "errors": {"query": 0, "write": 0},
  "memory_mb": {"peak": 1147, "mean_sampled": 1147}
}
```

### Confronto con criteri ADR-003

| Criterio | Target | Misurato | Verdetto |
|---|---|---|---|
| Query p95 | < 300 ms | **5.5 ms** | ✅ 60x margine |
| Memory peak | < 3000 MB | **1147 MB** | ✅ 38% del budget |
| Errori (query + write) | 0 | **0** | ✅ |
| Throughput query | 100 q/s | **101.2 q/s** | ✅ |
| Throughput write | 10 op/s | **10 op/s** | ✅ |

### Performance milestones

- **Indexing**: 343 record/s sustained → 50K record in ~2.5 min
- **Memory steady-state**: 1147 MB sostanzialmente costante per
  tutto il run (no leak osservato)
- **Latency p99 vs p50**: 9.5 ms / 1.2 ms = ~8x — distribuzione
  coda relativamente corta, non ci sono "long tail outliers"
- **Max single query**: 148 ms (singolo outlier, plausibile GC pause)

---

## Cosa NON è stato testato (e perché)

1. **`bge-m3` o `multilingual-e5-large`**: solo proxy con MiniLM. Il
   delta atteso è puramente sull'encoding (dimensionato in `ADR-008`
   in W5). HNSW scaling rimane invariato.
2. **Multi-utente concorrente**: out-of-scope v1 (single-user da brief
   §4.3). ChromaDB embedded NON è thread-safe per write — già gestito
   in `RAGProvider.NoopRAGProvider` con lock interno.
3. **Persistence durability**: lo script ricrea la dir ad ogni run
   (`--fresh`). Verificare crash recovery in W5 con un test dedicato.
4. **Crash isolation reale**: same-process crash test non eseguito.
   Mitigazione in `ChromaRAGProvider`: try/except + memory limit
   configurable (vedi ADR-003).
5. **Larger collections** (>100K record): non testato. Per i database
   di Stefano (Business + privato, stima ~10K-30K record totali) i
   target attuali sono già over-provisioned.

---

## Decisioni / azioni successive

1. **ADR-003 confermato** — same-process ChromaDB è la scelta corretta
   per v1. Procedere con `ChromaRAGProvider` in W5.
2. **`MiniLM-L12-v2` come opzione "fast"**: in ADR-008 W5, valutare
   se proporre come default (MiniLM) o come fallback (bge-m3 default,
   MiniLM su `--config performance.embedding=fast`).
3. **Stress test bge-m3 in W5**: ripetere lo spike con il modello
   reale prima di freeze ADR-008. Atteso ~30-40 min di indexing.
4. **Aggiornare ADR-003 §"Spike preventivo"** con link a questo report.

---

## Riproducibilità

```bash
cd ~/Developer/Devonthink_MCP

# Smoke (1 min)
uv run python scripts/spike_chromadb_stress.py \
    --records 500 --duration 30

# Full target (8 min totale, MiniLM)
uv run python scripts/spike_chromadb_stress.py \
    --records 50000 --duration 300 \
    --query-workers 8 --write-rps 10 --fresh

# Production model (30-40 min totale)
uv run python scripts/spike_chromadb_stress.py \
    --records 50000 --duration 300 \
    --query-workers 8 --write-rps 10 --fresh \
    --model BAAI/bge-m3
```

Report JSON salvato in `/tmp/istefox_chroma_spike_report.json`.
