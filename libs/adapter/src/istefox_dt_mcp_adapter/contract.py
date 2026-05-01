"""Abstract bridge contract.

`DEVONthinkAdapter` is the unified interface that the service layer
talks to. The service layer never knows which concrete bridge is in
use (JXA today, x-callback-url or DT Server in the future).

All methods are async. Implementations must:
- Raise structured `AdapterError` subclasses on failure (never bare exceptions)
- Be idempotent where semantically possible
- Validate input at the boundary (no trust assumption)
- Honor the `dry_run` flag on write operations
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from istefox_dt_mcp_schemas.common import (
        Database,
        HealthStatus,
        MoveResult,
        Record,
        RelatedResult,
        SearchResult,
        TagResult,
    )


class DEVONthinkAdapter(ABC):
    """Bridge contract for talking to DEVONthink 4.

    Concrete implementations: `JXAAdapter` (v1).
    Future: `XCallbackAdapter` (v1.5), `DTServerAdapter` (v2+).
    """

    @abstractmethod
    async def health_check(self) -> HealthStatus:
        """Probe the bridge and the DEVONthink app."""

    @abstractmethod
    async def list_databases(self) -> list[Database]:
        """Enumerate all currently-open databases."""

    @abstractmethod
    async def get_record(self, uuid: str) -> Record:
        """Fetch a single record by stable UUID. Raises RecordNotFoundError."""

    @abstractmethod
    async def search(
        self,
        query: str,
        *,
        databases: list[str] | None = None,
        max_results: int = 10,
        kinds: list[str] | None = None,
    ) -> list[SearchResult]:
        """BM25 search via DEVONthink native engine."""

    @abstractmethod
    async def find_related(
        self,
        uuid: str,
        *,
        k: int = 10,
    ) -> list[RelatedResult]:
        """Find records similar to the given one (See Also / Compare)."""

    @abstractmethod
    async def apply_tag(
        self,
        uuid: str,
        tag: str,
        *,
        dry_run: bool = True,
    ) -> TagResult:
        """Add a tag to a record. Idempotent. Honors dry_run."""

    @abstractmethod
    async def move_record(
        self,
        uuid: str,
        dest_group_path: str,
        *,
        dry_run: bool = True,
    ) -> MoveResult:
        """Move a record to a destination group. Honors dry_run."""

    async def close(self) -> None:
        """Release any resources held by the adapter (subprocesses, sockets, ...)."""
        return None
