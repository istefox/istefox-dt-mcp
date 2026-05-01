"""find_related tool — DEVONthink See Also / Compare wrapper."""

from __future__ import annotations

from typing import TYPE_CHECKING

from istefox_dt_mcp_schemas.tools import FindRelatedInput, FindRelatedOutput

from ._common import safe_call

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from istefox_dt_mcp_schemas.common import RelatedResult

    from ..deps import Deps


def register(mcp: FastMCP, deps: Deps) -> None:
    @mcp.tool()
    async def find_related(input: FindRelatedInput) -> FindRelatedOutput:  # noqa: A002
        async def op() -> list[RelatedResult]:
            return await deps.adapter.find_related(input.uuid, k=input.k)

        return await safe_call(
            tool_name="find_related",
            input_data=input.model_dump(),
            deps=deps,
            operation=op,
            output_factory=FindRelatedOutput,
        )
