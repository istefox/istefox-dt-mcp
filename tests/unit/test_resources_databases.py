"""dt://databases resource tests (0.5.0)."""

from __future__ import annotations

import json
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
from istefox_dt_mcp_server.resources.dt_resources import (
    build_databases_payload,
    register,
)

if TYPE_CHECKING:
    from istefox_dt_mcp_server.deps import Deps


def _db(uuid: str, name: str) -> Database:
    return Database(uuid=uuid, name=name, path=f"/p/{uuid}", is_open=True)


@pytest.fixture
def all_dbs() -> list[Database]:
    return [_db("DB-C", "Gamma"), _db("DB-A", "Alpha"), _db("DB-B", "Beta")]


@pytest.mark.asyncio
async def test_stdio_sees_all_sorted_by_uuid(deps: Deps, all_dbs) -> None:
    deps.adapter.list_databases.return_value = all_dbs  # type: ignore[attr-defined]
    payload = await build_databases_payload(deps)
    uuids = [d["uuid"] for d in payload["databases"]]
    assert uuids == ["DB-A", "DB-B", "DB-C"]  # deterministic order
    assert payload["truncated"] is False


@pytest.mark.asyncio
async def test_determinism_byte_identical(deps: Deps, all_dbs) -> None:
    deps.adapter.list_databases.return_value = all_dbs  # type: ignore[attr-defined]
    a = json.dumps(await build_databases_payload(deps), sort_keys=True)
    b = json.dumps(await build_databases_payload(deps), sort_keys=True)
    assert a == b


@pytest.mark.asyncio
async def test_http_principal_filtered_by_consent(deps: Deps, all_dbs) -> None:
    deps.adapter.list_databases.return_value = all_dbs  # type: ignore[attr-defined]
    deps.consent.authorize("alice", "DB-B")
    ctx = RequestContext(principal_id="alice", granted_scopes=frozenset({Scope.READ}))
    token = set_request_context(ctx)
    try:
        payload = await build_databases_payload(deps)
    finally:
        reset_request_context(token)
    assert [d["uuid"] for d in payload["databases"]] == ["DB-B"]


@pytest.mark.asyncio
async def test_resource_registered_and_readable(deps: Deps, all_dbs) -> None:
    deps.adapter.list_databases.return_value = all_dbs  # type: ignore[attr-defined]
    mcp: FastMCP = FastMCP(name="test")
    register(mcp, deps)
    result = await mcp.read_resource("dt://databases")
    body = result.contents[0].content
    parsed = json.loads(body)
    assert {d["uuid"] for d in parsed["databases"]} == {"DB-A", "DB-B", "DB-C"}
