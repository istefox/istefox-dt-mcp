"""OAuth scope model — public types + contextvar plumbing.

Implements the decision in ADR-006: 3 scope (`dt:read`, `dt:write`,
`dt:admin`); database-scoping is handled separately (phase 3,
ConsentStore). Tools declare their required scope as a parameter to
``safe_call``; the request middleware (``auth.middleware``) populates
the ``RequestContext`` contextvar before each tool call. If the
contextvar is unset (e.g. a tool is invoked outside the request path
in tests), helpers default to "all scopes granted" so unit tests don't
need to set it up.

Why no decorator pattern: FastMCP's ``@mcp.tool()`` decoration order
makes a ``@requires_scope`` decorator awkward (errors raised inside it
become MCP protocol errors, not envelopes). Integrating the check in
``safe_call`` keeps scope errors in the structured envelope shape
every other failure already uses.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from enum import StrEnum

# ---------------------------------------------------------------------------
# Scope enum (per ADR-006).
# ---------------------------------------------------------------------------


class Scope(StrEnum):
    """OAuth scope. Three values; database-scoping handled separately."""

    READ = "dt:read"
    """Search, get, list, summarize, ask_database, find_related, list_databases."""

    WRITE = "dt:write"
    """file_document, bulk_apply (incl. delete via trash, rename, move, tag)."""

    ADMIN = "dt:admin"
    """create_smart_rule, modify database settings, server configuration."""


# Convenience: every scope (used as the stdio default).
ALL_SCOPES: frozenset[Scope] = frozenset(Scope)


# ---------------------------------------------------------------------------
# Request context.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RequestContext:
    """Per-request authorization metadata, set by the middleware.

    ``principal_id`` is opaque server-side; for stdio it is
    ``"local-stdio"``, for HTTP phase-2 stub it is the value of the
    ``X-Istefox-Principal`` header (defaults to ``"http-anon"``); for
    HTTP phase-4 it will be the ``sub`` claim of the validated JWT.

    ``granted_scopes`` is a set of ``Scope`` values the principal has
    proved possession of for the current request.
    """

    principal_id: str
    granted_scopes: frozenset[Scope] = field(default_factory=frozenset)


# ContextVar default is None: an unset context means "no request in
# flight" which the helpers treat as a permissive local invocation
# (e.g. unit tests calling tool functions directly).
_request_context: ContextVar[RequestContext | None] = ContextVar(
    "istefox_request_context", default=None
)


def current_context() -> RequestContext | None:
    """Return the current request context, or ``None`` if unset."""
    return _request_context.get()


def current_scopes() -> frozenset[Scope]:
    """Return granted scopes for the current request.

    When no context is bound (unit tests, scripts), defaults to
    ``ALL_SCOPES`` so callers don't need to set up auth plumbing.
    """
    ctx = _request_context.get()
    if ctx is None:
        return ALL_SCOPES
    return ctx.granted_scopes


def set_request_context(
    ctx: RequestContext | None,
) -> Token[RequestContext | None]:
    """Bind the request context for the current task. Returns the token.

    Use the returned token with ``reset_request_context`` to restore the
    previous value (mandatory for nested calls / middleware order).
    """
    return _request_context.set(ctx)


def reset_request_context(token: Token[RequestContext | None]) -> None:
    """Restore the previous request context. Pair with ``set_request_context``."""
    _request_context.reset(token)


# ---------------------------------------------------------------------------
# Errors.
# ---------------------------------------------------------------------------


class InsufficientScopeError(Exception):
    """Raised when a tool requires a scope the principal does not hold.

    Carried up by ``safe_call`` and turned into an envelope with
    ``error_code=OAUTH_INSUFFICIENT_SCOPE``.
    """

    def __init__(
        self,
        *,
        required: Scope,
        granted: frozenset[Scope],
        principal_id: str | None = None,
    ) -> None:
        self.required = required
        self.granted = granted
        self.principal_id = principal_id
        super().__init__(
            f"insufficient scope: required={required.value}, "
            f"granted={sorted(s.value for s in granted)}"
        )


def has_scope(scope: Scope) -> bool:
    """Pure helper: is the given scope granted to the current request?"""
    return scope in current_scopes()
