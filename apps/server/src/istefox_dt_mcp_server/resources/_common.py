"""Common helpers for MCP resources.

Resources differ from tools: they return raw content (a JSON string
here), not an `Envelope`. On failure the MCP protocol expects the read
to *raise* (FastMCP turns it into a protocol error), not to return a
`success=false` body. Hence `safe_resource` mirrors `safe_call`'s
building blocks (scope gate, audit, error translation) but raises
instead of producing an envelope.

`bound_json` enforces the CLAUDE.md §2.2 size bound: a hard ceiling on
the serialized payload, with text-field truncation as defense in depth.

Every read is audited and logged with structlog parity to `safe_call`
(`request_id`/`audit_id` contextvars + a structured event per outcome);
failures surface to the MCP client as a localized italian
`ResourceError` (FastMCP turns it into a protocol error).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import structlog
from fastmcp.exceptions import ResourceError
from istefox_dt_mcp_adapter.errors import AdapterError

from ..audit import timer
from ..auth.consent import ReconsentRequiredError
from ..auth.scope import (
    Scope,
    current_context,
    current_scopes,
)
from ..tools._common import OAUTH_INSUFFICIENT_SCOPE, RECONSENT_REQUIRED

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ..deps import Deps

log = structlog.get_logger(__name__)

# Per-field cap on the record `text` (passed to get_record_text). The
# *enforcing* ceiling on the whole resource body is
# RESOURCE_JSON_BUDGET_CHARS below — keep this comfortably under it so
# the JSON envelope + escaping never push a legitimate record past the
# backstop (escaping rarely expands prose; structured fields are tiny).
RESOURCE_MAX_CHARS = 45_000

# Hard ceiling on the FULL serialized JSON body — this is what actually
# enforces the CLAUDE.md §2.2 "≤25K token" bound. 60K chars ÷ a
# conservative 2.5 chars/token (worst case for the IT/EN/FR/DE target
# corpus: accented Latin, code, base64-ish) ≈ 24K tokens < 25K, with
# headroom. Char-based (no tokenizer dependency, per the zero-new-deps
# constraint); deliberately conservative for the project's actual
# languages. CJK would tokenize denser, but it is out of the declared
# target corpus.
RESOURCE_JSON_BUDGET_CHARS = 60_000

# Defensive cap on the tag list of a record metadata resource.
MAX_TAGS = 100


def bound_json(payload: dict[str, Any]) -> str:
    """Serialize `payload` deterministically and enforce the size bound.

    Deterministic: `sort_keys=True`, `default=str`. If the payload
    exceeds the budget (only plausible for the text resource), truncate
    its `text` field, mark `truncated`, and re-serialize. If still over
    budget (non-text payload, or pathological text), emit a small valid
    JSON error body instead of a corrupt slice.
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
        if len(s) <= RESOURCE_JSON_BUDGET_CHARS:
            return s
    # Non-text payload, or text truncation still over budget: emit a
    # small VALID JSON error body rather than a corrupt hard slice.
    return json.dumps(
        {"error": "RESOURCE_OVERSIZED", "truncated": True}, sort_keys=True
    )


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
    denial) with `tool_name="resource:<uri>"`, emits structlog events
    bound to a `request_id`/`audit_id` (parity with `safe_call`), and
    raises a localized italian `ResourceError` on failure so FastMCP
    surfaces a clean MCP protocol error.
    """
    ctx = current_context()
    principal = ctx.principal_id if ctx is not None else "local"
    request_id = str(uuid4())
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        tool=f"resource:{uri}",
    )
    try:
        log.debug("resource_read_started", uri=uri)

        if Scope.READ not in current_scopes():
            audit_id = deps.audit.append(
                tool_name=f"resource:{uri}",
                input_data={"uri": uri},
                output_data=None,
                duration_ms=0.0,
                principal=principal,
                error_code=OAUTH_INSUFFICIENT_SCOPE,
            )
            structlog.contextvars.bind_contextvars(audit_id=str(audit_id))
            log.warning(
                "resource_scope_denied",
                required_scope=Scope.READ.value,
                granted_scopes=sorted(s.value for s in current_scopes()),
                principal=principal,
            )
            raise ResourceError(
                "Accesso negato: la lettura di questa resource richiede "
                "lo scope 'dt:read'. Riesegui il consent flow concedendo "
                "'dt:read' al client."
            )

        with timer() as t:
            try:
                payload = await operation()
            except ReconsentRequiredError as e:
                audit_id = deps.audit.append(
                    tool_name=f"resource:{uri}",
                    input_data={"uri": uri},
                    output_data=None,
                    duration_ms=t.duration_ms,
                    principal=principal,
                    error_code=RECONSENT_REQUIRED,
                )
                structlog.contextvars.bind_contextvars(audit_id=str(audit_id))
                log.warning(
                    "resource_reconsent_required",
                    principal=principal,
                    database_uuid=e.database_uuid,
                    database_name=e.database_name,
                )
                raise ResourceError(
                    f"Il database {e.database_name!r} ({e.database_uuid}) "
                    f"non è autorizzato per il client corrente. Riesegui "
                    f"il consent flow e selezionalo nella lista di "
                    f"autorizzazioni."
                ) from e
            except AdapterError as e:
                audit_id = deps.audit.append(
                    tool_name=f"resource:{uri}",
                    input_data={"uri": uri},
                    output_data=None,
                    duration_ms=t.duration_ms,
                    principal=principal,
                    error_code=e.code.value,
                )
                structlog.contextvars.bind_contextvars(audit_id=str(audit_id))
                log.warning(
                    "resource_failed",
                    error_code=e.code.value,
                    duration_ms=round(t.duration_ms, 1),
                )
                recovery = e.recovery_hint or deps.translator.recovery_hint_it(e.code)
                raise ResourceError(
                    f"{deps.translator.message_it(e.code)} {recovery}"
                ) from e

        body = bound_json(payload)
        audit_id = deps.audit.append(
            tool_name=f"resource:{uri}",
            input_data={"uri": uri},
            output_data={"bytes": len(body)},
            duration_ms=t.duration_ms,
            principal=principal,
        )
        structlog.contextvars.bind_contextvars(audit_id=str(audit_id))
        log.info("resource_ok", duration_ms=round(t.duration_ms, 1))
        return body
    finally:
        structlog.contextvars.unbind_contextvars("request_id", "tool", "audit_id")
