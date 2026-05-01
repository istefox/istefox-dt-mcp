"""Structured error schema and taxonomy.

`ErrorCode` is the single source of truth for error identifiers,
shared by the adapter (raises exceptions tagged with codes), the
server (maps codes to user-facing italian messages), and the MCP
tool output envelope.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID  # noqa: TC003 — needed by Pydantic at runtime

from pydantic import Field

from .common import StrictModel


class ErrorCode(StrEnum):
    """Tassonomic error codes. Stable contract — never rename, only add."""

    DT_NOT_RUNNING = "DT_NOT_RUNNING"
    DT_VERSION_INCOMPATIBLE = "DT_VERSION_INCOMPATIBLE"
    JXA_TIMEOUT = "JXA_TIMEOUT"
    JXA_ERROR = "JXA_ERROR"
    JXA_PARSE_ERROR = "JXA_PARSE_ERROR"
    RECORD_NOT_FOUND = "RECORD_NOT_FOUND"
    DATABASE_NOT_FOUND = "DATABASE_NOT_FOUND"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    RATE_LIMITED = "RATE_LIMITED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    INVALID_PREVIEW_TOKEN = "INVALID_PREVIEW_TOKEN"
    EXPIRED_PREVIEW_TOKEN = "EXPIRED_PREVIEW_TOKEN"
    CONSUMED_PREVIEW_TOKEN = "CONSUMED_PREVIEW_TOKEN"


class StructuredError(StrictModel):
    """Error envelope returned to the MCP client when a tool fails."""

    code: ErrorCode
    message_en: str = Field(..., description="Stable, technical, english")
    message_it: str = Field(..., description="User-facing italian message")
    recovery_hint_it: str = Field("", description="What the user can do about it")
    audit_id: UUID | None = None
