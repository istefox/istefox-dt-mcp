"""RAG-layer schemas.

Shared by the RAG provider abstraction (`libs/adapter/.../rag.py`)
and the eventual sidecar implementation (W5-6: `apps/sidecar`).
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import StrictModel


class RAGHit(StrictModel):
    """One semantic-search hit returned by the RAG provider."""

    uuid: str
    score: float = Field(..., ge=0.0, le=1.0)
    snippet: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class RAGStats(StrictModel):
    """Snapshot of the index state."""

    indexed_count: int
    last_index_at: str | None = None
    last_reconcile_at: str | None = None
    embedding_model: str | None = None


class RAGFilter(StrictModel):
    """Optional pre-filter applied before semantic ranking."""

    databases: list[str] | None = None
    tags: list[str] | None = None
    kinds: list[str] | None = None
