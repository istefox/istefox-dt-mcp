"""list_databases tool — enumerate open DEVONthink databases."""

from __future__ import annotations

from typing import TYPE_CHECKING

from istefox_dt_mcp_schemas.tools import (
    ListDatabasesInput,
    ListDatabasesOutput,
)

from ._common import safe_call

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from ..deps import Deps


def register(mcp: FastMCP, deps: Deps) -> None:
    @mcp.tool()
    async def list_databases(
        input: ListDatabasesInput,  # noqa: A002
    ) -> ListDatabasesOutput:
        return await safe_call(
            tool_name="list_databases",
            input_data=input.model_dump(),
            deps=deps,
            operation=deps.adapter.list_databases,
            output_factory=ListDatabasesOutput,
        )
