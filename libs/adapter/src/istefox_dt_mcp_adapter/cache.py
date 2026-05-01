"""SQLite-backed cache with TTL.

Used by `JXAAdapter` to memoize read-heavy calls (list_databases,
get_record, search). WAL mode for concurrent readers.

Categories with different TTLs are managed by the caller via
distinct cache key prefixes — the cache itself is dumb.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from threading import Lock
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    key         TEXT PRIMARY KEY,
    value_json  TEXT NOT NULL,
    expires_at  REAL NOT NULL
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_expires ON cache(expires_at);
"""


class SQLiteCache:
    """Thread-safe SQLite cache with per-entry TTL.

    Not async: the caller (typically inside an async semaphore-bounded
    region) accepts the small blocking overhead. Could be wrapped in
    `asyncio.to_thread` if profiling identifies it as a hotspot.
    """

    def __init__(self, path: Path, default_ttl_s: float = 60.0) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._default_ttl_s = default_ttl_s
        self._lock = Lock()
        self._conn = sqlite3.connect(
            self._path,
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)

    def get(self, key: str) -> Any | None:
        """Return cached value or None if missing/expired."""
        with self._lock:
            row = self._conn.execute(
                "SELECT value_json, expires_at FROM cache WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        value_json, expires_at = row
        if expires_at < time.time():
            self.invalidate(key)
            return None
        return json.loads(value_json)

    def set(self, key: str, value: Any, ttl_s: float | None = None) -> None:
        """Store value. ttl_s overrides default."""
        ttl = ttl_s if ttl_s is not None else self._default_ttl_s
        expires_at = time.time() + ttl
        payload = json.dumps(value, default=str)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO cache(key, value_json, expires_at) VALUES(?,?,?)",
                (key, payload, expires_at),
            )

    def invalidate(self, key: str) -> None:
        """Remove a specific key."""
        with self._lock:
            self._conn.execute("DELETE FROM cache WHERE key = ?", (key,))

    def invalidate_prefix(self, prefix: str) -> int:
        """Remove all keys starting with prefix. Returns deleted count."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM cache WHERE key LIKE ?",
                (f"{prefix}%",),
            )
            return cur.rowcount

    def purge_expired(self) -> int:
        """Remove all expired entries. Returns deleted count."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM cache WHERE expires_at < ?",
                (time.time(),),
            )
            return cur.rowcount

    def close(self) -> None:
        with self._lock:
            self._conn.close()
