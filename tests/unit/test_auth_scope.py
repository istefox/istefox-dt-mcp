"""Unit tests for the OAuth scope plumbing (0.4.0 phase 2).

Covers the public surface of `auth/scope.py`: the enum, RequestContext,
contextvar helpers, and the InsufficientScopeError.
"""

from __future__ import annotations

import pytest
from istefox_dt_mcp_server.auth.scope import (
    ALL_SCOPES,
    InsufficientScopeError,
    RequestContext,
    Scope,
    current_context,
    current_scopes,
    has_scope,
    reset_request_context,
    set_request_context,
)


def test_scope_enum_has_three_values_per_adr_006() -> None:
    """ADR-006 fixes the three OAuth scopes."""
    assert {s.value for s in Scope} == {"dt:read", "dt:write", "dt:admin"}


def test_all_scopes_constant_includes_every_value() -> None:
    assert frozenset(Scope) == ALL_SCOPES


def test_unset_context_returns_none() -> None:
    """No request bound → no context."""
    assert current_context() is None


def test_unset_context_grants_all_scopes_for_local_use() -> None:
    """Helpers default to permissive when no request is in flight."""
    assert current_scopes() == ALL_SCOPES
    assert has_scope(Scope.READ) is True
    assert has_scope(Scope.WRITE) is True
    assert has_scope(Scope.ADMIN) is True


def test_set_and_reset_round_trip() -> None:
    ctx = RequestContext(
        principal_id="alice",
        granted_scopes=frozenset({Scope.READ}),
    )
    token = set_request_context(ctx)
    try:
        assert current_context() is ctx
        assert current_scopes() == frozenset({Scope.READ})
        assert has_scope(Scope.READ) is True
        assert has_scope(Scope.WRITE) is False
    finally:
        reset_request_context(token)
    # After reset, defaults restored.
    assert current_context() is None
    assert current_scopes() == ALL_SCOPES


def test_request_context_is_frozen() -> None:
    ctx = RequestContext(principal_id="alice", granted_scopes=frozenset({Scope.READ}))
    with pytest.raises(Exception):
        ctx.principal_id = "mallory"  # type: ignore[misc]


def test_insufficient_scope_error_carries_required_and_granted() -> None:
    err = InsufficientScopeError(
        required=Scope.WRITE,
        granted=frozenset({Scope.READ}),
        principal_id="alice",
    )
    assert err.required is Scope.WRITE
    assert err.granted == frozenset({Scope.READ})
    assert err.principal_id == "alice"
    # The string repr lists both for diagnostics.
    msg = str(err)
    assert "dt:write" in msg
    assert "dt:read" in msg
