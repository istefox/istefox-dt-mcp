"""Domain models shared across adapter, server and sidecar.

These models represent DEVONthink entities (databases, records) and
common operation results. They are the lingua franca of the bridge
contract. Tool-specific I/O models live in `tools.py`.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — needed by Pydantic at runtime
from enum import StrEnum
from typing import TypeVar
from uuid import UUID  # noqa: TC003 — needed by Pydantic at runtime

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class StrictModel(BaseModel):
    """Base model with strict config. All schemas inherit from this."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=False,
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class LooseModel(BaseModel):
    """Base for OUTPUT models parsed from external sources (JXA, RAG, etc.).

    Same defaults as StrictModel except extra='ignore' — accept fields DT or
    other adapters may add in future versions without breaking replay tests
    or downstream consumers. Input models (validating LLM/user input) keep
    StrictModel; only models that wrap data from outside our control use
    LooseModel.
    """

    model_config = ConfigDict(
        extra="ignore",
        frozen=False,
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class RecordKind(StrEnum):
    """DEVONthink record kinds. Maps to `record.kind()` JXA values."""

    PDF = "PDF"
    RTF = "rtf"
    MARKDOWN = "markdown"
    PLAINTEXT = "txt"
    WEBARCHIVE = "webarchive"
    BOOKMARK = "bookmark"
    HTML = "html"
    IMAGE = "image"
    GROUP = "group"
    SMART_GROUP = "smart group"
    UNKNOWN = "unknown"


class Database(LooseModel):
    """A DEVONthink database (top-level container)."""

    uuid: str
    name: str
    path: str
    is_open: bool
    record_count: int | None = None


class Record(LooseModel):
    """A DEVONthink record (document, group, bookmark, ...)."""

    uuid: str
    name: str
    kind: RecordKind | str
    location: str
    path: str | None = None
    reference_url: str = Field(
        ..., description="x-devonthink-item:// URL for stable cross-machine ref"
    )
    creation_date: datetime
    modification_date: datetime
    tags: list[str] = Field(default_factory=list)
    size_bytes: int | None = None
    word_count: int | None = None


class SearchResult(LooseModel):
    """One hit returned by the bridge search operation."""

    uuid: str
    name: str
    location: str
    reference_url: str
    score: float | None = None
    snippet: str | None = None


class RelatedResult(LooseModel):
    """One hit returned by find_related (See Also / Compare)."""

    uuid: str
    name: str
    similarity: float | None = None
    location: str
    reference_url: str


class WriteOutcome(StrEnum):
    """Standardized outcome for write operations."""

    APPLIED = "applied"
    PREVIEWED = "previewed"
    NOOP = "noop"
    REJECTED = "rejected"


class TagResult(LooseModel):
    """Result of an apply_tag operation."""

    uuid: str
    outcome: WriteOutcome
    tags_before: list[str]
    tags_after: list[str]


class MoveResult(LooseModel):
    """Result of a move_record operation."""

    uuid: str
    outcome: WriteOutcome
    location_before: str
    location_after: str


class HealthStatus(LooseModel):
    """Bridge health check output.

    `bridge_ready` requires BOTH process running AND data-access
    permission (AppleEvents). `dt_running` alone (process exists)
    is not sufficient — a denied AppleEvents grant lets the process
    be detected but blocks every meaningful call.
    """

    dt_running: bool
    dt_version: str | None = None
    bridge_ready: bool
    cache_ready: bool
    sidecar_ready: bool
    permission_denied: bool = False
    recovery_hint: str | None = None


class ClassifySuggestion(LooseModel):
    """One destination group suggested by DT4 native classifier."""

    location: str
    score: float | None = None
    database: str | None = None


class Envelope[T](StrictModel):
    """Standard envelope for tool outputs.

    Every tool returns an Envelope so the LLM has a uniform shape to parse.
    """

    success: bool
    data: T | None = None
    warnings: list[str] = Field(default_factory=list)
    audit_id: UUID | None = None
    error_code: str | None = None
    error_message: str | None = None
    recovery_hint: str | None = None
