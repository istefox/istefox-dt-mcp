"""Resource schema + helper unit tests (0.5.0)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from istefox_dt_mcp_schemas.common import Database, Record
from istefox_dt_mcp_schemas.tools import (
    DatabaseListResource,
    RecordMetadataResource,
    RecordTextResource,
)
from istefox_dt_mcp_server.auth.scope import (
    InsufficientScopeError,
    RequestContext,
    reset_request_context,
    set_request_context,
)
from istefox_dt_mcp_server.resources._common import (
    RESOURCE_JSON_BUDGET_CHARS,
    bound_json,
    safe_resource,
)


def _record(uuid: str = "R-1") -> Record:
    return Record(
        uuid=uuid,
        name="Doc",
        kind="PDF",
        location="/Inbox",
        reference_url=f"x-devonthink-item://{uuid}",
        creation_date=datetime(2026, 1, 1, tzinfo=UTC),
        modification_date=datetime(2026, 1, 2, tzinfo=UTC),
        tags=["a", "b"],
        database_uuid="DB-1",
    )


def test_database_list_resource_roundtrip() -> None:
    db = Database(uuid="DB-1", name="Alpha", path="/p", is_open=True)
    model = DatabaseListResource(databases=[db], truncated=False)
    dumped = model.model_dump(mode="json")
    assert dumped["databases"][0]["uuid"] == "DB-1"
    assert dumped["truncated"] is False


def test_record_metadata_resource_roundtrip() -> None:
    model = RecordMetadataResource(record=_record(), tags_truncated=False)
    dumped = model.model_dump(mode="json")
    assert dumped["record"]["uuid"] == "R-1"
    assert dumped["tags_truncated"] is False


def test_record_text_resource_roundtrip() -> None:
    model = RecordTextResource(
        uuid="R-1", text="hello", truncated=False, returned_chars=5
    )
    dumped = model.model_dump(mode="json")
    assert dumped == {
        "uuid": "R-1",
        "text": "hello",
        "truncated": False,
        "returned_chars": 5,
    }


def test_bound_json_small_payload_is_verbatim_and_sorted() -> None:
    body = bound_json({"b": 2, "a": 1})
    assert json.loads(body) == {"a": 1, "b": 2}
    assert body.index('"a"') < body.index('"b"')  # sort_keys


def test_bound_json_truncates_oversized_text_field() -> None:
    huge = "x" * (RESOURCE_JSON_BUDGET_CHARS * 2)
    body = bound_json(
        {"uuid": "R", "text": huge, "truncated": False, "returned_chars": len(huge)}
    )
    assert len(body) <= RESOURCE_JSON_BUDGET_CHARS
    parsed = json.loads(body)
    assert parsed["truncated"] is True
    assert parsed["returned_chars"] == len(parsed["text"])


def test_bound_json_non_text_oversized_returns_valid_error_json() -> None:
    # No string `text` field + over budget → must still be valid JSON,
    # not a corrupt hard slice.
    payload = {"blob": "q" * (RESOURCE_JSON_BUDGET_CHARS * 2)}
    body = bound_json(payload)
    assert len(body) <= RESOURCE_JSON_BUDGET_CHARS
    parsed = json.loads(body)  # must not raise
    assert parsed == {"error": "RESOURCE_OVERSIZED", "truncated": True}


@pytest.mark.asyncio
async def test_safe_resource_returns_bound_body_and_audits(deps) -> None:
    async def op() -> dict:
        return {"ok": True}

    body = await safe_resource(uri="dt://x", deps=deps, operation=op)
    assert json.loads(body) == {"ok": True}
    recent = deps.audit.list_recent(limit=1)
    assert recent[0]["tool_name"] == "resource:dt://x"
    assert recent[0]["error_code"] is None


@pytest.mark.asyncio
async def test_safe_resource_denies_when_read_scope_missing(deps) -> None:
    ctx = RequestContext(principal_id="bob", granted_scopes=frozenset())
    token = set_request_context(ctx)
    try:
        with pytest.raises(InsufficientScopeError):
            await safe_resource(
                uri="dt://x",
                deps=deps,
                operation=lambda: (_ for _ in ()).throw(
                    AssertionError("operation must not run")
                ),
            )
    finally:
        reset_request_context(token)
    recent = deps.audit.list_recent(limit=1)
    assert recent[0]["error_code"] == "OAUTH_INSUFFICIENT_SCOPE"
