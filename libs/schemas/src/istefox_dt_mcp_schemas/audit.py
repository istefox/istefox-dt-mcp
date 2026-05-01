"""Audit log entry schema.

Append-only entries persisted in `~/.local/share/istefox-dt-mcp/audit.sqlite`.
Every tool call (read or write) produces one entry. Write operations
also store `before_state` to enable selective undo.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — needed by Pydantic at runtime
from typing import Any
from uuid import UUID  # noqa: TC003 — needed by Pydantic at runtime

from pydantic import Field

from .common import StrictModel


class AuditEntry(StrictModel):
    """One append-only row of the audit log."""

    audit_id: UUID
    timestamp: datetime
    principal: str = Field(default="local", description="OAuth user or 'local'")
    tool_name: str
    input_json: dict[str, Any]
    output_hash: str = Field(..., description="SHA-256 of the JSON output")
    duration_ms: float
    before_state: dict[str, Any] | None = Field(
        default=None,
        description="State snapshot before write op, used for selective undo",
    )
    after_state: dict[str, Any] | None = Field(
        default=None,
        description=(
            "State snapshot after a successful write op. Used by undo "
            "to detect drift precisely: if the current DT state matches "
            "after_state, undo can revert safely; otherwise something "
            "external changed the record after this audit entry."
        ),
    )
    error_code: str | None = None
