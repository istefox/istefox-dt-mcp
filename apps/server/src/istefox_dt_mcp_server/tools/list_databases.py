"""list_databases tool — enumerate open DEVONthink databases.

In 0.4.0 the output is filtered through the ConsentStore: HTTP
principals only see databases they've explicitly authorized via the
consent flow. The stdio principal (``local-stdio``) is treated as
fully authorized — single-user local-trust scenario.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from istefox_dt_mcp_schemas.tools import (
    ListDatabasesInput,
    ListDatabasesOutput,
)

from ..auth.scope import Scope, current_context
from ._common import safe_call

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from istefox_dt_mcp_schemas.common import Database

    from ..deps import Deps


def register(mcp: FastMCP, deps: Deps) -> None:
    @mcp.tool()
    async def list_databases(
        input: ListDatabasesInput,  # noqa: A002
    ) -> ListDatabasesOutput:
        async def op() -> list[Database]:
            all_dbs = await deps.adapter.list_databases()
            ctx = current_context()
            # Without an HTTP request bound (stdio, scripts, unit
            # tests calling the function directly) ctx is None →
            # treat as local-stdio (full visibility). With an HTTP
            # request, filter through the ConsentStore.
            if ctx is None:
                return all_dbs
            return deps.consent.filter_visible(ctx.principal_id, all_dbs)

        return await safe_call(
            tool_name="list_databases",
            input_data=input.model_dump(),
            deps=deps,
            operation=op,
            output_factory=ListDatabasesOutput,
            required_scope=Scope.READ,
        )
