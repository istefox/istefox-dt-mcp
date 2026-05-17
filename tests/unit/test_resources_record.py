"""dt://record/{uuid}/{metadata,text} resource tests (0.5.0)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from fastmcp import FastMCP
from istefox_dt_mcp_schemas.common import Record
from istefox_dt_mcp_server.auth.consent import ReconsentRequiredError
from istefox_dt_mcp_server.auth.scope import (
    RequestContext,
    Scope,
    reset_request_context,
    set_request_context,
)
from istefox_dt_mcp_server.resources._common import (
    MAX_TAGS,
    RESOURCE_JSON_BUDGET_CHARS,
    RESOURCE_MAX_CHARS,
)
from istefox_dt_mcp_server.resources.dt_resources import (
    build_record_metadata_payload,
    build_record_text_payload,
    register,
)

if TYPE_CHECKING:
    from istefox_dt_mcp_server.deps import Deps


def _record(uuid: str = "R-1", tags: list[str] | None = None) -> Record:
    return Record(
        uuid=uuid,
        name="Doc",
        kind="PDF",
        location="/Inbox",
        reference_url=f"x-devonthink-item://{uuid}",
        creation_date=datetime(2026, 1, 1, tzinfo=UTC),
        modification_date=datetime(2026, 1, 2, tzinfo=UTC),
        tags=tags if tags is not None else ["a", "b"],
        database_uuid="DB-1",
    )


@pytest.mark.asyncio
async def test_metadata_payload_stdio(deps: Deps) -> None:
    deps.adapter.get_record.return_value = _record()  # type: ignore[attr-defined]
    payload = await build_record_metadata_payload(deps, "R-1")
    assert payload["record"]["uuid"] == "R-1"
    assert payload["tags_truncated"] is False


@pytest.mark.asyncio
async def test_metadata_tags_capped(deps: Deps) -> None:
    deps.adapter.get_record.return_value = _record(  # type: ignore[attr-defined]
        tags=[f"t{i}" for i in range(MAX_TAGS + 50)]
    )
    payload = await build_record_metadata_payload(deps, "R-1")
    assert len(payload["record"]["tags"]) == MAX_TAGS
    assert payload["tags_truncated"] is True


@pytest.mark.asyncio
async def test_record_consent_denied_for_http_principal(deps: Deps) -> None:
    deps.adapter.get_record.return_value = _record()  # type: ignore[attr-defined]
    ctx = RequestContext(principal_id="bob", granted_scopes=frozenset({Scope.READ}))
    token = set_request_context(ctx)
    try:
        with pytest.raises(ReconsentRequiredError):
            await build_record_metadata_payload(deps, "R-1")
    finally:
        reset_request_context(token)


@pytest.mark.asyncio
async def test_record_missing_db_uuid_fails_closed_under_http(deps: Deps) -> None:
    rec = _record().model_copy(update={"database_uuid": None})
    deps.adapter.get_record.return_value = rec  # type: ignore[attr-defined]
    ctx = RequestContext(principal_id="bob", granted_scopes=frozenset({Scope.READ}))
    token = set_request_context(ctx)
    try:
        with pytest.raises(ReconsentRequiredError):
            await build_record_metadata_payload(deps, "R-1")
    finally:
        reset_request_context(token)


@pytest.mark.asyncio
async def test_text_payload_truncation_flag(deps: Deps) -> None:
    deps.adapter.get_record.return_value = _record()  # type: ignore[attr-defined]
    deps.adapter.get_record_text.return_value = (  # type: ignore[attr-defined]
        "y" * RESOURCE_MAX_CHARS
    )
    payload = await build_record_text_payload(deps, "R-1")
    assert payload["truncated"] is True
    assert payload["returned_chars"] == RESOURCE_MAX_CHARS


@pytest.mark.asyncio
async def test_text_payload_bounded(deps: Deps) -> None:
    from istefox_dt_mcp_server.resources._common import bound_json

    deps.adapter.get_record.return_value = _record()  # type: ignore[attr-defined]
    deps.adapter.get_record_text.return_value = (  # type: ignore[attr-defined]
        "z" * (RESOURCE_JSON_BUDGET_CHARS * 3)
    )
    payload = await build_record_text_payload(deps, "R-1")
    assert len(bound_json(payload)) <= RESOURCE_JSON_BUDGET_CHARS


@pytest.mark.asyncio
async def test_record_resources_registered(deps: Deps) -> None:
    deps.adapter.get_record.return_value = _record()  # type: ignore[attr-defined]
    deps.adapter.get_record_text.return_value = "hello"  # type: ignore[attr-defined]
    mcp = FastMCP(name="test")
    register(mcp, deps)

    meta = await mcp.read_resource("dt://record/R-1/metadata")
    assert json.loads(meta.contents[0].content)["record"]["uuid"] == "R-1"

    txt = await mcp.read_resource("dt://record/R-1/text")
    assert json.loads(txt.contents[0].content)["text"] == "hello"
