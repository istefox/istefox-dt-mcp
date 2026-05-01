"""Common helpers shared by tool implementations.

The `safe_call` helper wraps adapter calls with:
- duration measurement
- structured error → italian translation
- audit log entry (always, even on failure)
- structured logging
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from istefox_dt_mcp_adapter.errors import AdapterError

from ..audit import timer

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from istefox_dt_mcp_schemas.common import Envelope

    from ..deps import Deps


log = structlog.get_logger(__name__)


async def safe_call[T](
    *,
    tool_name: str,
    input_data: dict[str, Any],
    deps: Deps,
    operation: Callable[[], Awaitable[T]],
    output_factory: Callable[..., Envelope[T]],
) -> Envelope[T]:
    """Run `operation`, capture errors, persist audit, return envelope.

    `output_factory` is the concrete `<Tool>Output` class.
    """
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
            )
            log.warning(
                "tool_failed",
                tool=tool_name,
                error_code=e.code.value,
                duration_ms=round(t.duration_ms, 1),
                audit_id=str(audit_id),
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
    )
    log.info(
        "tool_ok",
        tool=tool_name,
        duration_ms=round(t.duration_ms, 1),
        audit_id=str(audit_id),
    )
    return output_factory(success=True, data=data, audit_id=audit_id)
