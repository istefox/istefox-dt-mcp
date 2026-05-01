"""safe_call logging context: input redaction + audit_id binding."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import structlog
from istefox_dt_mcp_schemas.common import SearchResult
from istefox_dt_mcp_schemas.tools import SearchOutput
from istefox_dt_mcp_server.tools._common import _summarize_input, safe_call

if TYPE_CHECKING:
    from unittest.mock import AsyncMock

    from istefox_dt_mcp_server.deps import Deps


def test_summarize_redacts_known_sensitive_keys() -> None:
    out = _summarize_input(
        {
            "query": "very sensitive query that should not be logged in full",
            "question": "another sensitive payload",
            "snippet": "x" * 200,
            "answer": "y" * 200,
            "max_results": 10,
        }
    )
    assert out["query"].startswith("<str len=")
    assert out["question"].startswith("<str len=")
    assert out["snippet"].startswith("<str len=")
    assert out["answer"].startswith("<str len=")
    assert out["max_results"] == 10


def test_summarize_truncates_long_strings_even_if_unknown_key() -> None:
    out = _summarize_input({"some_field": "x" * 200})
    assert out["some_field"].startswith("<str len=200")


def test_summarize_summarizes_collections() -> None:
    out = _summarize_input({"items": [1, 2, 3, 4, 5], "config": {"a": 1, "b": 2}})
    assert out["items"] == "<list len=5>"
    assert out["config"] == "<dict keys=2>"


def test_summarize_passes_small_scalars_through() -> None:
    out = _summarize_input({"flag": True, "count": 42, "name": "short"})
    assert out == {"flag": True, "count": 42, "name": "short"}


@pytest.mark.asyncio
async def test_safe_call_unbinds_context_after_run(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    structlog.contextvars.clear_contextvars()
    mock_adapter.search.return_value = [
        SearchResult(uuid="u", name="n", location="/", reference_url="x-d://1")
    ]

    async def op():
        return await mock_adapter.search("x")

    await safe_call(
        tool_name="search",
        input_data={"query": "x"},
        deps=deps,
        operation=op,
        output_factory=SearchOutput,
    )

    # contextvars must be empty again — no bleed across requests
    ctx = structlog.contextvars.get_contextvars()
    assert "request_id" not in ctx
    assert "audit_id" not in ctx
    assert "tool" not in ctx
