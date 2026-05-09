"""FastMCP middleware that populates the per-request scope context.

Three resolution paths, in priority order:

1. **stdio**: there's no HTTP request. Middleware grants ``ALL_SCOPES``
   to a synthetic ``local-stdio`` principal. Default behavior for
   Claude Desktop users (single-user, local-trust).
2. **HTTP with ``Authorization: Bearer <jwt>``**: validates the token
   via ``JWTIssuer.verify``; on success the principal_id and scopes
   come from the token claims. This is the production HTTP path
   landed in 0.4.0 phase 4.
3. **HTTP with ``X-Istefox-Scope`` (CSV) header**: testing-only
   fallback. Useful in unit/contract tests that don't want to
   run the full PKCE flow. Used only when no Bearer token is present.

Missing both header and Bearer in HTTP → empty scope set
(``http-anon`` principal), so all scope-gated tools reject.

Set by the middleware, consumed by ``safe_call`` in
``tools/_common.py`` via the contextvar in ``auth.scope``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from fastmcp.server.middleware import Middleware

from .scope import (
    ALL_SCOPES,
    RequestContext,
    Scope,
    reset_request_context,
    set_request_context,
)

if TYPE_CHECKING:
    from fastmcp.server.middleware import CallNext, MiddlewareContext
    from fastmcp.tools.tool import ToolResult
    from mcp import types as mt

    from .oauth import JWTIssuer

log = structlog.get_logger(__name__)


_HEADER_AUTHORIZATION = "authorization"
_HEADER_SCOPE = "x-istefox-scope"
_HEADER_PRINCIPAL = "x-istefox-principal"
_BEARER_PREFIX = "bearer "


def _parse_scope_csv(raw: str | None) -> frozenset[Scope]:
    """Parse a CSV scope header into a frozenset.

    Unknown scope strings are dropped (logged at DEBUG). Empty/None
    input returns the empty set — the safest default for write tools.
    """
    if not raw:
        return frozenset()
    out: set[Scope] = set()
    for tok in raw.split(","):
        s = tok.strip()
        if not s:
            continue
        try:
            out.add(Scope(s))
        except ValueError:
            log.debug("scope_header_unknown_value", value=s)
    return frozenset(out)


def _scopes_from_strings(values: frozenset[str]) -> frozenset[Scope]:
    """Filter raw strings down to the ones matching our Scope enum."""
    out: set[Scope] = set()
    for v in values:
        try:
            out.add(Scope(v))
        except ValueError:
            log.debug("token_scope_unknown_value", value=v)
    return frozenset(out)


def _resolve_http_context(jwt_issuer: JWTIssuer | None) -> RequestContext | None:
    """If we're inside an HTTP request, build the RequestContext.

    Returns ``None`` if FastMCP can't surface an HTTP request (stdio).
    """
    try:
        # Lazy import: get_http_request raises in stdio so we don't
        # want the import path to fail there either.
        from fastmcp.server.dependencies import get_http_request

        req = get_http_request()
    except Exception:
        return None

    headers = req.headers if hasattr(req, "headers") else {}

    # 1) Bearer token (production path). Requires the JWT issuer to
    # be wired (for stdio-only deployments it can be None — but then
    # we never reach this code path anyway).
    auth_header = headers.get(_HEADER_AUTHORIZATION) or ""
    if jwt_issuer is not None and auth_header.lower().startswith(_BEARER_PREFIX):
        token = auth_header[len(_BEARER_PREFIX) :].strip()
        try:
            claims = jwt_issuer.verify(token)
        except Exception as e:
            log.warning("bearer_token_invalid", error=type(e).__name__)
            return RequestContext(principal_id="http-anon", granted_scopes=frozenset())
        return RequestContext(
            principal_id=claims.principal_id,
            granted_scopes=_scopes_from_strings(claims.scopes),
        )

    # 2) Testing fallback header (X-Istefox-Scope).
    granted = _parse_scope_csv(headers.get(_HEADER_SCOPE))
    principal = headers.get(_HEADER_PRINCIPAL) or "http-anon"
    return RequestContext(principal_id=principal, granted_scopes=granted)


class ScopeMiddleware(Middleware):
    """Populate the per-request scope context before tools run.

    On stdio this is a no-op-equivalent (grants all scopes); on HTTP
    it reads the bearer token (production) or X-Istefox-Scope header
    (testing). The contextvar is reset after the tool returns to keep
    tasks isolated.
    """

    def __init__(self, jwt_issuer: JWTIssuer | None = None) -> None:
        self.jwt_issuer = jwt_issuer

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        ctx = _resolve_http_context(self.jwt_issuer)
        if ctx is None:
            ctx = RequestContext(
                principal_id="local-stdio",
                granted_scopes=ALL_SCOPES,
            )
        token = set_request_context(ctx)
        try:
            return await call_next(context)
        finally:
            reset_request_context(token)
