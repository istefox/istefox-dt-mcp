"""ConsentStore — per-principal database authorization (0.4.0 phase 3).

Implements the database-scoping side of ADR-006: granted scopes are in
the OAuth token, but *which databases* a principal can access is
persisted server-side here. Tokens stay O(1) regardless of the number
of databases; new databases are detected naturally and trigger
``RECONSENT_REQUIRED`` so the user must explicitly opt in.

Storage shape (single SQLite file, WAL + synchronous=FULL):

    CREATE TABLE consent (
        principal_id   TEXT NOT NULL,
        database_uuid  TEXT NOT NULL,
        granted_at     INTEGER NOT NULL,  -- unix seconds
        PRIMARY KEY (principal_id, database_uuid)
    )

The principal ``"local-stdio"`` is treated as fully authorized for
every database (single-user, local-trust scenario): callers can skip
the check entirely for that principal. HTTP principals are checked
strictly.

Phase 3 wires:
- ``filter_visible`` into ``list_databases`` (so unauthorized DBs are
  invisible).
- A ``check_or_raise`` call into write tools' first ``get_record``
  step (the existing ``get_record`` returns ``database_uuid`` from
  0.4.0 onward, so this costs zero extra JXA round-trips).
"""

from __future__ import annotations

import sqlite3
import time
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from istefox_dt_mcp_schemas.common import Database

log = structlog.get_logger(__name__)


# Special principal id used by the stdio transport — bypasses all
# consent checks (single-user local trust).
STDIO_PRINCIPAL = "local-stdio"


class ReconsentRequiredError(Exception):
    """Principal has not authorized the target database.

    Caught by ``safe_call`` and turned into an envelope with
    ``error_code=RECONSENT_REQUIRED``.
    """

    def __init__(
        self,
        *,
        principal_id: str,
        database_uuid: str,
        database_name: str | None = None,
    ) -> None:
        self.principal_id = principal_id
        self.database_uuid = database_uuid
        self.database_name = database_name
        super().__init__(
            f"reconsent required: principal={principal_id!r} has not "
            f"authorized database {database_uuid!r}"
            + (f" ({database_name!r})" if database_name else "")
        )


class ConsentStore:
    """Persistent per-database authorization, decoupled from OAuth tokens.

    Thread-safety: SQLite connections are per-call (cheap on WAL); we
    don't pin a single connection. ``check_same_thread=False`` is set
    so callers from different asyncio tasks can use the same instance.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ---------------------------------------------------------------
    # Schema management
    # ---------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            isolation_level=None,  # autocommit; we use explicit BEGINs as needed
        )
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = FULL")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS consent (
                    principal_id   TEXT NOT NULL,
                    database_uuid  TEXT NOT NULL,
                    granted_at     INTEGER NOT NULL,
                    PRIMARY KEY (principal_id, database_uuid)
                )
                """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_consent_principal
                    ON consent(principal_id)
                """)

    # ---------------------------------------------------------------
    # Mutations
    # ---------------------------------------------------------------

    def authorize(
        self,
        principal_id: str,
        database_uuids: str | Iterable[str],
    ) -> int:
        """Grant access to one or more databases for ``principal_id``.

        Idempotent: re-authorizing an already-granted database refreshes
        ``granted_at``. Returns the number of rows touched (insert or
        update).
        """
        if isinstance(database_uuids, str):
            uuids: list[str] = [database_uuids]
        else:
            uuids = [u for u in database_uuids if u]
        if not uuids:
            return 0

        now = int(time.time())
        with self._connect() as conn:
            cur = conn.executemany(
                """
                INSERT INTO consent (principal_id, database_uuid, granted_at)
                VALUES (?, ?, ?)
                ON CONFLICT(principal_id, database_uuid)
                DO UPDATE SET granted_at = excluded.granted_at
                """,
                [(principal_id, u, now) for u in uuids],
            )
            count = cur.rowcount
        log.info(
            "consent_authorize",
            principal=principal_id,
            count=count,
            db_uuids=uuids[:5],  # cap to avoid huge logs
        )
        return count

    def revoke(self, principal_id: str, database_uuid: str) -> bool:
        """Revoke access. Returns True iff a row was actually deleted."""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM consent WHERE principal_id = ? AND database_uuid = ?",
                (principal_id, database_uuid),
            )
            deleted = cur.rowcount > 0
        if deleted:
            log.info(
                "consent_revoke",
                principal=principal_id,
                database_uuid=database_uuid,
            )
        return deleted

    def revoke_all(self, principal_id: str) -> int:
        """Revoke every grant for a principal. Returns row count."""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM consent WHERE principal_id = ?",
                (principal_id,),
            )
            count = cur.rowcount
        log.info("consent_revoke_all", principal=principal_id, count=count)
        return count

    # ---------------------------------------------------------------
    # Queries
    # ---------------------------------------------------------------

    def authorized_databases(self, principal_id: str) -> set[str]:
        """Return the set of database UUIDs the principal has authorized."""
        if principal_id == STDIO_PRINCIPAL:
            # Stdio short-circuits — caller should generally not even
            # call this for stdio, but if they do we must not lie:
            # return an empty set since we don't track stdio explicitly.
            # The check helpers below understand the stdio bypass and
            # never consult this method for stdio.
            return set()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT database_uuid FROM consent WHERE principal_id = ?",
                (principal_id,),
            ).fetchall()
        return {r[0] for r in rows}

    def is_authorized(self, principal_id: str, database_uuid: str) -> bool:
        """Cheap single-DB lookup. Stdio is always authorized."""
        if principal_id == STDIO_PRINCIPAL:
            return True
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM consent
                WHERE principal_id = ? AND database_uuid = ?
                LIMIT 1
                """,
                (principal_id, database_uuid),
            ).fetchone()
        return row is not None

    def filter_visible(
        self,
        principal_id: str,
        databases: Iterable[Database],
    ) -> list[Database]:
        """Filter a list of databases down to those the principal owns.

        Stdio sees everything (single-user trust). HTTP principals see
        only what they've authorized.
        """
        all_dbs = list(databases)
        if principal_id == STDIO_PRINCIPAL:
            return all_dbs
        granted = self.authorized_databases(principal_id)
        return [db for db in all_dbs if db.uuid in granted]

    def check_or_raise(
        self,
        principal_id: str,
        database_uuid: str,
        *,
        database_name: str | None = None,
    ) -> None:
        """Raise ReconsentRequiredError if the principal isn't authorized.

        No-op for stdio. The optional ``database_name`` is surfaced in
        the error for nicer recovery messaging.
        """
        if self.is_authorized(principal_id, database_uuid):
            return
        raise ReconsentRequiredError(
            principal_id=principal_id,
            database_uuid=database_uuid,
            database_name=database_name,
        )
