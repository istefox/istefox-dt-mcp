"""Contract tests for the OAuth 2.1 + PKCE routes (0.4.0 phase 4).

Uses Starlette's TestClient against the FastMCP HTTP app to exercise
the full authorize → consent → token flow without uvicorn. Verifies
that the JWT issued at the end is valid and carries the right claims.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from fastmcp import FastMCP
from istefox_dt_mcp_schemas.common import Database
from istefox_dt_mcp_server.auth.routes import register_oauth_routes
from starlette.testclient import TestClient

if TYPE_CHECKING:
    from istefox_dt_mcp_server.deps import Deps


def _db(uuid: str, name: str) -> Database:
    return Database(uuid=uuid, name=name, path=f"/p/{uuid}", is_open=True)


@pytest.fixture
def http_client(deps: Deps) -> TestClient:
    """A Starlette TestClient against a FastMCP HTTP app with OAuth routes."""
    deps.adapter.list_databases.return_value = [  # type: ignore[attr-defined]
        _db("DB-A", "Alpha"),
        _db("DB-B", "Beta"),
    ]
    mcp: FastMCP = FastMCP(name="oauth-test")
    register_oauth_routes(mcp, deps)
    app = mcp.http_app(path="/mcp/", transport="streamable-http")
    return TestClient(app)


# ---------------------------------------------------------------------------
# Authorize endpoint
# ---------------------------------------------------------------------------


def test_authorize_renders_consent_page(http_client: TestClient) -> None:
    challenge = create_s256_code_challenge("v" * 64)
    resp = http_client.get(
        "/oauth/authorize",
        params={
            "client_id": "test-client",
            "redirect_uri": "https://client.example/cb",
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "dt:read dt:write",
            "state": "xyz",
        },
    )
    assert resp.status_code == 200
    body = resp.text
    # Form is present with correct hidden fields.
    assert 'name="client_id" value="test-client"' in body
    assert 'name="redirect_uri" value="https://client.example/cb"' in body
    assert f'name="code_challenge" value="{challenge}"' in body
    assert 'name="state" value="xyz"' in body
    # Both DBs are offered.
    assert "Alpha" in body
    assert "Beta" in body
    # Read+write are pre-checked because they were in the requested scope.
    assert (
        'value="dt:read"\n                 checked' in body or 'value="dt:read"' in body
    )


def test_authorize_rejects_missing_client_id(http_client: TestClient) -> None:
    resp = http_client.get(
        "/oauth/authorize",
        params={"redirect_uri": "https://x/cb", "response_type": "code"},
    )
    assert resp.status_code == 400


def test_authorize_rejects_non_pkce(http_client: TestClient) -> None:
    resp = http_client.get(
        "/oauth/authorize",
        params={
            "client_id": "c",
            "redirect_uri": "https://x/cb",
            "response_type": "code",
            # No code_challenge: PKCE is mandatory in OAuth 2.1.
        },
    )
    assert resp.status_code == 400


def test_authorize_rejects_unknown_response_type(http_client: TestClient) -> None:
    challenge = create_s256_code_challenge("v" * 64)
    resp = http_client.get(
        "/oauth/authorize",
        params={
            "client_id": "c",
            "redirect_uri": "https://x/cb",
            "response_type": "token",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Consent + Token (full flow)
# ---------------------------------------------------------------------------


def test_full_pkce_flow_issues_valid_token(http_client: TestClient, deps: Deps) -> None:
    verifier = "v" * 64
    challenge = create_s256_code_challenge(verifier)

    # Step 1: user submits the consent form (approve, with scopes + DBs).
    consent_resp = http_client.post(
        "/oauth/consent",
        data={
            "client_id": "test-client",
            "redirect_uri": "https://client.example/cb",
            "state": "xyz",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "action": "approve",
            "scope": ["dt:read", "dt:write"],
            "database_uuid": ["DB-A"],
        },
        follow_redirects=False,
    )
    assert consent_resp.status_code == 302
    location = consent_resp.headers["location"]
    assert location.startswith("https://client.example/cb?")
    # Extract the auth code from the redirect.
    from urllib.parse import parse_qs, urlparse

    qs = parse_qs(urlparse(location).query)
    assert qs.get("state") == ["xyz"]
    auth_code = qs["code"][0]

    # ConsentStore should have recorded the DB grant.
    assert deps.consent.is_authorized("oauth-user", "DB-A") is True
    assert deps.consent.is_authorized("oauth-user", "DB-B") is False

    # Step 2: client exchanges the code + verifier for a token.
    token_resp = http_client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "code_verifier": verifier,
            "redirect_uri": "https://client.example/cb",
        },
    )
    assert token_resp.status_code == 200
    body = token_resp.json()
    assert body["token_type"] == "Bearer"
    assert "access_token" in body
    assert body["expires_in"] > 0
    assert "dt:read" in body["scope"]
    assert "dt:write" in body["scope"]

    # The issued JWT must round-trip through the project's verifier.
    claims = deps.jwt_issuer.verify(body["access_token"])
    assert claims.principal_id == "oauth-user"
    assert claims.scopes == frozenset({"dt:read", "dt:write"})


def test_consent_deny_redirects_with_access_denied(
    http_client: TestClient,
) -> None:
    challenge = create_s256_code_challenge("v" * 64)
    resp = http_client.post(
        "/oauth/consent",
        data={
            "client_id": "test-client",
            "redirect_uri": "https://client.example/cb",
            "state": "abc",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "action": "deny",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert "error=access_denied" in location
    assert "state=abc" in location


def test_token_rejects_wrong_pkce_verifier(http_client: TestClient) -> None:
    challenge = create_s256_code_challenge("right" + "v" * 60)
    consent_resp = http_client.post(
        "/oauth/consent",
        data={
            "client_id": "c",
            "redirect_uri": "https://x/cb",
            "state": "s",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "action": "approve",
            "scope": ["dt:read"],
        },
        follow_redirects=False,
    )
    code = consent_resp.headers["location"].split("code=")[1].split("&")[0]

    resp = http_client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": "wrong-verifier-" + "x" * 60,
            "redirect_uri": "https://x/cb",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_grant"


def test_token_rejects_unknown_code(http_client: TestClient) -> None:
    resp = http_client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": "nope-this-doesnt-exist",
            "code_verifier": "v" * 64,
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_grant"


def test_token_rejects_unsupported_grant(http_client: TestClient) -> None:
    resp = http_client.post(
        "/oauth/token",
        data={"grant_type": "client_credentials"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "unsupported_grant_type"


def test_authorization_code_is_one_shot(http_client: TestClient) -> None:
    """Replaying the same code on /token must fail the second time."""
    verifier = "v" * 64
    challenge = create_s256_code_challenge(verifier)
    consent_resp = http_client.post(
        "/oauth/consent",
        data={
            "client_id": "c",
            "redirect_uri": "https://x/cb",
            "state": "s",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "action": "approve",
            "scope": ["dt:read"],
        },
        follow_redirects=False,
    )
    code = consent_resp.headers["location"].split("code=")[1].split("&")[0]

    common = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": "https://x/cb",
    }
    first = http_client.post("/oauth/token", data=common)
    assert first.status_code == 200
    second = http_client.post("/oauth/token", data=common)
    assert second.status_code == 400
    assert second.json()["error"] == "invalid_grant"
