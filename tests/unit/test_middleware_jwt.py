"""ScopeMiddleware JWT integration tests (0.4.0 phase 4).

Verifies the bearer-token resolution path:
- valid Bearer JWT → RequestContext populated from claims
- invalid Bearer → http-anon principal with empty scopes
- no Authorization header → falls back to X-Istefox-Scope CSV
- stdio (no HTTP request) → ALL_SCOPES for local-stdio
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from istefox_dt_mcp_server.auth.middleware import _resolve_http_context
from istefox_dt_mcp_server.auth.scope import Scope

if TYPE_CHECKING:
    from istefox_dt_mcp_server.auth.oauth import JWTIssuer


def _fake_request(headers: dict[str, str]) -> MagicMock:
    """Synthetic Starlette-Request stand-in carrying just headers."""
    req = MagicMock()
    # Starlette headers are case-insensitive; mimic .get with lower keys.
    lowered = {k.lower(): v for k, v in headers.items()}
    req.headers = lowered
    return req


def _patch_get_http_request(
    monkeypatch: pytest.MonkeyPatch, headers: dict[str, str]
) -> None:
    """Force `get_http_request()` to return a fake request with `headers`."""
    fake = _fake_request(headers)
    monkeypatch.setattr("fastmcp.server.dependencies.get_http_request", lambda: fake)


def test_no_http_context_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """When there's no HTTP request bound, _resolve_http_context returns None."""

    def _raise() -> None:
        raise RuntimeError("not in HTTP context")

    monkeypatch.setattr("fastmcp.server.dependencies.get_http_request", _raise)
    assert _resolve_http_context(None) is None


def test_valid_bearer_token_populates_context(
    monkeypatch: pytest.MonkeyPatch, jwt_issuer: JWTIssuer
) -> None:
    token, _ = jwt_issuer.issue(principal_id="alice", scopes=["dt:read", "dt:write"])
    _patch_get_http_request(monkeypatch, {"Authorization": f"Bearer {token}"})

    ctx = _resolve_http_context(jwt_issuer)
    assert ctx is not None
    assert ctx.principal_id == "alice"
    assert ctx.granted_scopes == frozenset({Scope.READ, Scope.WRITE})


def test_bearer_with_invalid_signature_falls_back_to_anon(
    monkeypatch: pytest.MonkeyPatch, jwt_issuer: JWTIssuer
) -> None:
    """Tampered token → http-anon, no scopes."""
    token, _ = jwt_issuer.issue(principal_id="alice", scopes=["dt:read"])
    tampered = token[:-4] + "xxxx"
    _patch_get_http_request(monkeypatch, {"Authorization": f"Bearer {tampered}"})

    ctx = _resolve_http_context(jwt_issuer)
    assert ctx is not None
    assert ctx.principal_id == "http-anon"
    assert ctx.granted_scopes == frozenset()


def test_no_bearer_falls_back_to_csv_header(
    monkeypatch: pytest.MonkeyPatch, jwt_issuer: JWTIssuer
) -> None:
    """No Authorization header → testing X-Istefox-Scope is used."""
    _patch_get_http_request(
        monkeypatch,
        {
            "X-Istefox-Scope": "dt:read,dt:admin",
            "X-Istefox-Principal": "tester",
        },
    )

    ctx = _resolve_http_context(jwt_issuer)
    assert ctx is not None
    assert ctx.principal_id == "tester"
    assert ctx.granted_scopes == frozenset({Scope.READ, Scope.ADMIN})


def test_no_headers_at_all_yields_anon_with_no_scopes(
    monkeypatch: pytest.MonkeyPatch, jwt_issuer: JWTIssuer
) -> None:
    _patch_get_http_request(monkeypatch, {})
    ctx = _resolve_http_context(jwt_issuer)
    assert ctx is not None
    assert ctx.principal_id == "http-anon"
    assert ctx.granted_scopes == frozenset()


def test_bearer_with_unknown_scope_strings_ignores_them(
    monkeypatch: pytest.MonkeyPatch, jwt_issuer: JWTIssuer
) -> None:
    """A token carrying a scope value we don't recognize is filtered out."""
    # Hand-issue a token with a bogus scope mixed in.
    from joserfc import jwt as joserfc_jwt
    from joserfc.jwk import OctKey

    secret_bytes = jwt_issuer.secret.get()
    forged = joserfc_jwt.encode(
        {"alg": "HS256"},
        {
            "iss": jwt_issuer.ISSUER,
            "aud": jwt_issuer.AUDIENCE,
            "sub": "alice",
            "scope": "dt:read garbage:scope dt:write",
            "iat": 1,
            "exp": 9_999_999_999,
        },
        OctKey.import_key(secret_bytes),
    )
    _patch_get_http_request(monkeypatch, {"Authorization": f"Bearer {forged}"})

    ctx = _resolve_http_context(jwt_issuer)
    assert ctx is not None
    assert ctx.granted_scopes == frozenset({Scope.READ, Scope.WRITE})
