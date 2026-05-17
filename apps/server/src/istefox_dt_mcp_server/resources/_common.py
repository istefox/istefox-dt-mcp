"""Common helpers for MCP resources.

Resources differ from tools: they return raw content (a JSON string
here), not an `Envelope`. On failure the MCP protocol expects the read
to *raise* (FastMCP turns it into a protocol error), not to return a
`success=false` body. Hence `safe_resource` mirrors `safe_call`'s
building blocks (scope gate, audit, error translation) but raises
instead of producing an envelope.

`bound_json` enforces the CLAUDE.md §2.2 size bound: a hard ceiling on
the serialized payload, with text-field truncation as defense in depth.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from istefox_dt_mcp_adapter.errors import AdapterError

from ..audit import timer
from ..auth.consent import ReconsentRequiredError
from ..auth.scope import (
    InsufficientScopeError,
    Scope,
    current_context,
    current_scopes,
)
from ..tools._common import OAUTH_INSUFFICIENT_SCOPE, RECONSENT_REQUIRED

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ..deps import Deps

# ~17K tokens at a conservative 3.5 chars/token — well under the 25K
# Claude Code resource bound, leaving headroom for token-dense text.
RESOURCE_MAX_CHARS = 60_000

# Absolute ceiling on the serialized JSON payload (envelope + text).
RESOURCE_JSON_BUDGET_CHARS = 80_000

# Defensive cap on the tag list of a record metadata resource.
MAX_TAGS = 100


def bound_json(payload: dict[str, Any]) -> str:
    """Serialize `payload` deterministically and enforce the size bound.

    Deterministic: `sort_keys=True`, `default=str`. If the payload
    exceeds the budget (only plausible for the text resource), truncate
    its `text` field, mark `truncated`, and re-serialize. A final hard
    slice guarantees the ceiling even in pathological cases.
    """
    s = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    if len(s) <= RESOURCE_JSON_BUDGET_CHARS:
        return s
    if isinstance(payload.get("text"), str):
        overflow = len(s) - RESOURCE_JSON_BUDGET_CHARS
        keep = max(0, len(payload["text"]) - overflow - 64)
        payload = {
            **payload,
            "text": payload["text"][:keep],
            "truncated": True,
            "returned_chars": keep,
        }
        s = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return s[:RESOURCE_JSON_BUDGET_CHARS]


async def safe_resource(
    *,
    uri: str,
    deps: Deps,
    operation: Callable[[], Awaitable[dict[str, Any]]],
) -> str:
    """Run a resource builder behind the scope/consent/audit gate.

    `operation` returns the payload dict; it may raise
    `ReconsentRequiredError` (consent denied) or `AdapterError`. This
    helper enforces `Scope.READ`, audits every outcome (success or
    denial) with `tool_name="resource:<uri>"`, and *raises* on failure
    so FastMCP surfaces an MCP protocol error.
    """
    ctx = current_context()
    principal = ctx.principal_id if ctx is not None else "local"

    if Scope.READ not in current_scopes():
        deps.audit.append(
            tool_name=f"resource:{uri}",
            input_data={"uri": uri},
            output_data=None,
            duration_ms=0.0,
            principal=principal,
            error_code=OAUTH_INSUFFICIENT_SCOPE,
        )
        raise InsufficientScopeError(
            required=Scope.READ,
            granted=current_scopes(),
            principal_id=ctx.principal_id if ctx is not None else None,
        )

    with timer() as t:
        try:
            payload = await operation()
        except ReconsentRequiredError:
            deps.audit.append(
                tool_name=f"resource:{uri}",
                input_data={"uri": uri},
                output_data=None,
                duration_ms=t.duration_ms,
                principal=principal,
                error_code=RECONSENT_REQUIRED,
            )
            raise
        except AdapterError as e:
            deps.audit.append(
                tool_name=f"resource:{uri}",
                input_data={"uri": uri},
                output_data=None,
                duration_ms=t.duration_ms,
                principal=principal,
                error_code=e.code.value,
            )
            raise

    body = bound_json(payload)
    deps.audit.append(
        tool_name=f"resource:{uri}",
        input_data={"uri": uri},
        output_data={"bytes": len(body)},
        duration_ms=t.duration_ms,
        principal=principal,
    )
    return body
