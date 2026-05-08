"""safe_call scope-gating tests (0.4.0 phase 2).

Verifies the enforcement path inside `tools/_common.py::safe_call` for
the ``required_scope`` parameter:

- when the request context grants the required scope, the operation
  runs normally;
- when it doesn't, the operation is *not* executed and the envelope
  carries `error_code=OAUTH_INSUFFICIENT_SCOPE` with a friendly message
  + recovery_hint;
- the audit log records both the success case and the denial.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from istefox_dt_mcp_schemas.common import Envelope
from istefox_dt_mcp_server.auth.scope import (
    RequestContext,
    Scope,
    reset_request_context,
    set_request_context,
)
from istefox_dt_mcp_server.tools._common import (
    OAUTH_INSUFFICIENT_SCOPE,
    safe_call,
)

if TYPE_CHECKING:
    from istefox_dt_mcp_server.deps import Deps


class _DummyOutput(Envelope[dict[str, Any]]):
    pass


async def _ok_op() -> dict[str, Any]:
    return {"ran": True}


async def _should_not_run_op() -> dict[str, Any]:
    raise AssertionError("operation must not run when scope is missing")


@pytest.mark.asyncio
async def test_safe_call_runs_when_scope_granted(deps: Deps) -> None:
    ctx = RequestContext(principal_id="t", granted_scopes=frozenset({Scope.WRITE}))
    token = set_request_context(ctx)
    try:
        result = await safe_call(
            tool_name="test_write_tool",
            input_data={"x": 1},
            deps=deps,
            operation=_ok_op,
            output_factory=_DummyOutput,
            required_scope=Scope.WRITE,
        )
    finally:
        reset_request_context(token)
    assert result.success is True
    assert result.error_code is None
    assert result.data == {"ran": True}


@pytest.mark.asyncio
async def test_safe_call_short_circuits_when_scope_missing(deps: Deps) -> None:
    ctx = RequestContext(principal_id="t", granted_scopes=frozenset({Scope.READ}))
    token = set_request_context(ctx)
    try:
        result = await safe_call(
            tool_name="test_write_tool",
            input_data={"x": 1},
            deps=deps,
            operation=_should_not_run_op,
            output_factory=_DummyOutput,
            required_scope=Scope.WRITE,
        )
    finally:
        reset_request_context(token)
    assert result.success is False
    assert result.error_code == OAUTH_INSUFFICIENT_SCOPE
    assert "dt:write" in (result.error_message or "")
    assert "dt:write" in (result.recovery_hint or "")
    # Even on denial we get an audit_id, so the operator can correlate
    # the rejected attempt with logs.
    assert result.audit_id is not None


@pytest.mark.asyncio
async def test_safe_call_unset_context_grants_all_scopes(deps: Deps) -> None:
    """Unit tests / scripts calling safe_call without a request bound.

    Default behavior is permissive (current_scopes() returns ALL_SCOPES)
    so unit tests don't need to set up auth plumbing for read tools.
    """
    # No set_request_context call here — context is the default.
    result = await safe_call(
        tool_name="test_read_tool",
        input_data={},
        deps=deps,
        operation=_ok_op,
        output_factory=_DummyOutput,
        required_scope=Scope.READ,
    )
    assert result.success is True


@pytest.mark.asyncio
async def test_safe_call_no_required_scope_skips_check(deps: Deps) -> None:
    """Backward-compat: tools that don't pass required_scope are unaffected."""
    ctx = RequestContext(principal_id="t", granted_scopes=frozenset())
    token = set_request_context(ctx)
    try:
        result = await safe_call(
            tool_name="legacy_tool",
            input_data={},
            deps=deps,
            operation=_ok_op,
            output_factory=_DummyOutput,
            # required_scope omitted
        )
    finally:
        reset_request_context(token)
    assert result.success is True
