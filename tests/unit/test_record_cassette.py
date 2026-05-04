"""Tests for sanitization helpers in _record_cassette."""

from __future__ import annotations

import json
from typing import Any

import pytest
from istefox_dt_mcp_server._record_cassette import (
    SanitizationError,
    sanitize_cassette,
)

_MANIFEST = {
    "version": 1,
    "database": {
        "name": "fixtures-dt-mcp",
        "uuid_placeholder": "FIXTURE-DB-0001",
    },
    "groups": [
        {"path": "/Inbox", "uuid_placeholder": "FIXTURE-GRP-INBOX"},
        {"path": "/Archive", "uuid_placeholder": "FIXTURE-GRP-ARCHIVE"},
    ],
    "records": [
        {
            "uuid_placeholder": "FIXTURE-REC-0001",
            "name": "Sample PDF Invoice 2025",
            "kind": "PDF",
            "location": "/Inbox",
            "tags": ["invoices"],
            "creation_date": "2025-01-01T00:00:00Z",
            "modification_date": "2025-01-01T00:00:00Z",
        },
    ],
}


def test_sanitize_replaces_known_uuids() -> None:
    """When the record name matches the manifest, the UUID is rewritten."""
    captured = {
        "script": "get_record.js",
        "argv": ["DT-RUNTIME-UUID-XYZ"],
        "stdout": json.dumps(
            {
                "uuid": "DT-RUNTIME-UUID-XYZ",
                "name": "Sample PDF Invoice 2025",
                "location": "/Inbox",
            }
        ),
    }
    out = sanitize_cassette(captured, _MANIFEST)
    parsed = json.loads(out["stdout"])
    assert parsed["uuid"] == "FIXTURE-REC-0001"


def test_sanitize_rewrites_filesystem_paths() -> None:
    captured = {
        "script": "list_databases.js",
        "argv": [],
        "stdout": json.dumps(
            [{"name": "fixtures-dt-mcp", "path": "/Users/john/Library/db.dtBase2"}]
        ),
    }
    out = sanitize_cassette(captured, _MANIFEST)
    assert "/Users/fixture/" in out["stdout"]
    assert "/Users/john/" not in out["stdout"]


def test_sanitize_replaces_unknown_record_name() -> None:
    # Two records: one known (keeps UUID resolved), one unknown name.
    # This keeps the unknown-UUID fraction at 1/2 = 50%, which is NOT
    # strictly greater than the default abort_threshold of 0.5, so the
    # sanitizer should return normally rather than raise SanitizationError.
    captured = {
        "script": "search.js",
        "argv": ["something"],
        "stdout": json.dumps(
            [
                {
                    "uuid": "DT-RUNTIME-KNOWN",
                    "name": "Sample PDF Invoice 2025",
                    "location": "/Inbox",
                },
                {
                    "uuid": "DT-RUNTIME-XYZ",
                    "name": "Personal Diary",
                    "location": "/Inbox",
                },
            ]
        ),
    }
    out = sanitize_cassette(captured, _MANIFEST)
    parsed = json.loads(out["stdout"])
    assert parsed[1]["name"] == "<UNKNOWN_NAME_1>"


def test_sanitize_replaces_unknown_path() -> None:
    captured = {
        "script": "search.js",
        "argv": ["x"],
        "stdout": json.dumps(
            [
                {
                    "uuid": "x",
                    "name": "Sample PDF Invoice 2025",
                    "location": "/Confidential",
                }
            ]
        ),
    }
    out = sanitize_cassette(captured, _MANIFEST)
    parsed = json.loads(out["stdout"])
    assert parsed[0]["location"] == "<UNKNOWN_PATH_1>"


def test_sanitize_aborts_when_too_many_unknowns() -> None:
    """If >50% of UUIDs lack a manifest match, abort with SanitizationError."""
    captured = {
        "script": "search.js",
        "argv": ["x"],
        "stdout": json.dumps(
            [
                {"uuid": "U1", "name": "Unknown 1", "location": "/Inbox"},
                {"uuid": "U2", "name": "Unknown 2", "location": "/Inbox"},
                {"uuid": "U3", "name": "Unknown 3", "location": "/Inbox"},
            ]
        ),
    }
    with pytest.raises(SanitizationError, match="unknown UUIDs"):
        sanitize_cassette(captured, _MANIFEST)


def test_sanitize_raises_on_invalid_json_stdout() -> None:
    captured = {"script": "x.js", "argv": [], "stdout": "not valid json {"}
    with pytest.raises(SanitizationError, match="not valid JSON"):
        sanitize_cassette(captured, _MANIFEST)


def test_sanitize_handles_empty_stdout() -> None:
    captured = {"script": "x.js", "argv": [], "stdout": ""}
    out = sanitize_cassette(captured, _MANIFEST)
    assert out["stdout"] == ""


