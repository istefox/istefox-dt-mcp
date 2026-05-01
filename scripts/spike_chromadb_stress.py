#!/usr/bin/env python3
"""ChromaDB embedded stress test (ADR-003 spike).

Validates that ChromaDB embedded + a multilingual sentence-transformer
can sustain the production-realistic load described in ADR-003:

- N indexed records (default 5K, target 50K)
- Mixed read/write workload for D seconds
- Configurable query concurrency

Pass criteria (from ADR-003 §"Spike preventivo"):
- Query p95 < 300ms
- No deadlock / corruption
- Memory sustained < 3 GB
- All ops succeed

Usage:
    cd ~/Developer/Devonthink_MCP

    # Quick (~5 min) — tiny model, 5K records
    uv run python scripts/spike_chromadb_stress.py

    # Full target (~30-60 min depending on hardware)
    uv run python scripts/spike_chromadb_stress.py \\
        --records 50000 \\
        --duration 300 \\
        --model BAAI/bge-m3

    # Tiny smoke (~1 min)
    uv run python scripts/spike_chromadb_stress.py \\
        --records 500 --duration 30
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import random
import resource
import statistics
import sys
import time
import uuid
from pathlib import Path

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"  # ~120 MB, fast
TARGET_MODEL = "BAAI/bge-m3"  # ~2.2 GB, production candidate

# Italian-flavored seed words / phrases — enough lexical diversity
# that embeddings spread out in the vector space.
SEED_TOPICS = [
    "vibrazioni meccaniche",
    "isolatori antivibranti",
    "spettro sismico",
    "modello agli elementi finiti",
    "smorzamento viscoso",
    "frequenza naturale",
    "trasmissibilità dinamica",
    "carico statico",
    "trespoli industriali",
    "datacenter HVAC",
    "rivestimento ceramico",
    "ossido di silicio",
    "trattamento termico acciaio",
    "saldatura TIG",
    "taglio laser inox",
    "prova non distruttiva",
    "ispezione ultrasonora",
    "report tecnico cliente",
    "preventivo articolo gomma",
    "specifica tecnica progetto",
]
SEED_VERBS = ["analizza", "verifica", "misura", "calcola", "documenta", "propone"]
SEED_ADJ = [
    "specifico",
    "industriale",
    "dimensionato",
    "ottimizzato",
    "verificato",
    "certificato",
]


def synth_doc(rng: random.Random, idx: int) -> tuple[str, str, dict[str, str]]:
    """Generate one synthetic record (uuid, text, metadata)."""
    n_topics = rng.randint(2, 4)
    topics = rng.sample(SEED_TOPICS, n_topics)
    verb = rng.choice(SEED_VERBS)
    adj = rng.choice(SEED_ADJ)
    text = (
        f"Documento #{idx}. Il presente documento {verb} aspetti {adj} "
        f"riguardanti {', '.join(topics)}. "
        f"Le rilevazioni sono state condotte con metodologia standard. "
        f"I risultati sono coerenti con l'esperienza maturata nel settore."
    )
    rec_id = str(uuid.uuid4())
    metadata = {
        "kind": rng.choice(["pdf", "rtf", "markdown"]),
        "database": rng.choice(["Business", "privato"]),
        "year": str(rng.randint(2020, 2026)),
    }
    return rec_id, text, metadata


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = round(p * (len(s) - 1))
    return s[k]


def memory_mb() -> float:
    """Resident set size in MB (cross-platform: macOS bytes, Linux KB)."""
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return rss / (1024 * 1024)
    return rss / 1024


async def run_spike(args: argparse.Namespace) -> int:
    print("=== ChromaDB stress spike (ADR-003) ===")
    print(f"records: {args.records}")
    print(f"duration: {args.duration}s")
    print(f"query workers: {args.query_workers}")
    print(f"write rps: {args.write_rps}")
    print(f"embedding model: {args.model}")
    print()

    rng = random.Random(args.seed)
    db_dir = Path(args.db_dir).expanduser()
    if db_dir.exists() and args.fresh:
        import shutil

        shutil.rmtree(db_dir)
    db_dir.mkdir(parents=True, exist_ok=True)

    # ----- 1. Load model -----
    print("[1/4] Loading embedding model (first run = download)...")
    t0 = time.monotonic()
    model = SentenceTransformer(args.model)
    print(f"  loaded in {(time.monotonic() - t0):.1f}s, memory={memory_mb():.0f} MB\n")

    # ----- 2. Init ChromaDB -----
    print("[2/4] Initializing ChromaDB embedded...")
    client = chromadb.PersistentClient(
        path=str(db_dir), settings=Settings(anonymized_telemetry=False)
    )
    collection = client.get_or_create_collection(
        name="spike", metadata={"hnsw:space": "cosine"}
    )
    initial_count = collection.count()
    print(f"  collection 'spike' opened, existing count={initial_count}\n")

    # ----- 3. Index N records -----
    print(f"[3/4] Indexing {args.records} synthetic records...")
    t0 = time.monotonic()
    records = [synth_doc(rng, i) for i in range(args.records)]

    batch = max(args.records // 50, 32)
    for start in range(0, len(records), batch):
        chunk = records[start : start + batch]
        ids = [r[0] for r in chunk]
        docs = [r[1] for r in chunk]
        metas = [r[2] for r in chunk]
        embeds = model.encode(
            docs, convert_to_numpy=True, show_progress_bar=False
        ).tolist()
        collection.upsert(ids=ids, embeddings=embeds, documents=docs, metadatas=metas)
        if start % (batch * 10) == 0 and start > 0:
            elapsed = time.monotonic() - t0
            rate = (start + len(chunk)) / elapsed
            print(
                f"    {start + len(chunk):>6} indexed, {rate:.1f} rec/s, mem={memory_mb():.0f} MB"
            )
    indexing_time = time.monotonic() - t0
    print(
        f"  indexed {len(records)} in {indexing_time:.1f}s ({len(records) / indexing_time:.1f} rec/s)\n"
    )
    gc.collect()

    # ----- 4. Mixed read/write load -----
    print(
        f"[4/4] Running mixed load for {args.duration}s ({args.query_workers} query workers + {args.write_rps} write/s)..."
    )
    query_latencies_ms: list[float] = []
    query_errors = 0
    write_count = 0
    write_errors = 0
    mem_samples: list[float] = []
    deadline = time.monotonic() + args.duration

    sample_queries = [
        "vibrazioni datacenter",
        "isolatori per trespoli",
        "spettro sismico verifica",
        "report tecnico ceramico",
        "preventivo articolo gomma",
        "saldatura inox certificata",
    ]

    async def query_worker(worker_id: int) -> None:
        local_rng = random.Random(args.seed + worker_id)
        while time.monotonic() < deadline:
            q = local_rng.choice(sample_queries)
            try:
                emb = await asyncio.to_thread(
                    model.encode, [q], convert_to_numpy=True, show_progress_bar=False
                )
                t1 = time.monotonic()
                await asyncio.to_thread(
                    collection.query,
                    query_embeddings=emb.tolist(),
                    n_results=10,
                )
                query_latencies_ms.append((time.monotonic() - t1) * 1000)
            except Exception as e:
                nonlocal_query_errors_inc()
                print(f"    query error worker {worker_id}: {e}")
            await asyncio.sleep(0.01)  # small breather

    # Use a dict to keep error counters mutable from nested closures
    error_counters = {"query": 0, "write": 0}

    def nonlocal_query_errors_inc() -> None:
        error_counters["query"] += 1

    async def write_worker() -> None:
        local_rng = random.Random(args.seed + 9999)
        interval = 1.0 / max(args.write_rps, 0.1)
        next_at = time.monotonic()
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_at:
                rec_id, text, meta = synth_doc(local_rng, write_count + args.records)
                try:
                    emb = await asyncio.to_thread(
                        model.encode,
                        [text],
                        convert_to_numpy=True,
                        show_progress_bar=False,
                    )
                    await asyncio.to_thread(
                        collection.upsert,
                        ids=[rec_id],
                        embeddings=emb.tolist(),
                        documents=[text],
                        metadatas=[meta],
                    )
                    nonlocal_write_inc()
                except Exception as e:
                    error_counters["write"] += 1
                    print(f"    write error: {e}")
                next_at += interval
            else:
                await asyncio.sleep(min(0.05, next_at - now))

    def nonlocal_write_inc() -> None:
        nonlocal write_count
        write_count += 1

    async def memory_sampler() -> None:
        while time.monotonic() < deadline:
            mem_samples.append(memory_mb())
            await asyncio.sleep(2.0)

    workers = [asyncio.create_task(query_worker(i)) for i in range(args.query_workers)]
    workers.append(asyncio.create_task(write_worker()))
    workers.append(asyncio.create_task(memory_sampler()))
    await asyncio.gather(*workers, return_exceptions=True)

    query_errors = error_counters["query"]
    write_errors = error_counters["write"]

    # ----- Report -----
    print("\n=== Spike report ===")
    n_queries = len(query_latencies_ms)
    rps = n_queries / args.duration if args.duration > 0 else 0
    print(f"queries executed: {n_queries} ({rps:.1f} q/s sustained)")
    if query_latencies_ms:
        print(
            f"query latency: mean={statistics.mean(query_latencies_ms):.0f}ms  "
            f"p50={percentile(query_latencies_ms, 0.5):.0f}ms  "
            f"p95={percentile(query_latencies_ms, 0.95):.0f}ms  "
            f"p99={percentile(query_latencies_ms, 0.99):.0f}ms  "
            f"max={max(query_latencies_ms):.0f}ms"
        )
    print(f"writes: {write_count} (errors {write_errors})")
    print(f"query errors: {query_errors}")
    print(f"memory peak: {max(mem_samples) if mem_samples else memory_mb():.0f} MB")
    print(
        f"memory mean (sampled every 2s): {statistics.mean(mem_samples) if mem_samples else 0:.0f} MB"
    )
    print(f"records in collection at end: {collection.count()}")

    # Verdict
    p95 = percentile(query_latencies_ms, 0.95) if query_latencies_ms else 0
    mem_peak_mb = max(mem_samples) if mem_samples else memory_mb()
    p95_ok = p95 < 300
    mem_ok = mem_peak_mb < 3000
    errors_ok = query_errors == 0 and write_errors == 0

    print("\n=== ADR-003 pass criteria ===")
    print(f"  query p95 < 300ms:    {'PASS' if p95_ok else 'FAIL'} ({p95:.0f}ms)")
    print(
        f"  memory < 3000 MB:     {'PASS' if mem_ok else 'FAIL'} ({mem_peak_mb:.0f} MB)"
    )
    print(
        f"  zero errors:          {'PASS' if errors_ok else 'FAIL'} (q={query_errors}, w={write_errors})"
    )
    overall = p95_ok and mem_ok and errors_ok
    print(f"  verdict:              {'PASS ✓' if overall else 'FAIL ✗'}")

    # Persist a JSON report
    report = {
        "args": vars(args),
        "indexing_time_s": round(indexing_time, 1),
        "indexing_rate_rec_per_s": round(len(records) / indexing_time, 1),
        "queries_executed": n_queries,
        "queries_per_second_sustained": round(rps, 1),
        "query_latency_ms": {
            "mean": (
                round(statistics.mean(query_latencies_ms), 1)
                if query_latencies_ms
                else 0
            ),
            "p50": round(percentile(query_latencies_ms, 0.5), 1),
            "p95": round(p95, 1),
            "p99": round(percentile(query_latencies_ms, 0.99), 1),
            "max": round(max(query_latencies_ms), 1) if query_latencies_ms else 0,
        },
        "writes_executed": write_count,
        "errors": {"query": query_errors, "write": write_errors},
        "memory_mb": {
            "peak": round(mem_peak_mb, 0),
            "mean_sampled": (
                round(statistics.mean(mem_samples), 0) if mem_samples else 0
            ),
        },
        "verdict": "PASS" if overall else "FAIL",
    }
    out_file = Path(args.report).expanduser()
    out_file.write_text(json.dumps(report, indent=2))
    print(f"\nreport JSON written to {out_file}")
    return 0 if overall else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--records", type=int, default=5000, help="N seed records to index"
    )
    parser.add_argument(
        "--duration", type=int, default=120, help="Load test duration (s)"
    )
    parser.add_argument(
        "--query-workers", type=int, default=4, help="Concurrent query workers"
    )
    parser.add_argument(
        "--write-rps", type=float, default=2.0, help="Target write rate (writes/s)"
    )
    parser.add_argument(
        "--model", default=DEFAULT_MODEL, help="sentence-transformers model id"
    )
    parser.add_argument(
        "--db-dir", default="/tmp/istefox_chroma_spike", help="ChromaDB persist dir"
    )
    parser.add_argument(
        "--report",
        default="/tmp/istefox_chroma_spike_report.json",
        help="JSON report path",
    )
    parser.add_argument("--fresh", action="store_true", help="Wipe db_dir before run")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    return asyncio.run(run_spike(args))


if __name__ == "__main__":
    sys.exit(main())
