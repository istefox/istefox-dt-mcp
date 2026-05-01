"""search tool — BM25 full-text search via DEVONthink native engine.

Vector / hybrid retrieval will be added in W6 once the RAG sidecar
ships. The mode parameter is accepted today but only "bm25" is
honored; other modes log a warning and fall back to bm25.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from istefox_dt_mcp_schemas.tools import SearchInput, SearchOutput

from ._common import safe_call

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from ..deps import Deps


log = structlog.get_logger(__name__)


def register(mcp: FastMCP, deps: Deps) -> None:
    @mcp.tool()
    async def search(input: SearchInput) -> SearchOutput:  # noqa: A002
        if input.mode != "bm25":
            log.warning(
                "search_mode_not_yet_supported",
                requested=input.mode,
                fallback="bm25",
            )

        kinds = [k.value for k in input.kinds] if input.kinds else None

        async def op():
            return await deps.adapter.search(
                input.query,
                databases=input.databases,
                max_results=input.max_results,
                kinds=kinds,
            )

        return await safe_call(
            tool_name="search",
            input_data=input.model_dump(mode="json"),
            deps=deps,
            operation=op,
            output_factory=SearchOutput,
        )
