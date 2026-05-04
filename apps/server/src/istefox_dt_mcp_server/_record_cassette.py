"""Cassette recording infrastructure for tests/contract/cassettes/.

Two responsibilities, separated for testability:

1. ``sanitize_cassette`` — pure function that rewrites captured stdout
   to use stable manifest placeholders (UUIDs, names, paths). Defense
   in depth: even if the recorder is pointed at the wrong DB, the
   sanitizer flags suspicious data and aborts before disk write.

2. ``record_cassette`` (in Task 5) — async orchestrator that wraps
   adapter._run_script, invokes the named tool, captures the first
   JXA call, applies sanitize_cassette, writes to disk.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)


SAFE_USERNAME_PLACEHOLDER = "fixture"


class SanitizationError(RuntimeError):
    """Raised when the captured cassette doesn't match the manifest.

    Indicates the recorder was pointed at the wrong DB or the manifest
    is stale. Aborting prevents committing a leaky cassette.
    """


def _build_name_to_uuid_map(manifest: dict[str, Any]) -> dict[str, str]:
    """Map record name → manifest uuid_placeholder for fast lookup."""
    out = {rec["name"]: rec["uuid_placeholder"] for rec in manifest.get("records", [])}
    out[manifest["database"]["name"]] = manifest["database"]["uuid_placeholder"]
    for group in manifest.get("groups", []):
        # Groups keyed by their last path segment (e.g. "Inbox" from "/Inbox")
        # because DT may surface the leaf name rather than the full path.
        leaf = group["path"].rstrip("/").split("/")[-1] or group["path"]
        out[leaf] = group["uuid_placeholder"]
    return out


def _build_path_set(manifest: dict[str, Any]) -> set[str]:
    """Collect all known paths from the manifest groups + records."""
    paths: set[str] = set()
    for group in manifest.get("groups", []):
        paths.add(group["path"])
    for rec in manifest.get("records", []):
        paths.add(rec["location"])
    return paths


def _rewrite_filesystem_paths(text: str) -> str:
    """Replace any /Users/<name>/ with /Users/fixture/."""
    return re.sub(r"/Users/[^/]+/", f"/Users/{SAFE_USERNAME_PLACEHOLDER}/", text)


def sanitize_cassette(
    cassette: dict[str, Any],
    manifest: dict[str, Any],
    *,
    abort_threshold: float = 0.5,
) -> dict[str, Any]:
    """Rewrite a captured cassette to use manifest-stable identifiers.

    Operations:
      - Filesystem paths /Users/<name>/ → /Users/fixture/
      - UUIDs in the captured stdout JSON: if the parent record's `name`
        matches a manifest entry, the UUID is replaced with the manifest
        placeholder. Otherwise the UUID is flagged unknown.
      - Record names not in the manifest: replaced with <UNKNOWN_NAME_n>.
      - Locations not in the manifest groups: replaced with <UNKNOWN_PATH_n>.

    Args:
        cassette: dict with keys "script", "argv", "stdout" (raw string).
        manifest: parsed dt-database-manifest.json content.
        abort_threshold: max fraction of unknown items before aborting.
            Default 0.5: if more than half the records in the captured
            stdout don't match manifest entries, we assume the recorder
            was pointed at the wrong DB and abort.

    Returns:
        New cassette dict with sanitized stdout.

    Raises:
        SanitizationError: if abort_threshold is exceeded or stdout is
            not parseable JSON.
    """
    name_to_uuid = _build_name_to_uuid_map(manifest)
    known_paths = _build_path_set(manifest)

    raw_stdout = cassette.get("stdout", "")
    if not raw_stdout:
        return {**cassette}

    # Step 1: filesystem paths (text-level)
    stdout_text = _rewrite_filesystem_paths(raw_stdout)

    # Step 2: parse JSON for record-level rewrites
    try:
        parsed = json.loads(stdout_text)
    except json.JSONDecodeError as e:
        raise SanitizationError(
            f"Captured stdout is not valid JSON: {e}. "
            f"First 200 chars: {stdout_text[:200]!r}"
        ) from e

    unknown_count = 0
    total_count = 0
    unknown_name_counter = 0
    unknown_path_counter = 0

    def _walk(node: Any) -> Any:
        nonlocal unknown_count, total_count, unknown_name_counter, unknown_path_counter
        if isinstance(node, dict):
            new: dict[str, Any] = {}
            name_field = node.get("name")
            for key, val in node.items():
                if (
                    key == "uuid"
                    and isinstance(val, str)
                    and name_field in name_to_uuid
                ):
                    new[key] = name_to_uuid[name_field]
                    total_count += 1
                elif key == "uuid" and isinstance(val, str):
                    new[key] = val
                    total_count += 1
                    unknown_count += 1
                elif key == "name" and isinstance(val, str) and val not in name_to_uuid:
                    unknown_name_counter += 1
                    new[key] = f"<UNKNOWN_NAME_{unknown_name_counter}>"
                elif (
                    key in ("location", "path")
                    and isinstance(val, str)
                    and val not in known_paths
                    and not val.startswith("/Users/fixture/")
                ):
                    unknown_path_counter += 1
                    new[key] = f"<UNKNOWN_PATH_{unknown_path_counter}>"
                else:
                    new[key] = _walk(val)
            return new
        if isinstance(node, list):
            return [_walk(item) for item in node]
        return node

    sanitized_parsed = _walk(parsed)

    if total_count > 0 and unknown_count / total_count > abort_threshold:
        raise SanitizationError(
            f"Captured cassette has {unknown_count}/{total_count} unknown UUIDs "
            f"({unknown_count / total_count:.0%}, threshold {abort_threshold:.0%}). "
            "Are you running the recorder against fixtures-dt-mcp?"
        )

    log.debug(
        "cassette_sanitized",
        total_uuids=total_count,
        unknown_uuids=unknown_count,
        unknown_names=unknown_name_counter,
        unknown_paths=unknown_path_counter,
    )

    return {
        "script": cassette.get("script", ""),
        "argv": cassette.get("argv", []),
        "stdout": json.dumps(sanitized_parsed, ensure_ascii=False),
    }


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    """Load the canonical fixture-DB manifest from disk.

    Default path is ``tests/fixtures/dt-database-manifest.json`` resolved
    against the repo root. Tests can pass an explicit path to use a
    purpose-built manifest fixture.
    """
    if path is None:
        # __file__ lives at apps/server/src/istefox_dt_mcp_server/_record_cassette.py
        # so parents[4] is the repo root that contains apps/ and tests/.
        repo_root = Path(__file__).resolve().parents[4]
        path = repo_root / "tests" / "fixtures" / "dt-database-manifest.json"
    with path.open(encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)
    return data


# ----------------------------------------------------------------------
# Recording orchestrator
# ----------------------------------------------------------------------


# Default inputs for the --all mode. Each entry is the JSON args the CLI
# would pass via --input; subagent/Stefano can override per-tool when
# recording manually.
DEFAULT_INPUTS: dict[str, dict[str, Any]] = {
    "list_databases": {},
    "search_bm25": {"query": "Sample", "databases": ["fixtures-dt-mcp"]},
    "find_related": {"uuid": "FIXTURE-REC-0001-AAAA-AAAAAAAAAAAA", "k": 5},
    "get_record": {"uuid": "FIXTURE-REC-0001-AAAA-AAAAAAAAAAAA"},
    "apply_tag": {
        "uuid": "FIXTURE-REC-0001-AAAA-AAAAAAAAAAAA",
        "tag": "review",
    },
    "move_record": {
        "uuid": "FIXTURE-REC-0001-AAAA-AAAAAAAAAAAA",
        # move_record.js parses destination as "Database/Group/Subgroup":
        # the first segment is the DB name, not a leading slash.
        "destination": "fixtures-dt-mcp/Archive",
    },
}


SUPPORTED_TOOLS: tuple[str, ...] = tuple(DEFAULT_INPUTS.keys())


async def _resolve_placeholder_uuids(
    args: dict[str, Any],
    manifest: dict[str, Any],
    adapter: Any,
) -> dict[str, Any]:
    """Translate manifest placeholder UUIDs in ``args`` to live DT UUIDs.

    DEFAULT_INPUTS (and any --input passed by Stefano) reference records
    by their stable manifest placeholder UUIDs (e.g.
    ``FIXTURE-REC-0001-AAAA-AAAAAAAAAAAA``). Live DT4 has its own UUIDs
    generated at record-creation time, so we look up the corresponding
    record by NAME in the live DB and substitute the real UUID before
    invoking the tool. The post-capture sanitizer handles the reverse
    mapping in stdout.

    Only the ``uuid`` key is translated — other keys (query, destination,
    tag, ...) pass through. If ``args["uuid"]`` is not a known
    placeholder, it is left untouched (so callers can also pass real
    UUIDs directly).

    Calls the adapter via ``_jxa_inline``, which bypasses
    ``_run_script`` and therefore is NOT intercepted by ``_RecorderShim``
    (the shim must be installed AFTER this resolver returns).
    """
    if "uuid" not in args:
        return args
    placeholder = args["uuid"]

    record_name: str | None = None
    for rec in manifest.get("records", []):
        if rec.get("uuid_placeholder") == placeholder:
            record_name = rec.get("name")
            break
    if record_name is None:
        return args

    db_name = manifest["database"]["name"]
    code = (
        'const dt = Application("DEVONthink");'
        f"const db = dt.databases().filter(d => d.name() === {json.dumps(db_name)})[0];"
        f'if (!db) throw new Error("DB not found: " + {json.dumps(db_name)});'
        f"const recs = db.contents().filter(r => r.name() === {json.dumps(record_name)});"
        f'if (recs.length === 0) throw new Error("Record not found by name: " + {json.dumps(record_name)});'
        "JSON.stringify({uuid: recs[0].uuid()});"
    )
    raw = await adapter._jxa_inline(code)
    parsed = raw if isinstance(raw, dict) else json.loads(raw)
    new_args = dict(args)
    new_args["uuid"] = parsed["uuid"]
    return new_args


class _RecorderShim:
    """Wraps an adapter's _run_script to intercept the FIRST JXA call.

    After the first call, subsequent calls pass through unchanged.
    The captured (script, argv, stdout) is exposed via .captured.
    """

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter
        self._original = adapter._run_script
        self.captured: dict[str, Any] | None = None

    async def _wrapped(self, script: str, *args: Any, **kwargs: Any) -> Any:
        result = await self._original(script, *args, **kwargs)
        if self.captured is None:
            argv = list(args) + [str(v) for v in kwargs.values()]
            self.captured = {
                "script": "<inline>.js",
                "argv": argv,
                "stdout": result if isinstance(result, str) else json.dumps(result),
            }
        return result

    def install(self) -> None:
        self._adapter._run_script = self._wrapped

    def uninstall(self) -> None:
        self._adapter._run_script = self._original


async def record_cassette(
    *,
    tool: str,
    input_args: dict[str, Any] | None = None,
    deps: Any,
    cassettes_dir: Path,
    manifest: dict[str, Any],
) -> Path:
    """Record a single cassette by invoking the named tool against live DT.

    Steps:
      1. Validate ``tool`` is in SUPPORTED_TOOLS.
      2. Wrap deps.adapter._run_script with _RecorderShim.
      3. Look up the tool's adapter method by name and invoke with input_args.
      4. Sanitize the captured stdout via sanitize_cassette.
      5. Write the result to ``cassettes_dir / f"{tool}.json"``.

    Args:
        tool: Name of the tool to record (must be in SUPPORTED_TOOLS).
        input_args: Args dict to pass to the tool. If None, uses DEFAULT_INPUTS[tool].
        deps: Live Deps with a real JXAAdapter (NOT mocked).
        cassettes_dir: Directory to write the cassette JSON into. Created if missing.
        manifest: Loaded fixture-DB manifest (use load_manifest()).

    Returns:
        Path to the written cassette file.

    Raises:
        ValueError: tool not in SUPPORTED_TOOLS.
        SanitizationError: capture didn't match the manifest.
    """
    if tool not in SUPPORTED_TOOLS:
        raise ValueError(
            f"Unsupported tool {tool!r}. Supported: {', '.join(SUPPORTED_TOOLS)}"
        )

    args = dict(input_args if input_args is not None else DEFAULT_INPUTS[tool])
    args = await _resolve_placeholder_uuids(args, manifest, deps.adapter)
    shim = _RecorderShim(deps.adapter)
    shim.install()

    try:
        if tool == "list_databases":
            await deps.adapter.list_databases()
        elif tool == "search_bm25":
            await deps.adapter.search(
                args["query"],
                databases=args.get("databases"),
                max_results=args.get("max_results", 10),
            )
        elif tool == "find_related":
            await deps.adapter.find_related(args["uuid"], k=args.get("k", 10))
        elif tool == "get_record":
            await deps.adapter.get_record(args["uuid"])
        elif tool == "apply_tag":
            await deps.adapter.apply_tag(args["uuid"], args["tag"], dry_run=False)
        elif tool == "move_record":
            await deps.adapter.move_record(
                args["uuid"], args["destination"], dry_run=False
            )
        else:  # pragma: no cover — guarded by the SUPPORTED_TOOLS check above
            raise AssertionError("unreachable")
    finally:
        shim.uninstall()

    if shim.captured is None:
        raise RuntimeError(
            f"Recording {tool} captured nothing. The tool didn't issue a JXA call."
        )

    sanitized = sanitize_cassette(shim.captured, manifest)
    cassettes_dir.mkdir(parents=True, exist_ok=True)
    out_path = cassettes_dir / f"{tool}.json"
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(sanitized, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    log.info("cassette_recorded", tool=tool, path=str(out_path))
    return out_path
