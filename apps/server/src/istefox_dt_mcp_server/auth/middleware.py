"""FastMCP middleware that populates the per-request scope context.

Two transport modes coexist:

- **stdio**: there's no HTTP request. Middleware grants ``ALL_SCOPES``
  to a synthetic ``local-stdio`` principal. Default behavior is
  unchanged for Claude Desktop users.
- **HTTP (phase 2 stub)**: reads ``X-Istefox-Scope`` (CSV of scope
  values, e.g. ``dt:read,dt:write``) and ``X-Istefox-Principal`` from
  the HTTP request. Missing header → empty scope set, so write tools
  reject. This is a *testing-only* mechanism. Phase 4 swaps it with
  OAuth bearer-token validation via authlib.

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

log = structlog.get_logger(__name__)


_HEADER_SCOPE = "x-istefox-scope"
_HEADER_PRINCIPAL = "x-istefox-principal"


def _parse_scopes(raw: str | None) -> frozenset[Scope]:
    """Parse a comma-separated scope header into a frozenset.

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


def _resolve_http_context() -> RequestContext | None:
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
    granted = _parse_scopes(headers.get(_HEADER_SCOPE))
    principal = headers.get(_HEADER_PRINCIPAL) or "http-anon"
    return RequestContext(principal_id=principal, granted_scopes=granted)


class ScopeMiddleware(Middleware):
    """Populate the per-request scope context before tools run.

    On stdio this is a no-op-equivalent (grants all scopes); on HTTP
    it reads the scope header. The contextvar is reset after the
    tool returns to keep tasks isolated.
    """

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        ctx = _resolve_http_context()
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