# ----------------------------------------------------------------------
# record_cassette orchestrator (with mocked adapter)
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_cassette_writes_correct_format(tmp_path) -> None:
    """End-to-end: recorder captures the first JXA call and writes to disk."""
    from unittest.mock import AsyncMock, MagicMock

    from istefox_dt_mcp_server._record_cassette import record_cassette

    deps = MagicMock()
    captured_stdout = json.dumps(
        [
            {
                "uuid": "DT-RUNTIME-XYZ",
                "name": "fixtures-dt-mcp",
                "path": "/Users/john/Library/db.dtBase2",
                "is_open": True,
                "record_count": 10,
            }
        ]
    )
    deps.adapter._run_script = AsyncMock(return_value=captured_stdout)

    async def fake_list_databases() -> Any:
        return await deps.adapter._run_script("list_databases.js")

    deps.adapter.list_databases = fake_list_databases

    out_path = await record_cassette(
        tool="list_databases",
        deps=deps,
        cassettes_dir=tmp_path,
        manifest=_MANIFEST,
    )

    assert out_path.exists()
    cassette = json.loads(out_path.read_text())
    assert "script" in cassette
    assert "argv" in cassette
    assert "stdout" in cassette
    assert "/Users/fixture/" in cassette["stdout"]


@pytest.mark.asyncio
async def test_record_cassette_rejects_unsupported_tool(tmp_path) -> None:
    from unittest.mock import MagicMock

    from istefox_dt_mcp_server._record_cassette import record_cassette

    with pytest.raises(ValueError, match="Unsupported tool"):
        await record_cassette(
            tool="nonexistent",
            deps=MagicMock(),
            cassettes_dir=tmp_path,
            manifest=_MANIFEST,
        )


@pytest.mark.asyncio
async def test_record_cassette_uses_default_inputs(tmp_path) -> None:
    """If input_args is None, the recorder uses DEFAULT_INPUTS[tool]."""
    from unittest.mock import AsyncMock, MagicMock

    from istefox_dt_mcp_server._record_cassette import (
        DEFAULT_INPUTS,
        record_cassette,
    )

    deps = MagicMock()
    deps.adapter._run_script = AsyncMock(
        return_value=json.dumps({"uuid": "x", "name": "Sample PDF Invoice 2025"})
    )

    capture_args: dict[str, Any] = {}

    async def fake_get_record(uuid: str) -> Any:
        capture_args["uuid"] = uuid
        return await deps.adapter._run_script("get_record.js", uuid)

    deps.adapter.get_record = fake_get_record

    await record_cassette(
        tool="get_record",
        input_args=None,
        deps=deps,
        cassettes_dir=tmp_path,
        manifest=_MANIFEST,
    )

    assert capture_args["uuid"] == DEFAULT_INPUTS["get_record"]["uuid"]


@pytest.mark.asyncio
async def test_resolve_placeholder_uuids_translates_known_placeholder() -> None:
    """When args.uuid matches a manifest placeholder, it is replaced with
    the live DT UUID returned by adapter._jxa_inline."""
    from unittest.mock import AsyncMock, MagicMock

    from istefox_dt_mcp_server._record_cassette import _resolve_placeholder_uuids

    adapter = MagicMock()
    adapter._jxa_inline = AsyncMock(return_value={"uuid": "REAL-DT-UUID-12345"})

    args_in = {"uuid": "FIXTURE-REC-0001", "tag": "review"}
    args_out = await _resolve_placeholder_uuids(args_in, _MANIFEST, adapter)

    assert args_out["uuid"] == "REAL-DT-UUID-12345"
    assert args_out["tag"] == "review"
    adapter._jxa_inline.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_placeholder_uuids_passes_through_unknown() -> None:
    """If args.uuid is NOT a known placeholder, args is returned unchanged
    and the adapter is not called."""
    from unittest.mock import AsyncMock, MagicMock

    from istefox_dt_mcp_server._record_cassette import _resolve_placeholder_uuids

    adapter = MagicMock()
    adapter._jxa_inline = AsyncMock()

    args_in = {"uuid": "SOME-UNKNOWN-UUID-NOT-IN-MANIFEST"}
    args_out = await _resolve_placeholder_uuids(args_in, _MANIFEST, adapter)

    assert args_out == args_in
    adapter._jxa_inline.assert_not_awaited()


def test_sanitize_distinguishes_database_inbox_from_group_inbox() -> None:
    """The system DB named 'Inbox' must NOT be matched against the manifest
    group named '/Inbox' (different entities, different placeholders)."""
    manifest = dict(_MANIFEST)
    manifest["system_databases"] = [
        {"name": "Inbox", "uuid_placeholder": "FIXTURE-DB-SYSINBOX"}
    ]
    captured = {
        "script": "list_databases.js",
        "argv": [],
        "stdout": json.dumps(
            [
                {
                    "uuid": "FIRST-DB-UUID",
                    "name": "fixtures-dt-mcp",
                    "path": "/Users/me/db.dtBase2",
                    "is_open": True,
                    "record_count": 10,
                },
                {
                    "uuid": "INBOX-DB-UUID",
                    "name": "Inbox",
                    "path": "/Users/me/Inbox.dtBase2",
                    "is_open": True,
                    "record_count": 5,
                },
            ]
        ),
    }
    out = sanitize_cassette(captured, manifest, abort_threshold=0.99)
    parsed = json.loads(out["stdout"])
    assert parsed[0]["uuid"] == "FIXTURE-DB-0001"
    # Critical: Inbox DB resolves to system_databases placeholder, NOT to
    # the group placeholder FIXTURE-GRP-INBOX.
    assert parsed[1]["uuid"] == "FIXTURE-DB-SYSINBOX"
    assert parsed[1]["uuid"] != "FIXTURE-GRP-INBOX"
