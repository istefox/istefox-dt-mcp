"""Benchmark MiniLM vs bge-m3 on a real DEVONthink corpus.

Output: a side-by-side comparison table on stderr + a JSON report on
stdout. Drives ADR-008 (embedding model selection).

Usage:
    # 1. Edit GOLD_QUERIES below with real (query, expected_uuid) pairs
    #    obtained from your DEVONthink — at least 10-20 for meaningful
    #    metrics. Run `istefox-dt-mcp search "term"` to find candidates.
    # 2. Pick a corpus database (e.g. "privato") with 200-500 records
    # 3. Run:
    #       uv run python scripts/benchmark_embeddings.py \\
    #           --database privato --limit 500 \\
    #           --report-json /tmp/embedding-bench.json
    # 4. Review output, paste verdict into docs/adr/0008-*.md

Cost: ~15-20 min total. bge-m3 first-load downloads ~2.2GB.

Requirements: DT4 running, RAG already wired (ISTEFOX_RAG_ENABLED=1
in env, or just rely on the script which builds its own provider).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

# Add libs to path so the script can run without an editable install
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "libs" / "adapter" / "src"))
sys.path.insert(0, str(ROOT / "libs" / "schemas" / "src"))
sys.path.insert(0, str(ROOT / "apps" / "sidecar" / "src"))


# ---------------------------------------------------------------------
# CONFIGURE THESE BEFORE RUNNING
# ---------------------------------------------------------------------

# Pairs of (query, expected_uuid). Find UUIDs via:
#   uv run istefox-dt-mcp serve   (then in a chat: search "your term")
# At least 10 pairs for meaningful recall@k. 20-30 is better.
GOLD_QUERIES: list[tuple[str, str]] = [
    # Example placeholders — replace with your real corpus
    # ("piano strategico vibrazioni", "8BFBF5DA-D4C6-454F-8B4F-8B9D656211D3"),
    # ("rimborso spese viaggio", "..."),
]

MODELS = [
    "paraphrase-multilingual-MiniLM-L12-v2",  # default, ~120MB
    "BAAI/bge-m3",  # ~2.2GB, higher quality
]

# ---------------------------------------------------------------------


@dataclass
class ModelMetrics:
    model: str
    n_indexed: int = 0
    index_duration_s: float = 0.0
    encode_avg_ms: float = 0.0
    query_latencies_ms: list[float] = field(default_factory=list)
    recall_at_5: float = 0.0
    recall_at_10: float = 0.0
    mrr: float = 0.0
    cold_start_s: float = 0.0
    peak_memory_mb: float | None = None

    def query_p95_ms(self) -> float:
        if not self.query_latencies_ms:
            return 0.0
        s = sorted(self.query_latencies_ms)
        return s[int(len(s) * 0.95)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "n_indexed": self.n_indexed,
            "index_duration_s": round(self.index_duration_s, 2),
            "encode_avg_ms": round(self.encode_avg_ms, 2),
            "query_p95_ms": round(self.query_p95_ms(), 2),
            "recall_at_5": round(self.recall_at_5, 3),
            "recall_at_10": round(self.recall_at_10, 3),
            "mrr": round(self.mrr, 3),
            "cold_start_s": round(self.cold_start_s, 2),
            "peak_memory_mb": self.peak_memory_mb,
        }


async def benchmark_model(
    model_name: str,
    *,
    records: list[dict[str, Any]],
    queries: list[tuple[str, str]],
    chroma_dir: Path,
) -> ModelMetrics:
    """Build a fresh Chroma collection with `model_name` and benchmark."""
    from istefox_dt_mcp_sidecar.chroma_provider import ChromaRAGProvider

    metrics = ModelMetrics(model=model_name)
    print(f"\n>>> {model_name}", file=sys.stderr)

    # Cold start: lazy load the model on first use
    t0 = time.perf_counter()
    provider = ChromaRAGProvider(
        persist_dir=chroma_dir / model_name.replace("/", "_"),
        embedding_model=model_name,
    )
    # Force lazy load with a no-op query so cold_start is measured
    await provider.query("warmup", k=1)
    metrics.cold_start_s = time.perf_counter() - t0
    print(f"    cold start: {metrics.cold_start_s:.2f}s", file=sys.stderr)

    # Index phase
    t0 = time.perf_counter()
    encode_times: list[float] = []
    for rec in records:
        et0 = time.perf_counter()
        await provider.index(
            uuid=rec["uuid"],
            text=rec["text"],
            metadata={
                "name": rec.get("name", ""),
                "database": rec.get("database", ""),
            },
        )
        encode_times.append((time.perf_counter() - et0) * 1000)
    metrics.index_duration_s = time.perf_counter() - t0
    metrics.n_indexed = len(records)
    metrics.encode_avg_ms = statistics.mean(encode_times) if encode_times else 0
    print(
        f"    indexed {metrics.n_indexed} records in "
        f"{metrics.index_duration_s:.1f}s "
        f"(avg encode {metrics.encode_avg_ms:.1f}ms)",
        file=sys.stderr,
    )

    # Query phase: measure latency + relevance
    hits_at_5 = 0
    hits_at_10 = 0
    rr_total = 0.0
    for query, expected_uuid in queries:
        qt0 = time.perf_counter()
        results = await provider.query(query, k=10)
        latency_ms = (time.perf_counter() - qt0) * 1000
        metrics.query_latencies_ms.append(latency_ms)

        result_uuids = [r.uuid for r in results]
        if expected_uuid in result_uuids[:5]:
            hits_at_5 += 1
        if expected_uuid in result_uuids[:10]:
            hits_at_10 += 1
        if expected_uuid in result_uuids:
            rank = result_uuids.index(expected_uuid) + 1
            rr_total += 1.0 / rank

    n_queries = max(len(queries), 1)
    metrics.recall_at_5 = hits_at_5 / n_queries
    metrics.recall_at_10 = hits_at_10 / n_queries
    metrics.mrr = rr_total / n_queries
    print(
        f"    recall@5={metrics.recall_at_5:.2f} "
        f"recall@10={metrics.recall_at_10:.2f} "
        f"mrr={metrics.mrr:.2f} "
        f"p95={metrics.query_p95_ms():.0f}ms",
        file=sys.stderr,
    )

    return metrics


async def fetch_corpus(database: str, limit: int) -> list[dict[str, Any]]:
    """Pull records from DT via the JXAAdapter."""
    from istefox_dt_mcp_adapter.jxa import JXAAdapter

    adapter = JXAAdapter(pool_size=2, timeout_s=10.0, max_retries=2)
    records, _ = await adapter.enumerate_records(database, limit=limit)
    print(f"corpus: {len(records)} records from '{database}'", file=sys.stderr)
    out: list[dict[str, Any]] = []
    for rec in records:
        text = await adapter.get_record_text(rec["uuid"], max_chars=4000)
        if text.strip():
            out.append(
                {
                    "uuid": rec["uuid"],
                    "name": rec.get("name", ""),
                    "text": text,
                    "database": database,
                }
            )
    return out


def print_comparison(results: list[ModelMetrics]) -> None:
    """Pretty-print a side-by-side table on stderr."""
    print("\n" + "=" * 70, file=sys.stderr)
    print(f"{'Metric':<22}", end="", file=sys.stderr)
    for m in results:
        print(f"{m.model[:22]:<24}", end="", file=sys.stderr)
    print(file=sys.stderr)
    print("-" * 70, file=sys.stderr)

    rows = [
        ("recall@5", "recall_at_5"),
        ("recall@10", "recall_at_10"),
        ("MRR", "mrr"),
        ("query p95 (ms)", "query_p95_ms"),
        ("encode avg (ms)", "encode_avg_ms"),
        ("cold start (s)", "cold_start_s"),
        ("index time (s)", "index_duration_s"),
    ]
    for label, key in rows:
        print(f"{label:<22}", end="", file=sys.stderr)
        for m in results:
            d = m.to_dict()
            v = d.get(key, "—")
            print(f"{v!s:<24}", end="", file=sys.stderr)
        print(file=sys.stderr)
    print("=" * 70, file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        required=True,
        help="DEVONthink database name to source the corpus from",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Max records to index (default 200)",
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        help="Write JSON report to this path",
    )
    args = parser.parse_args()

    if not GOLD_QUERIES:
        print(
            "ERROR: GOLD_QUERIES is empty. Edit this script first to add\n"
            "10-20 (query, expected_uuid) pairs from your real corpus.\n"
            "Without a gold set, recall/MRR cannot be measured.",
            file=sys.stderr,
        )
        sys.exit(2)

    async def run() -> dict[str, Any]:
        print("Fetching corpus from DT…", file=sys.stderr)
        records = asyncio.run(fetch_corpus(args.database, args.limit))
        if not records:
            print("ERROR: no records fetched. DT4 running?", file=sys.stderr)
            sys.exit(1)

        results: list[ModelMetrics] = []
        with TemporaryDirectory() as tmp:
            chroma_dir = Path(tmp)
            for model in MODELS:
                m = await benchmark_model(
                    model,
                    records=records,
                    queries=GOLD_QUERIES,
                    chroma_dir=chroma_dir,
                )
                results.append(m)

        print_comparison(results)
        return {
            "corpus": {
                "database": args.database,
                "n_records": len(records),
                "n_queries": len(GOLD_QUERIES),
            },
            "models": [m.to_dict() for m in results],
        }

    report = asyncio.run(run())
    print(json.dumps(report, indent=2))

    if args.report_json:
        args.report_json.write_text(json.dumps(report, indent=2))
        print(f"\nReport saved to {args.report_json}", file=sys.stderr)


if __name__ == "__main__":
    main()
