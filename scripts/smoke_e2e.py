#!/usr/bin/env python3
"""End-to-end smoke against a real DEVONthink 4 instance.

Run from a terminal that has Apple Events permission for DEVONthink
(e.g. /Applications/Utilities/Terminal.app — the first run will
trigger the macOS consent dialog).

    cd ~/Developer/Devonthink_MCP
    uv run python scripts/smoke_e2e.py

Outputs latency stats useful for the W2 GO/NO-GO checkpoint
(target: read p95 < 500ms).
"""

from __future__ import annotations

import asyncio
import statistics
import sys
import time

from istefox_dt_mcp_adapter.cache import SQLiteCache
from istefox_dt_mcp_adapter.errors import AdapterError
from istefox_dt_mcp_adapter.jxa import JXAAdapter

SEARCH_QUERIES = ["vibrazioni", "isolatori", "report", "test", "progetto"]
ITERATIONS_PER_OP = 5


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = round(p * (len(s) - 1))
    return s[k]


async def _measure(label: str, op, iterations: int = ITERATIONS_PER_OP) -> tuple[list[float], object]:
    samples: list[float] = []
    last = None
    for _ in range(iterations):
        t0 = time.monotonic()
        last = await op()
        samples.append((time.monotonic() - t0) * 1000.0)
    print(
        f"  [{label}] mean={statistics.mean(samples):.0f}ms  "
        f"p50={_percentile(samples, 0.50):.0f}ms  "
        f"p95={_percentile(samples, 0.95):.0f}ms  "
        f"max={max(samples):.0f}ms  (n={len(samples)})"
    )
    return samples, last


async def main() -> int:
    print("=== istefox-dt-mcp smoke E2E (real DEVONthink) ===\n")

    cache = SQLiteCache(
        path="/tmp/istefox_smoke_cache.sqlite", default_ttl_s=60.0
    )
    adapter = JXAAdapter(pool_size=4, timeout_s=10.0, cache=cache)

    # --- health ---
    health = await adapter.health_check()
    print(f"health: {health.model_dump()}\n")
    if not health.dt_running:
        print("DEVONthink not running — abort.")
        return 1

    all_samples: dict[str, list[float]] = {}

    # --- list_databases (cache disabled by hitting twice + invalidating) ---
    print("[list_databases]")
    samples, dbs = await _measure("list_databases", adapter.list_databases)
    all_samples["list_databases"] = samples
    print(f"  databases ({len(dbs)}):")  # type: ignore[arg-type]
    for db in dbs:  # type: ignore[union-attr]
        print(f"    - {db.name}")

    if not dbs:
        print("\nNo databases open — skipping search/find_related.")
        return 0

    # --- search ---
    print("\n[search]")
    for q in SEARCH_QUERIES:
        try:
            samples, results = await _measure(
                f"search '{q}'",
                lambda q=q: adapter.search(q, max_results=10),
            )
            all_samples[f"search:{q}"] = samples
            for r in results[:3]:  # type: ignore[union-attr]
                print(f"      • {r.name[:78]}")
        except AdapterError as e:
            print(f"  [search '{q}'] FAIL: {type(e).__name__}: {e}")

    # --- find_related (uses first hit of last successful search) ---
    print("\n[find_related]")
    try:
        seed_results = await adapter.search("the", max_results=1)
        if seed_results:
            seed = seed_results[0]
            samples, related = await _measure(
                f"find_related uuid={seed.uuid[:8]}",
                lambda: adapter.find_related(seed.uuid, k=10),
            )
            all_samples["find_related"] = samples
            print(f"  seed: {seed.name[:78]}")
            for r in related[:3]:  # type: ignore[union-attr]
                print(f"      • {r.name[:78]}")
        else:
            print("  no seed record available")
    except AdapterError as e:
        print(f"  FAIL: {type(e).__name__}: {e}")

    # --- W2 GO/NO-GO summary ---
    print("\n=== W2 GO/NO-GO checkpoint ===")
    all_flat = [s for samples in all_samples.values() for s in samples]
    overall_p95 = _percentile(all_flat, 0.95)
    overall_mean = statistics.mean(all_flat) if all_flat else 0
    print(f"overall mean: {overall_mean:.0f}ms")
    print(f"overall p95:  {overall_p95:.0f}ms")
    print("target:       < 500ms p95")
    status = "PASS ✓" if overall_p95 < 500 else "FAIL ✗"
    print(f"verdict:      {status}")
    return 0 if overall_p95 < 500 else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
