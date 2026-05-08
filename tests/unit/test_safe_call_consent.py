"""safe_call envelope path for ReconsentRequiredError (0.4.0 phase 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from istefox_dt_mcp_schemas.common import Envelope
from istefox_dt_mcp_server.auth.consent import ReconsentRequiredError
from istefox_dt_mcp_server.auth.scope import (
    RequestContext,
    Scope,
    reset_request_context,
    set_request_context,
)
from istefox_dt_mcp_server.tools._common import RECONSENT_REQUIRED, safe_call

if TYPE_CHECKING:
    from istefox_dt_mcp_server.deps import Deps


class _DummyOutput(Envelope[dict[str, Any]]):
    pass


@pytest.mark.asyncio
async def test_reconsent_required_becomes_envelope(deps: Deps) -> None:
    """An op that raises ReconsentRequiredError → RECONSENT_REQUIRED envelope."""
    ctx = RequestContext(
        principal_id="alice",
        granted_scopes=frozenset({Scope.WRITE}),
    )
    token = set_request_context(ctx)

    async def op() -> dict[str, Any]:
        raise ReconsentRequiredError(
            principal_id="alice",
            database_uuid="DB-XYZ",
            database_name="Customer Files",
        )

    try:
        result = await safe_call(
            tool_name="file_document",
            input_data={"record_uuid": "u1"},
            deps=deps,
            operation=op,
            output_factory=_DummyOutput,
            required_scope=Scope.WRITE,
        )
    finally:
        reset_request_context(token)

    assert result.success is False
    assert result.error_code == RECONSENT_REQUIRED
    # Surface the DB context in the message so the consent UI can
    # render the right checkbox.
    assert "Customer Files" in (result.error_message or "")
    assert "DB-XYZ" in (result.error_message or "")
    assert "consent flow" in (result.recovery_hint or "")
    # Failed attempts are still audited.
    assert result.audit_id is not None


@pytest.mark.asyncio
async def test_reconsent_uses_uuid_only_when_no_name(deps: Deps) -> None:
    ctx = RequestContext(
        principal_id="alice",
        granted_scopes=frozenset({Scope.WRITE}),
    )
    token = set_request_context(ctx)

    async def op() -> dict[str, Any]:
        raise ReconsentRequiredError(
            principal_id="alice",
            database_uuid="DB-XYZ",
        )

    try:
        result = await safe_call(
            tool_name="bulk_apply",
            input_data={},
            deps=deps,
            operation=op,
            output_factory=_DummyOutput,
            required_scope=Scope.WRITE,
        )
    finally:
        reset_request_context(token)

    assert result.success is False
    assert result.error_code == RECONSENT_REQUIRED
    assert "DB-XYZ" in (result.error_message or "")
