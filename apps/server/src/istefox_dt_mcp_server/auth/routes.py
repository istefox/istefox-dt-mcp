"""OAuth 2.1 + PKCE HTTP routes (0.4.0 phase 4).

Three endpoints registered on the FastMCP HTTP transport via
``mcp.custom_route``:

- ``GET /oauth/authorize``: shows the consent UI.
- ``POST /oauth/consent``: records the user's choices, mints an
  authorization code, redirects to the client's redirect_uri.
- ``POST /oauth/token``: exchanges the code (+ PKCE code_verifier)
  for a bearer JWT.

The flow assumes a single principal per server (single-user v1, ADR-006
NG1). The consent UI hard-codes ``principal_id="oauth-user"``; future
multi-user deployments would gate this behind a real login.

Errors return small HTML pages on GET endpoints and JSON envelopes on
POST endpoints, per OAuth 2.1 conventions.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from urllib.parse import urlencode

import structlog
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .consent_ui import render_consent_page, render_simple_error
from .oauth import verify_pkce_s256

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from starlette.requests import Request

    from ..deps import Deps

log = structlog.get_logger(__name__)


# Until the server grows real user accounts, every OAuth flow runs as
# this synthetic principal. The principal_id is what gets baked into
# the JWT `sub` claim and what ConsentStore keys grants on.
DEFAULT_PRINCIPAL_ID = "oauth-user"


def register_oauth_routes(mcp: FastMCP, deps: Deps) -> None:
    """Mount /oauth/* on the FastMCP HTTP server.

    Idempotent w.r.t. the FastMCP instance — calling twice would
    register the routes twice (caller's responsibility to do once).
    """

    @mcp.custom_route("/oauth/authorize", methods=["GET"])
    async def authorize(request: Request) -> Response:
        return await _authorize_get(request, deps)

    @mcp.custom_route("/oauth/consent", methods=["POST"])
    async def consent(request: Request) -> Response:
        return await _consent_post(request, deps)

    @mcp.custom_route("/oauth/token", methods=["POST"])
    async def token(request: Request) -> Response:
        return await _token_post(request, deps)

    log.info(
        "oauth_routes_registered",
        paths=["/oauth/authorize", "/oauth/consent", "/oauth/token"],
    )


# ---------------------------------------------------------------------------
# Authorize: render the consent UI
# ---------------------------------------------------------------------------


async def _authorize_get(request: Request, deps: Deps) -> Response:
    """Render the consent UI from the query string parameters.

    OAuth 2.1 PKCE requires: client_id, redirect_uri, response_type=code,
    code_challenge, code_challenge_method=S256, scope, state.
    """
    q = request.query_params
    client_id = q.get("client_id", "").strip()
    redirect_uri = q.get("redirect_uri", "").strip()
    response_type = q.get("response_type", "").strip()
    code_challenge = q.get("code_challenge", "").strip()
    code_challenge_method = q.get("code_challenge_method", "").strip()
    scope = q.get("scope", "").strip()
    state = q.get("state", "")

    if not client_id or not redirect_uri:
        return HTMLResponse(
            render_simple_error(
                "Missing parameters",
                "client_id and redirect_uri are required.",
                status=400,
            ),
            status_code=400,
        )
    if response_type != "code":
        return HTMLResponse(
            render_simple_error(
                "Unsupported response_type",
                f"Only response_type=code is supported (got {response_type!r}).",
                status=400,
            ),
            status_code=400,
        )
    if not code_challenge or code_challenge_method != "S256":
        return HTMLResponse(
            render_simple_error(
                "PKCE required",
                "code_challenge with code_challenge_method=S256 is required.",
                status=400,
            ),
            status_code=400,
        )

    # Discover currently-open databases so the user can tick the ones
    # they want to authorize. We deliberately list ALL of them (not
    # the principal's existing grants) so the user can extend the
    # authorized set in this consent.
    try:
        databases = await deps.adapter.list_databases()
    except Exception as e:
        log.warning("authorize_list_databases_failed", error=str(e))
        databases = []

    requested_scopes = frozenset(s for s in scope.split(" ") if s)

    return HTMLResponse(
        render_consent_page(
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            requested_scopes=requested_scopes,
            databases=databases,
        )
    )


# ---------------------------------------------------------------------------
# Consent: process the form, mint an auth code, redirect to client
# ---------------------------------------------------------------------------


def _form_str(form: object, key: str) -> str:
    """Read a form field as a string. UploadFile values become empty.

    Starlette's form values can be either ``str`` or ``UploadFile``;
    OAuth fields are always strings, so coercing the union here keeps
    the rest of the route handler's types simple.
    """
    val = form.get(key) if hasattr(form, "get") else None
    if isinstance(val, str):
        return val
    return ""


async def _consent_post(request: Request, deps: Deps) -> Response:
    form = await request.form()
    action = _form_str(form, "action")
    client_id = _form_str(form, "client_id").strip()
    redirect_uri = _form_str(form, "redirect_uri").strip()
    state = _form_str(form, "state")
    code_challenge = _form_str(form, "code_challenge").strip()
    code_challenge_method = _form_str(form, "code_challenge_method").strip()

    if not client_id or not redirect_uri or not code_challenge:
        return HTMLResponse(
            render_simple_error(
                "Missing parameters",
                "client_id, redirect_uri and code_challenge are required.",
                status=400,
            ),
            status_code=400,
        )
    if code_challenge_method != "S256":
        return HTMLResponse(
            render_simple_error(
                "PKCE required",
                "code_challenge_method must be S256.",
                status=400,
            ),
            status_code=400,
        )

    if action == "deny":
        # OAuth 2.1: deny → redirect with error=access_denied + state.
        params = {"error": "access_denied", "state": state}
        return RedirectResponse(f"{redirect_uri}?{urlencode(params)}", status_code=302)

    # Approve path: collect ticked scopes + databases, persist consent,
    # mint an authorization code, redirect to the client.
    granted_scope_values = [str(v) for v in form.getlist("scope")]
    granted_db_uuids = [str(v) for v in form.getlist("database_uuid")]

    # Persist DB grants for the canonical principal so subsequent tool
    # calls (with the JWT) pass ConsentStore.is_authorized.
    if granted_db_uuids:
        deps.consent.authorize(DEFAULT_PRINCIPAL_ID, granted_db_uuids)

    code = deps.auth_codes.issue(
        principal_id=DEFAULT_PRINCIPAL_ID,
        granted_scopes=granted_scope_values,
        granted_database_uuids=granted_db_uuids,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
    )

    log.info(
        "oauth_consent_granted",
        client_id=client_id,
        scopes=granted_scope_values,
        databases_count=len(granted_db_uuids),
    )
    params = {"code": code, "state": state}
    return RedirectResponse(f"{redirect_uri}?{urlencode(params)}", status_code=302)


# ---------------------------------------------------------------------------
# Token: exchange auth_code + code_verifier for a bearer JWT
# ---------------------------------------------------------------------------


def _token_error(error: str, description: str, status: int = 400) -> Response:
    """OAuth 2.1 token endpoint error envelope (RFC 6749 §5.2)."""
    body = {"error": error, "error_description": description}
    return JSONResponse(body, status_code=status)


async def _token_post(request: Request, deps: Deps) -> Response:
    # token endpoint accepts application/x-www-form-urlencoded per RFC.
    # JSON is also tolerated for client convenience.
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            data = await request.json()
        except json.JSONDecodeError:
            return _token_error("invalid_request", "malformed JSON body")
    else:
        form = await request.form()
        data = {k: form.get(k) for k in form}

    grant_type = (data.get("grant_type") or "").strip()
    code = (data.get("code") or "").strip()
    code_verifier = (data.get("code_verifier") or "").strip()
    redirect_uri = (data.get("redirect_uri") or "").strip()

    if grant_type != "authorization_code":
        return _token_error(
            "unsupported_grant_type",
            f"only authorization_code is supported (got {grant_type!r})",
        )
    if not code or not code_verifier:
        return _token_error(
            "invalid_request",
            "code and code_verifier are required",
        )

    record = deps.auth_codes.consume(code)
    if record is None:
        return _token_error(
            "invalid_grant",
            "authorization code is invalid or expired",
        )
    if redirect_uri and record.redirect_uri != redirect_uri:
        return _token_error(
            "invalid_grant",
            "redirect_uri does not match the original authorization request",
        )
    if not verify_pkce_s256(code_verifier, record.code_challenge):
        return _token_error(
            "invalid_grant",
            "PKCE code_verifier does not match the recorded code_challenge",
        )

    jwt_token, _expires_at = deps.jwt_issuer.issue(
        principal_id=record.principal_id,
        scopes=record.granted_scopes,
    )
    return JSONResponse(
        {
            "access_token": jwt_token,
            "token_type": "Bearer",
            "expires_in": deps.jwt_issuer.ttl_s,
            "scope": " ".join(sorted(record.granted_scopes)),
        }
    )
