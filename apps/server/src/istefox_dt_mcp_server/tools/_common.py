"""Common helpers shared by tool implementations.

The `safe_call` helper wraps adapter calls with:
- duration measurement
- structured error → italian translation
- audit log entry (always, even on failure)
- structured logging with bound `audit_id` + `tool` context

The `validate_confirm_token` helper enforces preview-token integrity
for write tools (file_document, bulk_apply): the token must be a
known audit_id, must point to a previous dry_run of the *same* tool,
must not have expired (TTL), and must not have been consumed before.

The `validate_destination_path` helper checks that the first segment
of an absolute destination path matches an open DEVONthink database.
This is a UX accelerator: it fails fast with a clear list of valid
databases instead of waiting for the JXA bridge to return an opaque
DATABASE_NOT_FOUND.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import structlog
from istefox_dt_mcp_adapter.errors import (
    AdapterError,
    ConsumedPreviewTokenError,
    DatabaseNotFoundError,
    ExpiredPreviewTokenError,
    InvalidPreviewTokenError,
)
from istefox_dt_mcp_schemas.common import Envelope

from ..audit import timer

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ..deps import Deps


# Preview tokens expire after 5 minutes (UX-driven: enough time for
# the user to read the preview and confirm; short enough to bound
# the window where stale state could be applied).
DEFAULT_PREVIEW_TTL_S = 300

# Env override for tests / power users
_PREVIEW_TTL_ENV = "ISTEFOX_PREVIEW_TTL_S"


def preview_ttl_s() -> int:
    raw = os.environ.get(_PREVIEW_TTL_ENV)
    if not raw:
        return DEFAULT_PREVIEW_TTL_S
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_PREVIEW_TTL_S


log = structlog.get_logger(__name__)

# Keys to redact from input_data when logged. Audit log keeps the full
# payload (it's local-only, append-only, owned by the user); the
# stderr stream may end up in pipes / files / observability backends,
# so we keep it light.
_INPUT_REDACT_KEYS = frozenset({"question", "query", "snippet", "answer"})


def _summarize_input(data: dict[str, Any]) -> dict[str, Any]:
    """Return a log-safe summary of the input payload.

    Long text fields are reduced to length only; small fields pass
    through. Nested structures get a shallow summary.
    """
    summary: dict[str, Any] = {}
    for k, v in data.items():
        if (k in _INPUT_REDACT_KEYS and isinstance(v, str)) or (
            isinstance(v, str) and len(v) > 80
        ):
            summary[k] = f"<str len={len(v)}>"
        elif isinstance(v, list):
            summary[k] = f"<list len={len(v)}>"
        elif isinstance(v, dict):
            summary[k] = f"<dict keys={len(v)}>"
        else:
            summary[k] = v
    return summary


def validate_confirm_token(
    deps: Deps,
    *,
    tool_name: str,
    confirm_token: str | None,
) -> None:
    """Verify a preview_token before applying a write op.

    Raises a `*PreviewTokenError` (caught by `safe_call`) on rejection.
    On success, marks the token as consumed (one-shot enforcement).

    Rejection cases:
    - missing/malformed token → InvalidPreviewTokenError
    - token doesn't reference a previous audit entry → InvalidPreviewTokenError
    - audit entry is from a different tool → InvalidPreviewTokenError
    - audit entry was an apply, not a preview → InvalidPreviewTokenError
    - audit entry older than TTL → ExpiredPreviewTokenError
    - token already consumed → ConsumedPreviewTokenError
    """
    if not confirm_token:
        raise InvalidPreviewTokenError("missing")
    try:
        audit_id = UUID(confirm_token)
    except ValueError as e:
        raise InvalidPreviewTokenError("not a UUID") from e

    entry = deps.audit.get(audit_id)
    if entry is None:
        raise InvalidPreviewTokenError("unknown audit_id")
    if entry.tool_name != tool_name:
        raise InvalidPreviewTokenError(
            f"token belongs to {entry.tool_name}, not {tool_name}"
        )
    if entry.input_json.get("dry_run") is not True:
        raise InvalidPreviewTokenError("token does not point to a dry_run preview")

    age_s = (datetime.now(UTC) - entry.timestamp).total_seconds()
    if age_s > preview_ttl_s():
        raise ExpiredPreviewTokenError(age_s)

    # Mark consumed atomically; a second caller racing with the same
    # token loses the INSERT and we report CONSUMED back.
    if not deps.audit.mark_consumed(audit_id):
        raise ConsumedPreviewTokenError()


async def validate_destination_path(deps: Deps, path: str) -> None:
    """Verify the first segment of `path` matches an open database.

    Raises `DatabaseNotFoundError` (subclass of AdapterError, caught by
    `safe_call`) if the prefix is empty or doesn't match any currently
    open DEVONthink database.

    The recovery_hint is overridden to include the list of available
    databases — much more helpful than the generic adapter message
    when the user is debugging a `destination_hint` typo.
    """
    parts = path.lstrip("/").split("/", 1)
    first = parts[0] if parts else ""
    if not first:
        err = DatabaseNotFoundError("(empty)")
        err.recovery_hint = (
            "destination_hint deve iniziare con il nome di un database "
            "(es. '/Inbox/MyGroup'). Usa list_databases per enumerare i "
            "database aperti."
        )
        raise err
    dbs = await deps.adapter.list_databases()
    open_names = [d.name for d in dbs if d.is_open]
    if first not in open_names:
        avail = ", ".join(sorted(open_names)) or "(nessun database aperto)"
        err = DatabaseNotFoundError(first)
        err.recovery_hint = (
            f"Database '{first}' non trovato fra quelli aperti. "
            f"Database disponibili: {avail}. Il primo segmento di "
            f"destination_hint deve essere il nome esatto di un database "
            f"(case-sensitive). Esempio: '/{open_names[0] if open_names else 'Inbox'}/MyGroup'."
        )
        raise err


async def safe_call[T, OutT: Envelope[Any]](
    *,
    tool_name: str,
    input_data: dict[str, Any],
    deps: Deps,
    operation: Callable[[], Awaitable[T]],
    output_factory: Callable[..., OutT],
    before_state: dict[str, Any] | None = None,
) -> OutT:
    """Run `operation`, capture errors, persist audit, return envelope.

    Logs three events bound to the same `request_id` and `audit_id`:
    - `tool_call_started` (DEBUG): with summarized input
    - `tool_ok` or `tool_failed` (INFO/WARNING): with duration + outcome

    `output_factory` is the concrete `<Tool>Output` class.

    `before_state` is opt-in for write tools that want to record a
    snapshot for selective undo (W7+: file_document, bulk_apply).
    The audit log persists it verbatim — keep it small and JSON-safe.
    """
    request_id = str(uuid4())
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        tool=tool_name,
    )
    try:
        log.debug("tool_call_started", input_summary=_summarize_input(input_data))

        with timer() as t:
            try:
                data = await operation()
            except AdapterError as e:
                audit_id = deps.audit.append(
                    tool_name=tool_name,
                    input_data=input_data,
                    output_data=None,
                    duration_ms=t.duration_ms,
                    error_code=e.code.value,
                    before_state=before_state,
                )
                structlog.contextvars.bind_contextvars(audit_id=str(audit_id))
                log.warning(
                    "tool_failed",
                    error_code=e.code.value,
                    duration_ms=round(t.duration_ms, 1),
                )
                # Per-instance recovery_hint (richer, includes call
                # context like "available databases: X, Y") wins over
                # the static translator default. Falls back to the
                # translator when the exception didn't carry one.
                recovery = e.recovery_hint or deps.translator.recovery_hint_it(e.code)
                return output_factory(
                    success=False,
                    data=None,
                    audit_id=audit_id,
                    error_code=e.code.value,
                    error_message=deps.translator.message_it(e.code),
                    recovery_hint=recovery,
                )

        audit_id = deps.audit.append(
            tool_name=tool_name,
            input_data=input_data,
            output_data=data,
            duration_ms=t.duration_ms,
            before_state=before_state,
        )
        structlog.contextvars.bind_contextvars(audit_id=str(audit_id))
        log.info("tool_ok", duration_ms=round(t.duration_ms, 1))
        return output_factory(success=True, data=data, audit_id=audit_id)
    finally:
        structlog.contextvars.unbind_contextvars("request_id", "tool", "audit_id")
