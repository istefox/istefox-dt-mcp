"""Server-wide dependency container.

Tools receive a `Deps` instance with all the wired components. This
keeps tools testable (inject mocks) and the server bootstrap
declarative.

RAG provider is config-driven (env `ISTEFOX_RAG_ENABLED=1` enables
the same-process ChromaRAGProvider, otherwise the NoopRAGProvider
is used and `search`/`ask_database` degrade to BM25-only).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from istefox_dt_mcp_adapter.cache import SQLiteCache
from istefox_dt_mcp_adapter.jxa import JXAAdapter
from istefox_dt_mcp_adapter.rag import NoopRAGProvider

from .audit import AuditLog
from .i18n import Translator

if TYPE_CHECKING:
    from istefox_dt_mcp_adapter.contract import DEVONthinkAdapter
    from istefox_dt_mcp_adapter.rag import RAGProvider


log = structlog.get_logger(__name__)

DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / "istefox-dt-mcp"


@dataclass
class Deps:
    adapter: DEVONthinkAdapter
    audit: AuditLog
    translator: Translator
    cache: SQLiteCache | None
    rag: RAGProvider


def _build_rag_provider(base: Path) -> RAGProvider:
    """Select the RAG provider based on env / defaults.

    `ISTEFOX_RAG_ENABLED=1`  → ChromaRAGProvider (same-process)
    `ISTEFOX_RAG_MODEL=...`  → override embedding model
    everything else          → NoopRAGProvider (BM25-only fallback)
    """
    if os.environ.get("ISTEFOX_RAG_ENABLED", "0").lower() not in {"1", "true", "yes"}:
        log.info("rag_disabled", reason="ISTEFOX_RAG_ENABLED not set")
        return NoopRAGProvider()

    # Lazy import — avoids loading torch/chromadb when RAG is off
    from istefox_dt_mcp_sidecar.chroma_provider import (
        DEFAULT_MODEL,
        ChromaRAGProvider,
    )

    model_name = os.environ.get("ISTEFOX_RAG_MODEL", DEFAULT_MODEL)
    db_dir = base / "vectors"
    log.info("rag_enabled", provider="chroma", model=model_name, db=str(db_dir))
    return ChromaRAGProvider(db_dir=db_dir, model_name=model_name)


def build_default_deps(
    *,
    data_dir: Path | None = None,
    pool_size: int = 4,
    timeout_s: float = 5.0,
) -> Deps:
    """Wire the default production dependency graph.

    RAG provider selection is env-driven (see `_build_rag_provider`).
    The default is `NoopRAGProvider` so the server starts fast and
    works without any extra setup; enable Chroma with
    `ISTEFOX_RAG_ENABLED=1`.
    """
    base = data_dir or DEFAULT_DATA_DIR
    base.mkdir(parents=True, exist_ok=True)

    cache = SQLiteCache(base / "cache.sqlite", default_ttl_s=60.0)
    adapter = JXAAdapter(pool_size=pool_size, timeout_s=timeout_s, cache=cache)
    audit = AuditLog(base / "audit.sqlite")
    translator = Translator()
    rag = _build_rag_provider(base)

    return Deps(
        adapter=adapter,
        audit=audit,
        translator=translator,
        cache=cache,
        rag=rag,
    )
