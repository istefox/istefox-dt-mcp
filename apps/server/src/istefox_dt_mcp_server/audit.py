"""Append-only audit log on SQLite.

Every tool call (read or write) produces one row. Write operations
also persist `before_state` to enable selective undo.

Schema is fixed: changing it requires a new migration. The
`audit_log` table has no UPDATE/DELETE statements anywhere in code —
this is enforced by convention plus a CHECK trigger.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import UUID, uuid4

from istefox_dt_mcp_schemas.audit import AuditEntry

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    audit_id     TEXT PRIMARY KEY,
    ts           TEXT NOT NULL,
    principal    TEXT NOT NULL,
    tool_name    TEXT NOT NULL,
    input_json   TEXT NOT NULL,
    output_hash  TEXT NOT NULL,
    duration_ms  REAL NOT NULL,
    before_state TEXT,
    error_code   TEXT
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_audit_ts   ON audit_log(ts);
CREATE INDEX IF NOT EXISTS idx_audit_tool ON audit_log(tool_name);

CREATE TRIGGER IF NOT EXISTS audit_no_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only');
END;

CREATE TRIGGER IF NOT EXISTS audit_no_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only');
END;
"""


def _hash_output(output: Any) -> str:
    payload = json.dumps(output, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class AuditLog:
    """Thread-safe append-only audit log backed by SQLite."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._conn = sqlite3.connect(
            self._path,
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    def append(
        self,
        *,
        tool_name: str,
        input_data: dict[str, Any],
        output_data: Any,
        duration_ms: float,
        principal: str = "local",
        before_state: dict[str, Any] | None = None,
        error_code: str | None = None,
    ) -> UUID:
        """Persist one entry. Returns the assigned audit_id."""
        audit_id = uuid4()
        ts = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                """INSERT INTO audit_log(
                    audit_id, ts, principal, tool_name, input_json,
                    output_hash, duration_ms, before_state, error_code
                ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    str(audit_id),
                    ts,
                    principal,
                    tool_name,
                    json.dumps(input_data, default=str),
                    _hash_output(output_data),
                    duration_ms,
                    json.dumps(before_state, default=str) if before_state else None,
                    error_code,
                ),
            )
        return audit_id

    def get(self, audit_id: UUID) -> AuditEntry | None:
        with self._lock:
            row = self._conn.execute(
                """SELECT audit_id, ts, principal, tool_name, input_json,
                          output_hash, duration_ms, before_state, error_code
                   FROM audit_log WHERE audit_id = ?""",
                (str(audit_id),),
            ).fetchone()
        if not row:
            return None
        return AuditEntry(
            audit_id=UUID(row[0]),
            timestamp=datetime.fromisoformat(row[1]),
            principal=row[2],
            tool_name=row[3],
            input_json=json.loads(row[4]),
            output_hash=row[5],
            duration_ms=row[6],
            before_state=json.loads(row[7]) if row[7] else None,
            error_code=row[8],
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class _Timer:
    """Tiny context manager used by tools to measure their own duration."""

    def __init__(self) -> None:
        self.duration_ms: float = 0.0
        self._t0: float = 0.0

    def __enter__(self) -> _Timer:
        self._t0 = time.monotonic()
        return self

    def __exit__(self, *_: object) -> None:
        self.duration_ms = (time.monotonic() - self._t0) * 1000.0


def timer() -> _Timer:
    return _Timer()
