"""Resource schema + helper unit tests (0.5.0)."""

from __future__ import annotations

from datetime import UTC, datetime

from istefox_dt_mcp_schemas.common import Database, Record
from istefox_dt_mcp_schemas.tools import (
    DatabaseListResource,
    RecordMetadataResource,
    RecordTextResource,
)


def _record(uuid: str = "R-1") -> Record:
    return Record(
        uuid=uuid,
        name="Doc",
        kind="PDF",
        location="/Inbox",
        reference_url=f"x-devonthink-item://{uuid}",
        creation_date=datetime(2026, 1, 1, tzinfo=UTC),
        modification_date=datetime(2026, 1, 2, tzinfo=UTC),
        tags=["a", "b"],
        database_uuid="DB-1",
    )


def test_database_list_resource_roundtrip() -> None:
    db = Database(uuid="DB-1", name="Alpha", path="/p", is_open=True)
    model = DatabaseListResource(databases=[db], truncated=False)
    dumped = model.model_dump(mode="json")
    assert dumped["databases"][0]["uuid"] == "DB-1"
    assert dumped["truncated"] is False


def test_record_metadata_resource_roundtrip() -> None:
    model = RecordMetadataResource(record=_record(), tags_truncated=False)
    dumped = model.model_dump(mode="json")
    assert dumped["record"]["uuid"] == "R-1"
    assert dumped["tags_truncated"] is False


def test_record_text_resource_roundtrip() -> None:
    model = RecordTextResource(
        uuid="R-1", text="hello", truncated=False, returned_chars=5
    )
    dumped = model.model_dump(mode="json")
    assert dumped == {
        "uuid": "R-1",
        "text": "hello",
        "truncated": False,
        "returned_chars": 5,
    }
