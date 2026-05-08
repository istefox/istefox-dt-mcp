"""Unit tests for ConsentStore (0.4.0 phase 3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from istefox_dt_mcp_schemas.common import Database
from istefox_dt_mcp_server.auth.consent import (
    STDIO_PRINCIPAL,
    ConsentStore,
    ReconsentRequiredError,
)


def _db(uuid: str, name: str | None = None) -> Database:
    return Database(
        uuid=uuid,
        name=name or f"db-{uuid}",
        path=f"/path/{uuid}",
        is_open=True,
    )


def test_authorize_round_trip(tmp_path: Path) -> None:
    s = ConsentStore(tmp_path / "consent.sqlite")
    assert s.authorize("alice", "DB-001") == 1
    assert s.is_authorized("alice", "DB-001") is True
    assert s.is_authorized("alice", "DB-002") is False
    assert s.is_authorized("bob", "DB-001") is False


def test_authorize_idempotent(tmp_path: Path) -> None:
    s = ConsentStore(tmp_path / "consent.sqlite")
    s.authorize("alice", "DB-001")
    # Re-authorize should not error and should still be authorized.
    s.authorize("alice", "DB-001")
    assert s.is_authorized("alice", "DB-001") is True
    assert s.authorized_databases("alice") == {"DB-001"}


def test_authorize_many(tmp_path: Path) -> None:
    s = ConsentStore(tmp_path / "consent.sqlite")
    s.authorize("alice", ["DB-A", "DB-B", "DB-C"])
    assert s.authorized_databases("alice") == {"DB-A", "DB-B", "DB-C"}


def test_revoke(tmp_path: Path) -> None:
    s = ConsentStore(tmp_path / "consent.sqlite")
    s.authorize("alice", ["DB-A", "DB-B"])
    assert s.revoke("alice", "DB-A") is True
    assert s.revoke("alice", "DB-A") is False  # idempotent
    assert s.authorized_databases("alice") == {"DB-B"}


def test_revoke_all(tmp_path: Path) -> None:
    s = ConsentStore(tmp_path / "consent.sqlite")
    s.authorize("alice", ["DB-A", "DB-B", "DB-C"])
    assert s.revoke_all("alice") == 3
    assert s.authorized_databases("alice") == set()


def test_filter_visible_filters_unauthorized(tmp_path: Path) -> None:
    s = ConsentStore(tmp_path / "consent.sqlite")
    s.authorize("alice", "DB-A")
    all_dbs = [_db("DB-A", "Alpha"), _db("DB-B", "Beta"), _db("DB-C", "Gamma")]
    visible = s.filter_visible("alice", all_dbs)
    assert {db.uuid for db in visible} == {"DB-A"}


def test_filter_visible_empty_for_unknown_principal(tmp_path: Path) -> None:
    s = ConsentStore(tmp_path / "consent.sqlite")
    s.authorize("alice", "DB-A")
    all_dbs = [_db("DB-A"), _db("DB-B")]
    assert s.filter_visible("mallory", all_dbs) == []


def test_stdio_principal_bypass_filter(tmp_path: Path) -> None:
    """Stdio sees everything regardless of consent table contents."""
    s = ConsentStore(tmp_path / "consent.sqlite")
    # No authorize calls — stdio still sees all.
    all_dbs = [_db("DB-A"), _db("DB-B"), _db("DB-C")]
    visible = s.filter_visible(STDIO_PRINCIPAL, all_dbs)
    assert {db.uuid for db in visible} == {"DB-A", "DB-B", "DB-C"}


def test_stdio_principal_is_authorized_everywhere(tmp_path: Path) -> None:
    s = ConsentStore(tmp_path / "consent.sqlite")
    assert s.is_authorized(STDIO_PRINCIPAL, "any-db") is True


def test_check_or_raise_raises_for_unauthorized(tmp_path: Path) -> None:
    s = ConsentStore(tmp_path / "consent.sqlite")
    s.authorize("alice", "DB-A")
    with pytest.raises(ReconsentRequiredError) as exc:
        s.check_or_raise("alice", "DB-B", database_name="Beta")
    err = exc.value
    assert err.principal_id == "alice"
    assert err.database_uuid == "DB-B"
    assert err.database_name == "Beta"
    # Message includes the human-readable name for the consent UI.
    assert "Beta" in str(err)


def test_check_or_raise_passes_for_authorized(tmp_path: Path) -> None:
    s = ConsentStore(tmp_path / "consent.sqlite")
    s.authorize("alice", "DB-A")
    s.check_or_raise("alice", "DB-A")  # no exception


def test_check_or_raise_passes_for_stdio(tmp_path: Path) -> None:
    s = ConsentStore(tmp_path / "consent.sqlite")
    # Empty store, stdio principal → still authorized.
    s.check_or_raise(STDIO_PRINCIPAL, "any-db")


def test_persistence_across_instances(tmp_path: Path) -> None:
    """A new ConsentStore on the same file sees previous grants."""
    db_path = tmp_path / "consent.sqlite"
    s1 = ConsentStore(db_path)
    s1.authorize("alice", "DB-A")

    s2 = ConsentStore(db_path)
    assert s2.is_authorized("alice", "DB-A") is True


def test_authorize_empty_iterable_is_no_op(tmp_path: Path) -> None:
    s = ConsentStore(tmp_path / "consent.sqlite")
    assert s.authorize("alice", []) == 0
    assert s.authorized_databases("alice") == set()


def test_authorized_databases_for_stdio_returns_empty_set(tmp_path: Path) -> None:
    """stdio bypass means we don't track its grants — be honest in the API."""
    s = ConsentStore(tmp_path / "consent.sqlite")
    assert s.authorized_databases(STDIO_PRINCIPAL) == set()
