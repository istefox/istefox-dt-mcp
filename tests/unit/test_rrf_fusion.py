"""Reciprocal Rank Fusion (RRF) — pure-function unit tests."""

from __future__ import annotations

from istefox_dt_mcp_schemas.rag import RAGHit
from istefox_dt_mcp_server.tools.search import RRF_K, _rrf_fuse


def _hit(uuid: str, score: float = 0.9) -> RAGHit:
    return RAGHit(uuid=uuid, score=score, snippet="", metadata={})


def test_rrf_orders_by_combined_rank() -> None:
    bm25 = ["A", "B", "C"]
    rag = [_hit("B"), _hit("D")]
    out = _rrf_fuse(bm25, rag, max_results=4)
    uuids = [u for u, _ in out]
    # B is in both lists at top → must win
    assert uuids[0] == "B"
    assert set(uuids) == {"A", "B", "C", "D"}


def test_rrf_score_formula() -> None:
    # Single list at rank 0 → score = 1 / (k + 1)
    out = _rrf_fuse(["X"], [], max_results=1)
    assert out[0][1] == 1.0 / (RRF_K + 1)


def test_rrf_empty_inputs() -> None:
    assert _rrf_fuse([], [], max_results=10) == []


def test_rrf_handles_only_bm25() -> None:
    out = _rrf_fuse(["A", "B"], [], max_results=10)
    assert [u for u, _ in out] == ["A", "B"]


def test_rrf_handles_only_rag() -> None:
    out = _rrf_fuse([], [_hit("A"), _hit("B")], max_results=10)
    assert [u for u, _ in out] == ["A", "B"]


def test_rrf_truncates_to_max_results() -> None:
    out = _rrf_fuse(["A", "B", "C", "D"], [], max_results=2)
    assert len(out) == 2


def test_rrf_doc_in_both_lists_beats_top_of_one() -> None:
    # "Z" is rank 0 in both, "A" is rank 0 only in bm25
    bm25 = ["A", "Z"]
    rag = [_hit("Z"), _hit("B")]
    out = _rrf_fuse(bm25, rag, max_results=3)
    # Z must come first because it's boosted by appearing in both
    assert out[0][0] == "Z"
