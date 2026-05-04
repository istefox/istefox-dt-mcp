"""Tests for sanitization helpers in _record_cassette."""

from __future__ import annotations

import json

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
