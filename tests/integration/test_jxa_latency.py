"""Real-DT JXA latency benchmark — validates the W2 GO/NO-GO target.

The architecture brief sets a p95 read-latency target of < 500ms.
This benchmark exercises `adapter.get_record(uuid)` against a real
DEVONthink instance and asserts the *mean* round-trip stays under
that threshold (mean is the metric pytest-benchmark exposes
directly; p95 would require parsing stats.stats which is brittle).

Skipped by default. Run with:

    uv run pytest tests/integration -m "integration and benchmark" \\
        --benchmark-enable
"""

from __future__ import annotations

import asyncio

import pytest
from istefox_dt_mcp_adapter.jxa import JXAAdapter

# Both markers required: `integration` for the env-gate, `benchmark`
# so the run is opt-in even within the integration session.
pytestmark = [pytest.mark.integration, pytest.mark.benchmark]

# GO/NO-GO threshold from the brief (W2 milestone).
_TARGET_MEAN_S = 0.500
# Number of round-trips per benchmark sample. 30 keeps the test
# under ~15s on a healthy DT (assuming ~200-400ms/call) while giving
# pytest-benchmark enough samples for stable statistics.
_ROUNDS = 30


_BROAD_QUERY = "the"


def test_get_record_latency_p95_under_500ms(
    benchmark: object,
    real_adapter: JXAAdapter,
    first_open_database: str,
) -> None:
    """Repeatedly fetch a known record; assert mean < 500ms.

    Note: pytest-benchmark's `benchmark()` is a sync callable. We
    bridge to async by calling `asyncio.run(...)` inside the timed
    function — this is acceptable here because the benchmark target
    is the JXA round-trip (hundreds of ms), not the event-loop setup
    cost (microseconds).
    """

    # One-shot search to obtain a real UUID. Done outside the timed
    # body so search latency doesn't pollute the get_record numbers.
    async def _seed() -> str:
        hits = await real_adapter.search(
            _BROAD_QUERY,
            databases=[first_open_database],
            max_results=1,
        )
        if not hits:
            pytest.skip(
                f"No hits for '{_BROAD_QUERY}' in '{first_open_database}' — "
                "open a DB with content and retry"
            )
        # str() coercion: schemas pkg is `Any` under mypy strict
        # because of `ignore_missing_imports = true`.
        return str(hits[0].uuid)

    seed_uuid = asyncio.run(_seed())

    async def _fetch() -> None:
        await real_adapter.get_record(seed_uuid)

    def _run() -> None:
        asyncio.run(_fetch())

    # `benchmark.pedantic` gives us explicit control over rounds/iterations.
    # We treat `benchmark` as an opaque object here (its type is provided
    # by pytest-benchmark and not statically importable).
    benchmark.pedantic(_run, rounds=_ROUNDS, iterations=1, warmup_rounds=2)  # type: ignore[attr-defined]

    # When pytest is invoked with `--benchmark-disable` (the default
    # in pyproject.toml addopts), pedantic still calls _run but
    # doesn't populate stats. Skip with a clear, actionable message
    # instead of raising AttributeError on `.stats.stats.mean`.
    if benchmark.stats is None:  # type: ignore[attr-defined]
        pytest.skip(
            "benchmark stats unavailable (pytest invoked with "
            "--benchmark-disable). Re-run with --benchmark-enable: "
            "uv run pytest tests/integration -m integration "
            "--benchmark-enable -v"
        )

    mean_s = benchmark.stats.stats.mean  # type: ignore[attr-defined]
    assert mean_s < _TARGET_MEAN_S, (
        f"get_record mean latency {mean_s * 1000:.1f}ms exceeds "
        f"GO/NO-GO target {_TARGET_MEAN_S * 1000:.0f}ms"
    )
