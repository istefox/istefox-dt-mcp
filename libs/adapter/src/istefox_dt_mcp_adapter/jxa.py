"""JXA bridge implementation.

Spawns `osascript -l JavaScript` subprocesses to talk to DEVONthink 4.
Concurrency bounded by a semaphore; results memoized in SQLiteCache.

Scripts live next to this file in `scripts/*.js` and receive parameters
as positional argv. Each script must:
- Return a single JSON string on stdout
- On error, return `{"error": "<ErrorCode>", "message": "..."}`
- Never write to stderr unless fatal
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
from istefox_dt_mcp_schemas.common import (
    ClassifySuggestion,
    Database,
    HealthStatus,
    MoveResult,
    Record,
    RelatedResult,
    SearchResult,
    TagResult,
    WriteOutcome,
)

from .contract import DEVONthinkAdapter
from .errors import (
    AdapterError,
    AutomationPermissionError,
    DatabaseNotFoundError,
    DTNotRunningError,
    DTVersionIncompatibleError,
    ErrorCode,
    JXAError,
    JXAParseError,
    JXATimeoutError,
    RecordNotFoundError,
)

if TYPE_CHECKING:
    from uuid import UUID

    from .cache import SQLiteCache

SCRIPTS_DIR = Path(__file__).parent / "scripts"
MIN_DT_VERSION = (4, 0, 0)

log = structlog.get_logger(__name__)


def _version_tuple(s: str) -> tuple[int, ...]:
    return tuple(int(p) for p in s.split(".") if p.isdigit())


def _version_gte(detected: str, required: tuple[int, ...]) -> bool:
    return _version_tuple(detected) >= required


def _detect_caller_app() -> str:
    """Best-effort detection of the GUI app that ultimately spawned us.

    Walks the parent process chain looking for a `.app` bundle (Warp,
    iTerm, Terminal, Claude, ...). Used only to enrich the recovery
    hint shown to the user when macOS denies Apple Events.
    """
    import os
    import subprocess

    pid = os.getppid()
    for _ in range(12):
        try:
            out = subprocess.check_output(
                ["ps", "-p", str(pid), "-o", "ppid=,comm="],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except subprocess.CalledProcessError:
            break
        parts = out.split(maxsplit=1)
        if len(parts) != 2:
            break
        ppid_s, comm = parts
        if ".app/" in comm:
            name = comm.split(".app/")[0].rsplit("/", 1)[-1]
            return name
        if ppid_s in {"0", "1"}:
            break
        pid = int(ppid_s)
    return ""


class JXAAdapter(DEVONthinkAdapter):
    """Talks to DEVONthink via osascript JXA subprocess pool."""

    def __init__(
        self,
        *,
        pool_size: int = 4,
        timeout_s: float = 5.0,
        max_retries: int = 3,
        cache: SQLiteCache | None = None,
    ) -> None:
        self._semaphore = asyncio.Semaphore(pool_size)
        self._timeout_s = timeout_s
        self._max_retries = max_retries
        self._cache = cache
        self._version_validated = False

    async def health_check(self) -> HealthStatus:
        try:
            running = await self._jxa_inline(
                "JSON.stringify(Application('DEVONthink').running())"
            )
            dt_running = bool(running)
        except AdapterError:
            return HealthStatus(
                dt_running=False,
                dt_version=None,
                bridge_ready=False,
                cache_ready=self._cache is not None,
                sidecar_ready=False,
            )

        version: str | None = None
        if dt_running:
            try:
                version = await self._jxa_inline(
                    "JSON.stringify(Application('DEVONthink').version())"
                )
            except AdapterError as e:
                log.warning("dt_version_probe_failed", error=str(e))

        if version and not _version_gte(version, MIN_DT_VERSION):
            raise DTVersionIncompatibleError(
                detected=version, required=".".join(map(str, MIN_DT_VERSION))
            )

        return HealthStatus(
            dt_running=dt_running,
            dt_version=version,
            bridge_ready=dt_running,
            cache_ready=self._cache is not None,
            sidecar_ready=False,
        )

    async def list_databases(self) -> list[Database]:
        cache_key = "list_databases"
        if self._cache and (cached := self._cache.get(cache_key)):
            return [Database.model_validate(d) for d in cached]

        raw = await self._run_script("list_databases.js")
        databases = [Database.model_validate(d) for d in raw]

        if self._cache:
            self._cache.set(
                cache_key,
                [d.model_dump(mode="json") for d in databases],
                ttl_s=300.0,
            )
        return databases

    async def get_record(self, uuid: str) -> Record:
        raw = await self._run_script("get_record.js", uuid)
        if (
            isinstance(raw, dict)
            and raw.get("error") == ErrorCode.RECORD_NOT_FOUND.value
        ):
            raise RecordNotFoundError(uuid)
        return Record.model_validate(raw)

    async def enumerate_records(
        self,
        database_name: str,
        *,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[list[dict[str, str]], int]:
        raw = await self._run_script(
            "enumerate_db.js",
            database_name,
            str(limit),
            str(offset),
        )
        if (
            isinstance(raw, dict)
            and raw.get("error") == ErrorCode.DATABASE_NOT_FOUND.value
        ):
            raise DatabaseNotFoundError(database_name)
        if not isinstance(raw, dict):
            return [], 0
        records = raw.get("records") or []
        total = int(raw.get("total_seen", 0))
        return list(records), total

    async def get_record_text(self, uuid: str, *, max_chars: int = 2000) -> str:
        cache_key = f"record_text:{uuid}:max={max_chars}"
        if self._cache and (cached := self._cache.get(cache_key)):
            return str(cached)

        raw = await self._run_script("get_record_text.js", uuid, str(max_chars))
        if (
            isinstance(raw, dict)
            and raw.get("error") == ErrorCode.RECORD_NOT_FOUND.value
        ):
            raise RecordNotFoundError(uuid)

        text = str(raw.get("text", "")) if isinstance(raw, dict) else ""
        if self._cache:
            self._cache.set(cache_key, text, ttl_s=300.0)
        return text

    async def search(
        self,
        query: str,
        *,
        databases: list[str] | None = None,
        max_results: int = 10,
        kinds: list[str] | None = None,
    ) -> list[SearchResult]:
        args = [query, str(max_results)]
        args.append(json.dumps(databases or []))
        args.append(json.dumps(kinds or []))
        raw = await self._run_script("search_bm25.js", *args)
        return [SearchResult.model_validate(r) for r in raw]

    async def find_related(
        self,
        uuid: str,
        *,
        k: int = 10,
    ) -> list[RelatedResult]:
        cache_key = f"find_related:{uuid}:k={k}"
        if self._cache and (cached := self._cache.get(cache_key)):
            return [RelatedResult.model_validate(r) for r in cached]

        raw = await self._run_script("find_related.js", uuid, str(k))
        if (
            isinstance(raw, dict)
            and raw.get("error") == ErrorCode.RECORD_NOT_FOUND.value
        ):
            raise RecordNotFoundError(uuid)
        results = [RelatedResult.model_validate(r) for r in raw]

        if self._cache:
            self._cache.set(
                cache_key,
                [r.model_dump(mode="json") for r in results],
                ttl_s=300.0,
            )
        return results

    async def classify_record(
        self,
        uuid: str,
        *,
        top_n: int = 3,
    ) -> list[ClassifySuggestion]:
        raw = await self._run_script("classify.js", uuid, str(top_n))
        if (
            isinstance(raw, dict)
            and raw.get("error") == ErrorCode.RECORD_NOT_FOUND.value
        ):
            raise RecordNotFoundError(uuid)
        if not isinstance(raw, list):
            return []
        return [ClassifySuggestion.model_validate(s) for s in raw]

    async def apply_tag(
        self,
        uuid: str,
        tag: str,
        *,
        dry_run: bool = True,
    ) -> TagResult:
        record = await self.get_record(uuid)
        tags_before = list(record.tags)
        if tag in tags_before:
            return TagResult(
                uuid=uuid,
                outcome=WriteOutcome.NOOP,
                tags_before=tags_before,
                tags_after=tags_before,
            )
        tags_after = [*tags_before, tag]
        if dry_run:
            return TagResult(
                uuid=uuid,
                outcome=WriteOutcome.PREVIEWED,
                tags_before=tags_before,
                tags_after=tags_after,
            )
        await self._run_script("apply_tag.js", uuid, tag)
        if self._cache:
            self._cache.invalidate_prefix(f"record:{uuid}")
        return TagResult(
            uuid=uuid,
            outcome=WriteOutcome.APPLIED,
            tags_before=tags_before,
            tags_after=tags_after,
        )

    async def remove_tag(
        self,
        uuid: str,
        tag: str,
        *,
        dry_run: bool = True,
    ) -> TagResult:
        record = await self.get_record(uuid)
        tags_before = list(record.tags)
        if tag not in tags_before:
            return TagResult(
                uuid=uuid,
                outcome=WriteOutcome.NOOP,
                tags_before=tags_before,
                tags_after=tags_before,
            )
        tags_after = [t for t in tags_before if t != tag]
        if dry_run:
            return TagResult(
                uuid=uuid,
                outcome=WriteOutcome.PREVIEWED,
                tags_before=tags_before,
                tags_after=tags_after,
            )
        await self._run_script("remove_tag.js", uuid, tag)
        if self._cache:
            self._cache.invalidate_prefix(f"record:{uuid}")
        return TagResult(
            uuid=uuid,
            outcome=WriteOutcome.APPLIED,
            tags_before=tags_before,
            tags_after=tags_after,
        )

    async def move_record(
        self,
        uuid: str,
        dest_group_path: str,
        *,
        dry_run: bool = True,
    ) -> MoveResult:
        record = await self.get_record(uuid)
        location_before = record.location
        if dry_run:
            return MoveResult(
                uuid=uuid,
                outcome=WriteOutcome.PREVIEWED,
                location_before=location_before,
                location_after=dest_group_path,
            )
        raw = await self._run_script("move_record.js", uuid, dest_group_path)
        if (
            isinstance(raw, dict)
            and raw.get("error") == ErrorCode.DATABASE_NOT_FOUND.value
        ):
            raise DatabaseNotFoundError(dest_group_path)
        location_after: str = dest_group_path
        if isinstance(raw, dict):
            value = raw.get("location")
            if isinstance(value, str):
                location_after = value
        if self._cache:
            self._cache.invalidate_prefix(f"record:{uuid}")
        return MoveResult(
            uuid=uuid,
            outcome=WriteOutcome.APPLIED,
            location_before=location_before,
            location_after=location_after,
        )

    async def _run_script(
        self,
        script_name: str,
        *args: str,
        audit_id: UUID | None = None,
    ) -> Any:
        script_path = SCRIPTS_DIR / script_name
        if not script_path.exists():
            raise JXAError(
                f"Script not found: {script_name}",
                audit_id=audit_id,
            )

        last_exc: AdapterError | None = None
        for attempt in range(self._max_retries):
            try:
                return await self._exec_osascript(
                    str(script_path), list(args), audit_id=audit_id
                )
            except (JXATimeoutError, JXAError) as e:
                last_exc = e
                backoff = 0.1 * (2**attempt)
                log.warning(
                    "jxa_retry",
                    script=script_name,
                    attempt=attempt + 1,
                    backoff_s=backoff,
                    error=str(e),
                    stderr=getattr(e, "stderr", "")[:500],
                )
                await asyncio.sleep(backoff)
        assert last_exc is not None
        raise last_exc

    async def _jxa_inline(self, code: str) -> Any:
        """Run a one-line JXA expression. Returns parsed JSON."""
        return await self._exec_osascript(None, [], inline_code=code)

    async def _exec_osascript(
        self,
        script_path: str | None,
        args: list[str],
        *,
        inline_code: str | None = None,
        audit_id: UUID | None = None,
    ) -> Any:
        cmd = ["osascript", "-l", "JavaScript"]
        if inline_code is not None:
            cmd += ["-e", inline_code]
        else:
            assert script_path is not None
            cmd.append(script_path)
            cmd.extend(args)

        async with self._semaphore:
            t0 = time.monotonic()
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=self._timeout_s
                )
            except TimeoutError as e:
                proc.kill()
                raise JXATimeoutError(self._timeout_s, audit_id=audit_id) from e

        duration_ms = (time.monotonic() - t0) * 1000
        stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
        stdout = stdout_bytes.decode("utf-8", errors="replace").strip()

        log.debug(
            "jxa_exec",
            script=script_path,
            inline=inline_code is not None,
            duration_ms=round(duration_ms, 1),
            returncode=proc.returncode,
        )

        if proc.returncode != 0:
            if "Application isn't running" in stderr:
                raise DTNotRunningError(audit_id=audit_id)
            if "(-1743)" in stderr or "Not authorized" in stderr:
                raise AutomationPermissionError(
                    caller_hint=_detect_caller_app(), audit_id=audit_id
                )
            raise JXAError(
                f"osascript exit {proc.returncode}",
                stderr=stderr,
                audit_id=audit_id,
            )

        if not stdout:
            return None
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as e:
            raise JXAParseError(stdout, audit_id=audit_id) from e
