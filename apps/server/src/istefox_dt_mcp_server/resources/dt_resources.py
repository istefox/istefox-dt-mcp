"""DEVONthink MCP resources (0.5.0).

Pure async builders hold the logic (testable without FastMCP); thin
`@mcp.resource` wrappers delegate through `safe_resource`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from istefox_dt_mcp_schemas.tools import DatabaseListResource

from ..auth.scope import current_context
from ._common import safe_resource

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from ..deps import Deps


async def build_databases_payload(deps: Deps) -> dict[str, Any]:
    """Consent-filtered, uuid-sorted list of open databases."""
    all_dbs = await deps.adapter.list_databases()
    ctx = current_context()
    if ctx is None:
        visible = list(all_dbs)
    else:
        visible = deps.consent.filter_visible(ctx.principal_id, all_dbs)
    visible_sorted = sorted(visible, key=lambda d: d.uuid)
    model = DatabaseListResource(databases=visible_sorted, truncated=False)
    return model.model_dump(mode="json")


def register(mcp: FastMCP, deps: Deps) -> None:
    @mcp.resource(
        "dt://databases",
        name="dt-databases",
        mime_type="application/json",
        description=(
            "Open DEVONthink databases visible to the caller "
            "(consent-filtered). Deterministic, bounded, read-only."
        ),
    )
    async def dt_databases() -> str:
        return await safe_resource(
            uri="dt://databases",
            deps=deps,
            operation=lambda: build_databases_payload(deps),
        )
