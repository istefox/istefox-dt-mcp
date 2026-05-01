"""Server-wide dependency container.

Tools receive a `Deps` instance with all the wired components. This
keeps tools testable (inject mocks) and the server bootstrap
declarative.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from istefox_dt_mcp_adapter.cache import SQLiteCache
from istefox_dt_mcp_adapter.jxa import JXAAdapter
from istefox_dt_mcp_adapter.rag import NoopRAGProvider

from .audit import AuditLog
from .i18n import Translator

if TYPE_CHECKING:
    from istefox_dt_mcp_adapter.contract import DEVONthinkAdapter
    from istefox_dt_mcp_adapter.rag import RAGProvider

DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / "istefox-dt-mcp"


@dataclass
class Deps:
    adapter: DEVONthinkAdapter
    audit: AuditLog
    translator: Translator
    cache: SQLiteCache | None
    rag: RAGProvider


def build_default_deps(
    *,
    data_dir: Path | None = None,
    pool_size: int = 4,
    timeout_s: float = 5.0,
) -> Deps:
    """Wire the default production dependency graph.

    RAG defaults to NoopRAGProvider until the sidecar lands in W5-6.
    `search` and `ask_database` work in BM25-only mode under noop.
    """
    base = data_dir or DEFAULT_DATA_DIR
    base.mkdir(parents=True, exist_ok=True)

    cache = SQLiteCache(base / "cache.sqlite", default_ttl_s=60.0)
    adapter = JXAAdapter(pool_size=pool_size, timeout_s=timeout_s, cache=cache)
    audit = AuditLog(base / "audit.sqlite")
    translator = Translator()
    rag = NoopRAGProvider()

    return Deps(
        adapter=adapter,
        audit=audit,
        translator=translator,
        cache=cache,
        rag=rag,
    )
