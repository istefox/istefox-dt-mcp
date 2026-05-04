#!/usr/bin/env python3
"""Idempotently recreate the fixtures-dt-mcp DEVONthink test database.

Reads tests/fixtures/dt-database-manifest.json, ensures the database,
groups, and records exist in DT4. Re-running the script after manual
edits restores the manifest's intended state (groups added, missing
records created — pre-existing records are NOT mutated to avoid
clobbering tweaks from the developer).

Prerequisites:
  - DEVONthink 4 running
  - AppleEvents permission granted to your terminal (`Privacy & Security
    → Automation → DEVONthink` toggled ON for Terminal.app)

Usage:
  python scripts/setup_test_database.py

Idempotency:
  - DB exists?     → re-use
  - Group exists?  → skip
  - Record name exists in DB? → skip (preserves user edits)
  - Record missing? → create with manifest properties

Exit codes:
  0 — success
  1 — DT not running or AppleEvents denied
  2 — manifest file missing or invalid

This script is intentionally **not** wired into pytest. It runs once
to set up the fixture DB; cassette recording (the next step) reads
from that DB via the record-cassette CLI.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run_jxa(script: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["osascript", "-l", "JavaScript", "-e", script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _ensure_database(db_name: str) -> str:
    """Returns the database UUID; creates the DB if missing."""
    script = f"""
    const dt = Application("DEVONthink");
    const existing = dt.databases().filter(d => d.name() === "{db_name}");
    if (existing.length > 0) {{
      JSON.stringify({{action: "reused", uuid: existing[0].uuid()}});
    }} else {{
      const newDbPath = ObjC.unwrap(
        $.NSString.stringWithString("~/Databases/{db_name}.dtBase2")
          .stringByExpandingTildeInPath
      );
      dt.createDatabase(newDbPath);
      // DT4 JXA quirk: createDatabase return value is unreliable (often null).
      // Re-lookup by name to get a valid reference.
      const created = dt.databases().filter(d => d.name() === "{db_name}");
      if (created.length === 0) {{
        throw new Error("createDatabase did not produce a database named '{db_name}' in dt.databases()");
      }}
      JSON.stringify({{action: "created", uuid: created[0].uuid()}});
    }}
    """
    rc, stdout, stderr = _run_jxa(script)
    if rc != 0:
        raise RuntimeError(f"DB ensure failed: {stderr.strip() or stdout.strip()}")
    result = json.loads(stdout.strip())
    print(f"  database '{db_name}': {result['action']} (uuid: {result['uuid']})")
    return str(result["uuid"])


def _ensure_group(db_name: str, path: str) -> str:
    """Returns the group UUID; creates if missing. path is /A/B/C style."""
    parts = [p for p in path.split("/") if p]
    if not parts:
        raise ValueError(f"Invalid group path: {path}")

    script = f"""
    const dt = Application("DEVONthink");
    const dbs = dt.databases().filter(d => d.name() === "{db_name}");
    if (dbs.length === 0) throw new Error("DB not found: {db_name}");
    const db = dbs[0];

    let parent = db.root;
    const parts = {json.dumps(parts)};
    let current_uuid = null;

    for (const part of parts) {{
      const existing = parent.children().filter(c => c.name() === part && c.recordType() === "group");
      if (existing.length > 0) {{
        parent = existing[0];
        current_uuid = parent.uuid();
      }} else {{
        const newGroup = dt.createLocation(part, {{in: parent}});
        parent = newGroup;
        current_uuid = newGroup.uuid();
      }}
    }}
    JSON.stringify({{uuid: current_uuid}});
    """
    rc, stdout, stderr = _run_jxa(script)
    if rc != 0:
        raise RuntimeError(
            f"Group ensure failed for {path}: {stderr.strip() or stdout.strip()}"
        )
    result = json.loads(stdout.strip())
    print(f"  group '{path}': uuid {result['uuid']}")
    return str(result["uuid"])


# Manifest "kind" values mirror RecordKind (the read-side enum returned by
# record.kind()). DT4's createRecordWith expects a different "type" enum on
# the write side. Map the read-side strings to the write-side ones here.
_KIND_TO_DT4_TYPE = {
    "PDF": "PDF document",
    "rtf": "rtf",
    "markdown": "markdown",
    "txt": "text",
    "webarchive": "webarchive",
    "bookmark": "bookmark",
    "html": "html",
    "image": "picture",
}


def _ensure_record(db_name: str, rec: dict[str, object]) -> tuple[str, str]:
    """Returns (action, uuid). action in {created, skipped}."""
    kind = str(rec["kind"])
    dt4_type = _KIND_TO_DT4_TYPE.get(kind)
    if dt4_type is None:
        raise RuntimeError(
            f"Unsupported manifest kind '{kind}' for record '{rec['name']}'. "
            f"Add a mapping to _KIND_TO_DT4_TYPE."
        )

    location = str(rec.get("location") or "/")
    location_parts = [p for p in location.split("/") if p]

    script = f"""
    const dt = Application("DEVONthink");
    const dbs = dt.databases().filter(d => d.name() === "{db_name}");
    if (dbs.length === 0) throw new Error("DB not found");
    const db = dbs[0];

    // Walk to the destination group from db.root.
    let parent = db.root;
    const locParts = {json.dumps(location_parts)};
    for (const part of locParts) {{
      const matches = parent.children().filter(c =>
        c.name() === part && c.recordType() === "group"
      );
      if (matches.length === 0) {{
        throw new Error("Group not found in path: " + part);
      }}
      parent = matches[0];
    }}

    // Skip if a record with this name already exists anywhere in the DB.
    const existing = db.contents().filter(r =>
      r.name() === {json.dumps(rec['name'])}
    );
    if (existing.length > 0) {{
      JSON.stringify({{action: "skipped", uuid: existing[0].uuid()}});
    }} else {{
      // DT4 quirk: createRecordWith returns a reference that is sometimes
      // null in JXA. Lookup-by-name after creation to get a stable handle.
      dt.createRecordWith({{
        name: {json.dumps(rec['name'])},
        type: {json.dumps(dt4_type)},
      }}, {{in: parent}});
      const created = parent.children().filter(r =>
        r.name() === {json.dumps(rec['name'])}
      );
      if (created.length === 0) {{
        throw new Error("createRecordWith did not produce '{rec['name']}'");
      }}
      created[0].tags = {json.dumps(rec.get('tags', []))};
      JSON.stringify({{action: "created", uuid: created[0].uuid()}});
    }}
    """
    rc, stdout, stderr = _run_jxa(script)
    if rc != 0:
        raise RuntimeError(
            f"Record ensure failed for {rec['name']}: {stderr.strip() or stdout.strip()}"
        )
    result = json.loads(stdout.strip())
    return str(result["action"]), str(result["uuid"])


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    manifest_path = repo_root / "tests" / "fixtures" / "dt-database-manifest.json"
    if not manifest_path.exists():
        print(f"ERROR: manifest missing at {manifest_path}", file=sys.stderr)
        return 2
    manifest = json.loads(manifest_path.read_text())

    db_name = manifest["database"]["name"]
    print(f"Setting up test database '{db_name}'...")

    try:
        _ensure_database(db_name)
        for group in manifest["groups"]:
            _ensure_group(db_name, group["path"])
        created = 0
        skipped = 0
        for rec in manifest["records"]:
            action, _ = _ensure_record(db_name, rec)
            if action == "created":
                created += 1
            else:
                skipped += 1
        print(f"\n✅ done: {created} created, {skipped} already present")
        return 0
    except RuntimeError as e:
        print(f"❌ failure: {e}", file=sys.stderr)
        if "AppleEvents" in str(e) or "1743" in str(e):
            print(
                "  Fix: System Settings → Privacy & Security → Automation → "
                "enable DEVONthink for your terminal.",
                file=sys.stderr,
            )
        return 1


if __name__ == "__main__":
    sys.exit(main())
