"""Shared pytest fixtures.

Provides:
- `tmp_data_dir`: fresh data directory for cache + audit
- `mock_adapter`: AsyncMock implementing DEVONthinkAdapter
- `audit_log`: a fresh AuditLog backed by tmp_data_dir
- `cache`: a fresh SQLiteCache backed by tmp_data_dir
- `translator`: italian Translator
- `deps`: full Deps wired with mocked adapter
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from istefox_dt_mcp_adapter.cache import SQLiteCache
from istefox_dt_mcp_adapter.contract import DEVONthinkAdapter
from istefox_dt_mcp_adapter.rag import NoopRAGProvider
from istefox_dt_mcp_server.audit import AuditLog
from istefox_dt_mcp_server.deps import Deps
from istefox_dt_mcp_server.i18n import Translator


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    p = tmp_path / "data"
    p.mkdir()
    return p


@pytest.fixture
def cache(tmp_data_dir: Path) -> SQLiteCache:
    return SQLiteCache(tmp_data_dir / "cache.sqlite", default_ttl_s=60.0)


@pytest.fixture
def audit_log(tmp_data_dir: Path) -> AuditLog:
    return AuditLog(tmp_data_dir / "audit.sqlite")


@pytest.fixture
def translator() -> Translator:
    return Translator()


@pytest.fixture
def mock_adapter() -> AsyncMock:
    return AsyncMock(spec=DEVONthinkAdapter)


@pytest.fixture
def deps(
    mock_adapter: AsyncMock,
    audit_log: AuditLog,
    translator: Translator,
    cache: SQLiteCache,
) -> Deps:
    return Deps(
        adapter=mock_adapter,
        audit=audit_log,
        translator=translator,
        cache=cache,
        rag=NoopRAGProvider(),
    )
