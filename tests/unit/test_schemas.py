"""Pydantic schema round-trip + validation."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from istefox_dt_mcp_schemas.audit import AuditEntry
from istefox_dt_mcp_schemas.common import (
    Database,
    Envelope,
    Record,
    RecordKind,
    SearchResult,
    WriteOutcome,
)
from istefox_dt_mcp_schemas.errors import ErrorCode, StructuredError
from istefox_dt_mcp_schemas.tools import (
    ListDatabasesOutput,
    SearchInput,
    SearchOutput,
)
from pydantic import ValidationError


def _now() -> datetime:
    return datetime.now()


def test_database_round_trip() -> None:
    db = Database(uuid="u", name="X", path="/p", is_open=True)
    assert Database.model_validate(db.model_dump()) == db


def test_record_round_trip() -> None:
    r = Record(
        uuid="u",
        name="n",
        kind=RecordKind.PDF,
        location="/L",
        reference_url="x-d://1",
        creation_date=_now(),
        modification_date=_now(),
        tags=["a", "b"],
    )
    assert Record.model_validate(r.model_dump(mode="json")) == r


def test_search_input_validation() -> None:
    s = SearchInput(query="hello")
    assert s.max_results == 10
    assert s.mode == "bm25"


def test_search_input_rejects_empty_query() -> None:
    with pytest.raises(ValidationError):
        SearchInput(query="")


def test_search_input_rejects_oversize_max_results() -> None:
    with pytest.raises(ValidationError):
        SearchInput(query="x", max_results=500)


def test_envelope_success() -> None:
    out = ListDatabasesOutput(success=True, data=[])
    assert out.success is True
    assert out.data == []


def test_envelope_failure() -> None:
    out: SearchOutput = SearchOutput(
        success=False,
        data=None,
        error_code=ErrorCode.DT_NOT_RUNNING.value,
        error_message="non avviato",
        recovery_hint="avvia DT",
    )
    assert out.success is False
    assert out.error_code == "DT_NOT_RUNNING"


def test_audit_entry_round_trip() -> None:
    e = AuditEntry(
        audit_id=uuid4(),
        timestamp=_now(),
        tool_name="search",
        input_json={"q": "x"},
        output_hash="h" * 64,
        duration_ms=12.3,
    )
    assert AuditEntry.model_validate(e.model_dump(mode="json")) == e


def test_structured_error() -> None:
    err = StructuredError(
        code=ErrorCode.RECORD_NOT_FOUND,
        message_en="Record not found",
        message_it="Record non trovato",
        recovery_hint_it="Verifica UUID",
    )
    assert err.code == ErrorCode.RECORD_NOT_FOUND


def test_search_result_optional_fields() -> None:
    r = SearchResult(uuid="u", name="n", location="/L", reference_url="x-d://1")
    assert r.score is None
    assert r.snippet is None


def test_write_outcome_enum() -> None:
    assert WriteOutcome.APPLIED.value == "applied"
    assert WriteOutcome.PREVIEWED.value == "previewed"


def test_envelope_extra_field_rejected() -> None:
    with pytest.raises(ValidationError):
        Envelope(success=True, data=None, foo="bar")  # type: ignore[call-arg]


# ---------------------------------------------------------------------
# Write tool schemas (W4 — schema only, implementation W7+)
# ---------------------------------------------------------------------


def test_file_document_dry_run_default() -> None:
    from istefox_dt_mcp_schemas.tools import FileDocumentInput

    f = FileDocumentInput(record_uuid="u")
    assert f.dry_run is True
    assert f.confirm_token is None


def test_file_document_with_confirm_token() -> None:
    from istefox_dt_mcp_schemas.tools import FileDocumentInput

    f = FileDocumentInput(record_uuid="u", dry_run=False, confirm_token="prev-audit-id")
    assert f.dry_run is False
    assert f.confirm_token == "prev-audit-id"


def test_bulk_apply_min_one_op() -> None:
    from istefox_dt_mcp_schemas.tools import BulkApplyInput

    with pytest.raises(ValidationError):
        BulkApplyInput(operations=[])


def test_bulk_apply_max_500_ops() -> None:
    from istefox_dt_mcp_schemas.tools import BulkApplyInput, BulkApplyOperation

    ops = [
        BulkApplyOperation(record_uuid=f"u{i}", op="add_tag", payload={"tag": "x"})
        for i in range(501)
    ]
    with pytest.raises(ValidationError):
        BulkApplyInput(operations=ops)


def test_undo_dry_run_default() -> None:
    from istefox_dt_mcp_schemas.tools import UndoInput

    u = UndoInput(audit_id="abc-123")
    assert u.dry_run is True
    assert u.drift_detected is False if hasattr(u, "drift_detected") else True


def test_undo_result_drift_flag() -> None:
    from istefox_dt_mcp_schemas.tools import UndoResult

    r = UndoResult(
        audit_id="a",
        target_record_uuid="u",
        reverted=True,
        drift_detected=True,
    )
    assert r.drift_detected is True
