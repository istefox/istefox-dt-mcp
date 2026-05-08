"""list_databases consent-filtering tests (0.4.0 phase 3).

Verifies that `list_databases` respects the ConsentStore: when an HTTP
principal is bound to the request context, only authorized databases
appear in the output. Stdio (no context bound) returns everything.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastmcp import FastMCP
from istefox_dt_mcp_schemas.common import Database
from istefox_dt_mcp_server.auth.scope import (
    RequestContext,
    Scope,
    reset_request_context,
    set_request_context,
)
from istefox_dt_mcp_server.tools.list_databases import register

if TYPE_CHECKING:
    from istefox_dt_mcp_server.deps import Deps


def _db(uuid: str, name: str) -> Database:
    return Database(uuid=uuid, name=name, path=f"/p/{uuid}", is_open=True)


@pytest.fixture
def all_dbs() -> list[Database]:
    return [_db("DB-A", "Alpha"), _db("DB-B", "Beta"), _db("DB-C", "Gamma")]


@pytest.fixture
def server_with_list_databases(deps: Deps, all_dbs: list[Database]) -> FastMCP:
    """A FastMCP server with list_databases registered against `deps`.

    The mock adapter is wired to return ``all_dbs`` from list_databases().
    """
    deps.adapter.list_databases.return_value = all_dbs  # type: ignore[attr-defined]
    mcp: FastMCP = FastMCP(name="test")
    register(mcp, deps)
    return mcp


@pytest.mark.asyncio
async def test_stdio_sees_all_databases(
    server_with_list_databases: FastMCP, all_dbs: list[Database]
) -> None:
    """No request context bound (stdio) → no filtering, all DBs returned."""
    result = await server_with_list_databases.call_tool("list_databases", {"input": {}})
    body = result.structured_content
    assert body is not None
    assert body["success"] is True
    returned = body["data"]
    # The order doesn't matter; structural identity by uuid is enough.
    returned_uuids = {db["uuid"] for db in returned}
    assert returned_uuids == {db.uuid for db in all_dbs}


@pytest.mark.asyncio
async def test_http_principal_sees_only_authorized_dbs(
    server_with_list_databases: FastMCP, deps: Deps
) -> None:
    """With a request context bound, ConsentStore filters the output."""
    deps.consent.authorize("alice", "DB-B")
    ctx = RequestContext(
        principal_id="alice",
        granted_scopes=frozenset({Scope.READ}),
    )
    token = set_request_context(ctx)
    try:
        result = await server_with_list_databases.call_tool(
            "list_databases", {"input": {}}
        )
    finally:
        reset_request_context(token)

    body = result.structured_content
    assert body is not None
    assert body["success"] is True
    returned = body["data"]
    assert len(returned) == 1
    assert returned[0]["uuid"] == "DB-B"


@pytest.mark.asyncio
async def test_http_principal_with_no_grants_sees_empty_list(
    server_with_list_databases: FastMCP,
) -> None:
    """An HTTP principal that hasn't authorized any DB sees zero rows."""
    ctx = RequestContext(
        principal_id="bob",
        granted_scopes=frozenset({Scope.READ}),
    )
    token = set_request_context(ctx)
    try:
        result = await server_with_list_databases.call_tool(
            "list_databases", {"input": {}}
        )
    finally:
        reset_request_context(token)

    body = result.structured_content
    assert body is not None
    assert body["success"] is True
    assert body["data"] == []
