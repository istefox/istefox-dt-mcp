"""Common helpers shared by tool implementations.

The `safe_call` helper wraps adapter calls with:
- duration measurement
- structured error → italian translation
- audit log entry (always, even on failure)
- structured logging with bound `audit_id` + `tool` context
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

import structlog
from istefox_dt_mcp_adapter.errors import AdapterError
from istefox_dt_mcp_schemas.common import Envelope

from ..audit import timer

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ..deps import Deps


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
                return output_factory(
                    success=False,
                    data=None,
                    audit_id=audit_id,
                    error_code=e.code.value,
                    error_message=deps.translator.message_it(e.code),
                    recovery_hint=deps.translator.recovery_hint_it(e.code),
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
