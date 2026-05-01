"""Audit log append-only behavior + retrieval."""

from __future__ import annotations

import sqlite3

import pytest
from istefox_dt_mcp_server.audit import AuditLog


def test_append_returns_uuid(audit_log: AuditLog) -> None:
    audit_id = audit_log.append(
        tool_name="search",
        input_data={"q": "x"},
        output_data=[],
        duration_ms=1.2,
    )
    assert audit_id is not None


def test_get_returns_entry(audit_log: AuditLog) -> None:
    audit_id = audit_log.append(
        tool_name="list_databases",
        input_data={},
        output_data=[{"uuid": "abc"}],
        duration_ms=42.0,
    )
    entry = audit_log.get(audit_id)
    assert entry is not None
    assert entry.tool_name == "list_databases"
    assert entry.input_json == {}
    assert entry.duration_ms == 42.0
    assert entry.principal == "local"
    assert entry.error_code is None


def test_get_missing_returns_none(audit_log: AuditLog) -> None:
    from uuid import uuid4

    assert audit_log.get(uuid4()) is None


def test_append_with_error_code(audit_log: AuditLog) -> None:
    audit_id = audit_log.append(
        tool_name="search",
        input_data={"q": "x"},
        output_data=None,
        duration_ms=10.0,
        error_code="DT_NOT_RUNNING",
    )
    entry = audit_log.get(audit_id)
    assert entry is not None
    assert entry.error_code == "DT_NOT_RUNNING"


def test_update_is_blocked(audit_log: AuditLog) -> None:
    audit_id = audit_log.append(
        tool_name="search",
        input_data={},
        output_data=None,
        duration_ms=1,
    )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        audit_log._conn.execute(
            "UPDATE audit_log SET tool_name = 'hacked' WHERE audit_id = ?",
            (str(audit_id),),
        )


def test_delete_is_blocked(audit_log: AuditLog) -> None:
    audit_id = audit_log.append(
        tool_name="search",
        input_data={},
        output_data=None,
        duration_ms=1,
    )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        audit_log._conn.execute(
            "DELETE FROM audit_log WHERE audit_id = ?",
            (str(audit_id),),
        )


def test_output_hash_stable(audit_log: AuditLog) -> None:
    a = audit_log.append(
        tool_name="t",
        input_data={"k": "v"},
        output_data={"a": 1, "b": 2},
        duration_ms=1,
    )
    b = audit_log.append(
        tool_name="t",
        input_data={"k": "v"},
        output_data={"b": 2, "a": 1},
        duration_ms=1,
    )
    ea = audit_log.get(a)
    eb = audit_log.get(b)
    assert ea is not None and eb is not None
    assert ea.output_hash == eb.output_hash


def test_before_state_persisted(audit_log: AuditLog) -> None:
    audit_id = audit_log.append(
        tool_name="apply_tag",
        input_data={"uuid": "u", "tag": "x"},
        output_data={"applied": True},
        duration_ms=1,
        before_state={"tags": ["a"]},
    )
    entry = audit_log.get(audit_id)
    assert entry is not None
    assert entry.before_state == {"tags": ["a"]}


def test_after_state_persisted_and_one_shot(audit_log: AuditLog) -> None:
    audit_id = audit_log.append(
        tool_name="file_document",
        input_data={"dry_run": False},
        output_data={"applied": True},
        duration_ms=1,
        before_state={"tags": []},
    )
    # Initially no after_state
    entry = audit_log.get(audit_id)
    assert entry is not None
    assert entry.after_state is None

    # First set succeeds
    assert audit_log.set_after_state(audit_id, {"tags": ["x"]}) is True
    entry = audit_log.get(audit_id)
    assert entry is not None
    assert entry.after_state == {"tags": ["x"]}

    # Second set is rejected (one-shot per audit_id)
    assert audit_log.set_after_state(audit_id, {"tags": ["y"]}) is False
    entry = audit_log.get(audit_id)
    assert entry is not None
    # Original snapshot preserved
    assert entry.after_state == {"tags": ["x"]}


def test_after_state_table_is_append_only(audit_log: AuditLog) -> None:
    audit_id = audit_log.append(
        tool_name="file_document",
        input_data={},
        output_data=None,
        duration_ms=1,
    )
    audit_log.set_after_state(audit_id, {"location": "/X"})
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        audit_log._conn.execute(
            "UPDATE audit_after_state SET state = '{}' WHERE audit_id = ?",
            (str(audit_id),),
        )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        audit_log._conn.execute(
            "DELETE FROM audit_after_state WHERE audit_id = ?",
            (str(audit_id),),
        )


def test_list_recent_returns_newest_first(audit_log: AuditLog) -> None:
    """Three appends + list_recent(limit=2) should return the two
    most recent in newest-first order."""
    a1 = audit_log.append(
        tool_name="search",
        input_data={"q": "first"},
        output_data=[],
        duration_ms=1.0,
    )
    a2 = audit_log.append(
        tool_name="file_document",
        input_data={"dry_run": True},
        output_data={},
        duration_ms=2.0,
    )
    a3 = audit_log.append(
        tool_name="file_document",
        input_data={"dry_run": False},
        output_data={},
        duration_ms=3.0,
    )
    rows = audit_log.list_recent(limit=2)
    assert len(rows) == 2
    assert rows[0]["audit_id"] == str(a3)
    assert rows[1]["audit_id"] == str(a2)
    # Older a1 not returned (limit=2)
    assert all(r["audit_id"] != str(a1) for r in rows)
    # Projection includes input parsed back to dict
    assert rows[0]["input"] == {"dry_run": False}


def test_list_recent_filters_by_tool(audit_log: AuditLog) -> None:
    """tool_name filter should restrict the result set."""
    audit_log.append(
        tool_name="search",
        input_data={},
        output_data=[],
        duration_ms=1.0,
    )
    fd_id = audit_log.append(
        tool_name="file_document",
        input_data={"dry_run": False},
        output_data={},
        duration_ms=2.0,
    )
    audit_log.append(
        tool_name="list_databases",
        input_data={},
        output_data=[],
        duration_ms=3.0,
    )
    rows = audit_log.list_recent(limit=10, tool_name="file_document")
    assert len(rows) == 1
    assert rows[0]["audit_id"] == str(fd_id)
    assert rows[0]["tool_name"] == "file_document"


def test_list_recent_includes_error_code(audit_log: AuditLog) -> None:
    """Error rows should expose their error_code so the user can spot
    failed applies (which are not undoable) at a glance."""
    audit_log.append(
        tool_name="file_document",
        input_data={"dry_run": False},
        output_data=None,
        duration_ms=1.0,
        error_code="RECORD_NOT_FOUND",
    )
    rows = audit_log.list_recent(limit=1)
    assert rows[0]["error_code"] == "RECORD_NOT_FOUND"


def test_list_recent_empty_log(audit_log: AuditLog) -> None:
    assert audit_log.list_recent(limit=10) == []
