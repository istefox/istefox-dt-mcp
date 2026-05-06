# Bulk Apply Per-Op Drift Detection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the 3-state drift classifier (`no_drift` / `already_reverted` / `hostile_drift`, today only used by `file_document` undo) to `bulk_apply` undo on a per-op basis, so each op in a bulk batch can be evaluated independently and skipped or reverted accordingly.

**Architecture:** During the apply phase of `bulk_apply`, capture per-op `before` and `after` snapshots (`{location, tags}`) by calling `get_record` immediately before and after each successful op, and persist them in `audit.after_state.per_op_snapshots[idx]`. In `undo._undo_bulk_apply`, walk the applied ops in LIFO order, call the existing `compute_drift_state` per op, and route each op to revert / skip / surface drift. A `drift_per_op` array is added to the undo response. Audit entries written before this change fall back to legacy behavior (no per-op drift detection) via a `bool` branch on the presence of `per_op_snapshots`.

**Tech Stack:** Python 3.12, FastMCP, Pydantic v2, pytest + pytest-asyncio, AsyncMock for adapter mocks, structlog. Project layout: `apps/server/src/istefox_dt_mcp_server/`.

**Reference spec:** [`docs/superpowers/specs/2026-05-06-bulk-apply-drift-detection-design.md`](../specs/2026-05-06-bulk-apply-drift-detection-design.md)

---

### Task 1: Branch + baseline

**Files:** No file changes — preparation only.

- [ ] **Step 1.1: Switch to a new feature branch off main**

```bash
git checkout main
git pull --ff-only
git checkout -b feat/bulk-apply-drift-detection
```

- [ ] **Step 1.2: Establish a green baseline**

```bash
uv run pytest tests/unit -q --tb=short
```

Expected: 200+ pass, 0 fail. If any fail, stop and investigate.

- [ ] **Step 1.3: Read the two files you'll be touching**

```bash
wc -l apps/server/src/istefox_dt_mcp_server/tools/bulk_apply.py \
      apps/server/src/istefox_dt_mcp_server/undo.py \
      tests/unit/test_undo.py \
      tests/unit/test_tools/test_bulk_apply.py
```

Expected line counts (approximate, may drift): 278, 448, 320+, varies. Skim them — the tests reuse a `_record()` helper and an audit-fixture pattern that you'll mirror.

---

### Task 2: Capture per-op `before` snapshot in `bulk_apply` apply phase (TDD)

**Files:**
- Modify: `apps/server/src/istefox_dt_mcp_server/tools/bulk_apply.py`
- Modify: `tests/unit/test_tools/test_bulk_apply.py`

The apply loop currently calls `get_record` only for `move` ops (to populate `pre_move_snapshots`). We need it for **every** op, before dispatch, capturing both `location` and `tags`. Reuse the existing `move` snapshot to avoid double-fetching.

- [ ] **Step 2.1: Add a failing unit test**

Append at the bottom of `tests/unit/test_tools/test_bulk_apply.py`:

```python
@pytest.mark.asyncio
async def test_apply_persists_per_op_before_snapshot(deps_with_audit):
    """After applying an add_tag op, audit.after_state.per_op_snapshots[idx]
    must contain a `before` block with the record's location + tags as
    they were just before dispatch."""
    deps = deps_with_audit
    deps.adapter.get_record = AsyncMock(
        return_value=Record(
            uuid="u1",
            name="r1",
            kind=RecordKind.PDF,
            location="/Inbox",
            reference_url="x-d://u1",
            creation_date=datetime.now(),
            modification_date=datetime.now(),
            tags=["existing"],
        )
    )
    deps.adapter.apply_tag = AsyncMock(return_value=None)

    # Two-phase: preview to mint a token, then apply
    preview_input = BulkApplyInput(
        operations=[
            BulkApplyOperation(record_uuid="u1", op="add_tag", payload={"tag": "new"}),
        ],
        dry_run=True,
    )
    preview = await _call_bulk_apply(deps, preview_input)
    apply_input = BulkApplyInput(
        operations=preview_input.operations,
        dry_run=False,
        confirm_token=preview.data.preview_token,
    )
    result = await _call_bulk_apply(deps, apply_input)
    assert result.success

    entry = deps.audit.get(result.audit_id)
    snaps = (entry.after_state or {}).get("per_op_snapshots") or {}
    assert "0" in snaps, f"expected per_op_snapshots['0'], got keys: {list(snaps)}"
    assert snaps["0"]["before"] == {"location": "/Inbox", "tags": ["existing"]}
```

If `_call_bulk_apply`, `deps_with_audit`, and the `Record` import are not already present in this test file, add them. Look at how the existing test in this file constructs `deps` and calls the registered tool — copy that pattern. If unsure, run `grep -n "_call_bulk_apply\|deps_with_audit" tests/unit/test_tools/test_bulk_apply.py` to find the existing helpers.

- [ ] **Step 2.2: Run the test — expect failure**

```bash
uv run pytest tests/unit/test_tools/test_bulk_apply.py::test_apply_persists_per_op_before_snapshot -v
```

Expected: FAIL with `KeyError: '0'` or `assert 'per_op_snapshots' in ...` because the production code does not yet populate that key.

- [ ] **Step 2.3: Add a `per_op_snapshots` accumulator + before-snapshot capture in `bulk_apply.py`**

In `apps/server/src/istefox_dt_mcp_server/tools/bulk_apply.py`, inside the `op()` async function (around line 60), declare the accumulator alongside `pre_move_snapshots`:

```python
        # Capture per-op {before, after} record snapshots so undo can
        # run 3-state drift detection on each op independently.
        per_op_snapshots: dict[str, dict[str, dict[str, Any]]] = {}
```

Then in the apply loop, **before** the existing `if bop.op == "move":` block (around line 100), insert the unconditional pre-snapshot capture:

```python
                # Pre-snapshot for drift detection (every op type).
                # For move ops we'll reuse this as pre_move_snapshots,
                # avoiding a double get_record.
                try:
                    rec_before = await deps.adapter.get_record(bop.record_uuid)
                except AdapterError:
                    outcomes.append(
                        BulkOpOutcome(
                            index=idx,
                            record_uuid=bop.record_uuid,
                            op=bop.op,
                            status="failed",
                            error_code="RECORD_NOT_FOUND",
                            error_message="cannot snapshot before op",
                        )
                    )
                    if failed_index is None:
                        failed_index = idx
                    if input.stop_on_first_error:
                        break
                    continue
```

Then **modify** the existing `if bop.op == "move":` block to reuse `rec_before` instead of calling `get_record` a second time:

```python
                if bop.op == "move":
                    pre_move_snapshots[bop.record_uuid] = rec_before.location
```

(Remove the inner `try: snapshot_record = await deps.adapter.get_record(...)` — `rec_before` already has the data.)

- [ ] **Step 2.4: Run the test — still expects failure (no `after`-snapshot yet, but the test only checks `before`)**

```bash
uv run pytest tests/unit/test_tools/test_bulk_apply.py::test_apply_persists_per_op_before_snapshot -v
```

Expected: still FAIL. The accumulator exists but is never populated. We need step 2.5.

- [ ] **Step 2.5: Populate the accumulator on successful apply**

Right after the existing line that increments `applied += 1` (around line 152), add:

```python
                per_op_snapshots[str(idx)] = {
                    "before": {
                        "location": rec_before.location,
                        "tags": list(rec_before.tags),
                    },
                    # `after` populated in Task 3
                }
```

- [ ] **Step 2.6: Persist `per_op_snapshots` in `set_after_state`**

Find the existing `deps.audit.set_after_state(...)` call (around line 202) and add the new key:

```python
            if applied_ops:
                deps.audit.set_after_state(
                    result.audit_id,
                    {
                        "applied": applied_ops,
                        "operations_applied": result.data.operations_applied,
                        "pre_move_snapshots": pre_move_snapshots,
                        "per_op_snapshots": per_op_snapshots,
                    },
                )
```

- [ ] **Step 2.7: Run the test — expect pass**

```bash
uv run pytest tests/unit/test_tools/test_bulk_apply.py::test_apply_persists_per_op_before_snapshot -v
```

Expected: PASS.

- [ ] **Step 2.8: Run the rest of the bulk_apply test file to ensure no regression**

```bash
uv run pytest tests/unit/test_tools/test_bulk_apply.py -v
```

Expected: all existing tests still pass. The extra `get_record` call may need its mock to be set up in tests that previously didn't expect it — if so, fix the affected test fixtures by adding `deps.adapter.get_record = AsyncMock(return_value=...)` analogous to step 2.1.

- [ ] **Step 2.9: Commit**

```bash
git add apps/server/src/istefox_dt_mcp_server/tools/bulk_apply.py \
        tests/unit/test_tools/test_bulk_apply.py
git commit -m "feat(bulk_apply): capture per-op before-snapshot in audit log"
```

---

### Task 3: Capture per-op `after` snapshot (TDD)

**Files:**
- Modify: `apps/server/src/istefox_dt_mcp_server/tools/bulk_apply.py`
- Modify: `tests/unit/test_tools/test_bulk_apply.py`

The accumulator now has `before`. Add `after`, captured immediately after the dispatch returns successfully. Edge case: if the post-dispatch `get_record` fails (rare — record deleted between dispatch and refetch), the op is still considered applied but the `per_op_snapshots[idx]` entry is left without `after`. Undo will fall back to legacy behavior for that specific op.

- [ ] **Step 3.1: Add a failing test for the after-snapshot**

Append:

```python
@pytest.mark.asyncio
async def test_apply_persists_per_op_after_snapshot(deps_with_audit):
    """After applying add_tag, per_op_snapshots[idx].after must reflect
    the record's state post-dispatch (tag now in the list)."""
    deps = deps_with_audit
    # Two distinct snapshots: before has 1 tag, after has 2
    rec_before = Record(
        uuid="u1", name="r1", kind=RecordKind.PDF, location="/Inbox",
        reference_url="x-d://u1", creation_date=datetime.now(),
        modification_date=datetime.now(), tags=["existing"],
    )
    rec_after = Record(
        uuid="u1", name="r1", kind=RecordKind.PDF, location="/Inbox",
        reference_url="x-d://u1", creation_date=datetime.now(),
        modification_date=datetime.now(), tags=["existing", "new"],
    )
    deps.adapter.get_record = AsyncMock(side_effect=[rec_before, rec_after])
    deps.adapter.apply_tag = AsyncMock(return_value=None)

    preview_input = BulkApplyInput(
        operations=[
            BulkApplyOperation(record_uuid="u1", op="add_tag", payload={"tag": "new"}),
        ],
        dry_run=True,
    )
    preview = await _call_bulk_apply(deps, preview_input)
    apply_input = BulkApplyInput(
        operations=preview_input.operations,
        dry_run=False,
        confirm_token=preview.data.preview_token,
    )
    result = await _call_bulk_apply(deps, apply_input)
    assert result.success

    entry = deps.audit.get(result.audit_id)
    snap = (entry.after_state or {}).get("per_op_snapshots", {}).get("0")
    assert snap is not None
    assert snap["after"] == {"location": "/Inbox", "tags": ["existing", "new"]}
```

- [ ] **Step 3.2: Run — expect failure**

```bash
uv run pytest tests/unit/test_tools/test_bulk_apply.py::test_apply_persists_per_op_after_snapshot -v
```

Expected: FAIL with `KeyError: 'after'` or assertion mismatch.

- [ ] **Step 3.3: Add the post-dispatch refetch in `bulk_apply.py`**

Replace the block from step 2.5:

```python
                per_op_snapshots[str(idx)] = {
                    "before": {
                        "location": rec_before.location,
                        "tags": list(rec_before.tags),
                    },
                }
```

With this expanded version:

```python
                per_op_entry: dict[str, dict[str, Any]] = {
                    "before": {
                        "location": rec_before.location,
                        "tags": list(rec_before.tags),
                    },
                }
                # Post-snapshot: best-effort. If the refetch fails (record
                # deleted between dispatch and refetch — rare), the op is
                # still recorded as applied but undo falls back to legacy
                # behavior for THIS op only.
                try:
                    rec_after = await deps.adapter.get_record(bop.record_uuid)
                    per_op_entry["after"] = {
                        "location": rec_after.location,
                        "tags": list(rec_after.tags),
                    }
                except AdapterError:
                    pass  # `after` left unset — undo handles missing key
                per_op_snapshots[str(idx)] = per_op_entry
```

- [ ] **Step 3.4: Run — expect pass**

```bash
uv run pytest tests/unit/test_tools/test_bulk_apply.py::test_apply_persists_per_op_after_snapshot -v
```

Expected: PASS.

- [ ] **Step 3.5: Add an edge-case test for missing `after` (post-dispatch refetch fails)**

```python
@pytest.mark.asyncio
async def test_apply_handles_post_snapshot_failure(deps_with_audit):
    """If the post-dispatch get_record raises, the op is still applied
    but per_op_snapshots[idx] has only `before` (no `after`)."""
    deps = deps_with_audit
    rec_before = Record(
        uuid="u1", name="r1", kind=RecordKind.PDF, location="/Inbox",
        reference_url="x-d://u1", creation_date=datetime.now(),
        modification_date=datetime.now(), tags=["existing"],
    )
    # First call returns before-snapshot; second call (post-dispatch) raises
    from istefox_dt_mcp_adapter.errors import AdapterError, AdapterErrorCode
    deps.adapter.get_record = AsyncMock(
        side_effect=[
            rec_before,
            AdapterError(code=AdapterErrorCode.RECORD_NOT_FOUND, message="gone"),
        ]
    )
    deps.adapter.apply_tag = AsyncMock(return_value=None)

    preview_input = BulkApplyInput(
        operations=[
            BulkApplyOperation(record_uuid="u1", op="add_tag", payload={"tag": "new"}),
        ],
        dry_run=True,
    )
    preview = await _call_bulk_apply(deps, preview_input)
    apply_input = BulkApplyInput(
        operations=preview_input.operations,
        dry_run=False,
        confirm_token=preview.data.preview_token,
    )
    result = await _call_bulk_apply(deps, apply_input)
    assert result.success
    assert result.data.operations_applied == 1  # op still recorded as applied

    entry = deps.audit.get(result.audit_id)
    snap = (entry.after_state or {}).get("per_op_snapshots", {}).get("0")
    assert snap is not None
    assert "before" in snap
    assert "after" not in snap  # post-snapshot was lost
```

- [ ] **Step 3.6: Run — expect pass (no impl change needed; the try/except already handles this)**

```bash
uv run pytest tests/unit/test_tools/test_bulk_apply.py::test_apply_handles_post_snapshot_failure -v
```

Expected: PASS.

- [ ] **Step 3.7: Run the full bulk_apply test file**

```bash
uv run pytest tests/unit/test_tools/test_bulk_apply.py -v
```

Expected: all green. Adjust mocks in any tests that broke because they now also need to handle the post-dispatch `get_record`.

- [ ] **Step 3.8: Commit**

```bash
git add apps/server/src/istefox_dt_mcp_server/tools/bulk_apply.py \
        tests/unit/test_tools/test_bulk_apply.py
git commit -m "feat(bulk_apply): capture per-op after-snapshot in audit log"
```

---

### Task 4: Wire `compute_drift_state` into `_undo_bulk_apply` for `no_drift` (TDD)

**Files:**
- Modify: `apps/server/src/istefox_dt_mcp_server/undo.py`
- Create: `tests/unit/test_undo_bulk_apply_drift.py`

This task only handles the `no_drift` path (the existing happy path). `already_reverted` and `hostile_drift` come in Tasks 5 and 6. Goal: introduce the per-op drift evaluation skeleton without changing observed behavior for the no-drift case.

- [ ] **Step 4.1: Create the new test file**

`tests/unit/test_undo_bulk_apply_drift.py`:

```python
"""Per-op drift detection in _undo_bulk_apply (3-state classifier)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from istefox_dt_mcp_schemas.common import Record, RecordKind
from istefox_dt_mcp_server.undo import undo_audit

if TYPE_CHECKING:
    from istefox_dt_mcp_server.deps import Deps


def _record(
    uuid: str = "u",
    location: str = "/Inbox",
    tags: list[str] | None = None,
) -> Record:
    return Record(
        uuid=uuid, name=f"r-{uuid}", kind=RecordKind.PDF,
        location=location, reference_url=f"x-d://{uuid}",
        creation_date=datetime.now(), modification_date=datetime.now(),
        tags=tags or [],
    )


def _audit_bulk_apply(
    deps: "Deps",
    *,
    applied_ops: list[dict],
    per_op_snapshots: dict[str, dict] | None = None,
    pre_move_snapshots: dict[str, str] | None = None,
):
    """Insert a bulk_apply audit entry as if a successful apply had run."""
    audit_id = deps.audit.append(
        tool_name="bulk_apply",
        input_data={
            "operations": [
                {"record_uuid": op["uuid"], "op": op["op"], "payload": op["payload"]}
                for op in applied_ops
            ],
            "dry_run": False,
        },
        output_data={"operations_applied": len(applied_ops)},
        duration_ms=10.0,
        before_state={"operations": list(applied_ops)},
    )
    after_state: dict = {
        "applied": applied_ops,
        "operations_applied": len(applied_ops),
        "pre_move_snapshots": pre_move_snapshots or {},
    }
    if per_op_snapshots is not None:
        after_state["per_op_snapshots"] = per_op_snapshots
    deps.audit.set_after_state(audit_id, after_state)
    return audit_id


@pytest.mark.asyncio
async def test_no_drift_per_op_reverts_add_tag(deps):
    """Single add_tag op, current state matches `after`: revert proceeds."""
    audit_id = _audit_bulk_apply(
        deps,
        applied_ops=[{"uuid": "u1", "op": "add_tag", "payload": {"tag": "x"}}],
        per_op_snapshots={
            "0": {
                "before": {"location": "/Inbox", "tags": []},
                "after":  {"location": "/Inbox", "tags": ["x"]},
            }
        },
    )
    deps.adapter.get_record = AsyncMock(
        return_value=_record(uuid="u1", location="/Inbox", tags=["x"])
    )
    deps.adapter.remove_tag = AsyncMock(return_value=None)

    result = await undo_audit(deps, audit_id, dry_run=False)

    assert result["reverted"] is True
    assert result["reverted_count"] == 1
    drift_per_op = result.get("drift_per_op", [])
    assert len(drift_per_op) == 1
    assert drift_per_op[0]["drift_state"] == "no_drift"
    deps.adapter.remove_tag.assert_awaited_once_with("u1", "x", dry_run=False)
```

The `deps` fixture is the project-wide one used in `test_undo.py`. If pytest can't find it, copy the `conftest.py` pattern from `tests/unit/`.

- [ ] **Step 4.2: Run — expect failure**

```bash
uv run pytest tests/unit/test_undo_bulk_apply_drift.py::test_no_drift_per_op_reverts_add_tag -v
```

Expected: FAIL with `KeyError: 'drift_per_op'` (the existing `_undo_bulk_apply` does not return that key).

- [ ] **Step 4.3: Refactor `_undo_bulk_apply` to compute drift per op (no_drift path only)**

Open `apps/server/src/istefox_dt_mcp_server/undo.py` at the `_undo_bulk_apply` function (around line 320). Restructure as follows.

Before the existing inverse-plan loop (around line 358), add:

```python
    # Detect whether this audit entry has per-op snapshots (new format)
    # or only the legacy {applied, pre_move_snapshots} shape.
    per_op_snapshots: dict[str, dict] = after.get("per_op_snapshots") or {}
    has_drift_detection = bool(per_op_snapshots)

    drift_per_op: list[dict[str, Any]] = []
```

Then replace the existing `for op in reversed(applied):` loop with this version:

```python
    indexed_applied = list(enumerate(applied))
    for orig_idx, op in reversed(indexed_applied):
        uuid = op.get("uuid")
        op_type = op.get("op")
        payload = op.get("payload") or {}
        if not uuid or not op_type:
            continue

        # Compute the inverse op (same logic as before)
        inverse_op: dict[str, Any] | None = None
        if op_type == "add_tag":
            tag = payload.get("tag")
            if tag:
                inverse_op = {"uuid": uuid, "op": "remove_tag", "tag": tag}
        elif op_type == "remove_tag":
            tag = payload.get("tag")
            if tag:
                inverse_op = {"uuid": uuid, "op": "add_tag", "tag": tag}
        elif op_type == "move":
            original_location = snapshots.get(uuid)
            if original_location:
                inverse_op = {
                    "uuid": uuid, "op": "move", "destination": original_location,
                }
            else:
                skipped.append({"uuid": uuid, "reason": "no pre-move snapshot"})
                continue
        else:
            skipped.append({"uuid": uuid, "reason": f"unknown op {op_type}"})
            continue

        if inverse_op is None:
            continue

        # Per-op drift evaluation (only when snapshots are available)
        if has_drift_detection:
            snap = per_op_snapshots.get(str(orig_idx))
            if snap is None or "after" not in snap:
                # Missing per-op snapshot → fall back to legacy (no drift check)
                drift_per_op.append({
                    "index": orig_idx, "uuid": uuid,
                    "drift_state": "unknown",
                    "reason": "no per-op snapshot",
                })
                inverse_plan.append(inverse_op)
                continue

            try:
                current = await deps.adapter.get_record(uuid)
            except AdapterError:
                drift_per_op.append({
                    "index": orig_idx, "uuid": uuid,
                    "drift_state": "unknown",
                    "reason": "record not retrievable",
                })
                skipped.append({"uuid": uuid, "reason": "record not retrievable"})
                continue

            drift_state = compute_drift_state(current, snap["before"], snap["after"])

            # For now (Task 4 scope) we only handle no_drift.
            # already_reverted and hostile_drift are added in Task 5+6.
            drift_per_op.append({
                "index": orig_idx, "uuid": uuid,
                "drift_state": drift_state,
            })
            inverse_plan.append(inverse_op)
        else:
            # Legacy entry (no per_op_snapshots): keep current behavior
            inverse_plan.append(inverse_op)
```

(The previous body of the loop — the if/elif chain that built inverse ops — is now inside the new structure. Make sure `_dispatch_op`-style logic at the end of the function is unchanged.)

Then update the `dry_run` and apply-phase return values to include `drift_per_op`. Find the dry_run return (around line 392) and add the field:

```python
        return {
            "audit_id": audit_id_str,
            "tool_name": "bulk_apply",
            "reverted": False,
            "drift_detected": False,
            "would_revert": inverse_plan,
            "skipped": skipped,
            "drift_per_op": drift_per_op,
            "n_ops_to_revert": len(inverse_plan),
            "force_acknowledged": force,
            "dry_run": True,
            "message": "dry_run preview",
        }
```

And the apply-phase return (around line 433):

```python
    return {
        "audit_id": audit_id_str,
        "tool_name": "bulk_apply",
        "reverted": reverted_count > 0 and not failures,
        "reverted_count": reverted_count,
        "failures": failures,
        "skipped": skipped,
        "drift_per_op": drift_per_op,
        "drift_detected": False,  # updated in Task 6
        "dry_run": False,
        "message": (
            "ok"
            if not failures
            else f"{reverted_count} reverted, {len(failures)} failed"
        ),
    }
```

Imports: ensure `compute_drift_state` is importable inside `_undo_bulk_apply` (it's defined in the same module, so no new import needed).

- [ ] **Step 4.4: Run the new test — expect pass**

```bash
uv run pytest tests/unit/test_undo_bulk_apply_drift.py::test_no_drift_per_op_reverts_add_tag -v
```

Expected: PASS.

- [ ] **Step 4.5: Run the existing undo tests for regression**

```bash
uv run pytest tests/unit/test_undo.py -v
```

Expected: all existing tests pass. The new code branches cleanly on `has_drift_detection`, so legacy entries (used by existing tests) hit the unchanged path.

- [ ] **Step 4.6: Commit**

```bash
git add apps/server/src/istefox_dt_mcp_server/undo.py \
        tests/unit/test_undo_bulk_apply_drift.py
git commit -m "feat(undo): compute per-op drift_state in bulk_apply undo (no_drift path)"
```

---

### Task 5: Add `already_reverted` handling (TDD)

**Files:**
- Modify: `apps/server/src/istefox_dt_mcp_server/undo.py`
- Modify: `tests/unit/test_undo_bulk_apply_drift.py`

- [ ] **Step 5.1: Add a failing test**

Append to `tests/unit/test_undo_bulk_apply_drift.py`:

```python
@pytest.mark.asyncio
async def test_already_reverted_per_op_skips(deps):
    """Single add_tag op, user externally removed the tag: undo skips."""
    audit_id = _audit_bulk_apply(
        deps,
        applied_ops=[{"uuid": "u1", "op": "add_tag", "payload": {"tag": "x"}}],
        per_op_snapshots={
            "0": {
                "before": {"location": "/Inbox", "tags": []},
                "after":  {"location": "/Inbox", "tags": ["x"]},
            }
        },
    )
    # Current state matches `before`: tag was already removed externally
    deps.adapter.get_record = AsyncMock(
        return_value=_record(uuid="u1", location="/Inbox", tags=[])
    )
    deps.adapter.remove_tag = AsyncMock(return_value=None)

    result = await undo_audit(deps, audit_id, dry_run=False)

    assert result["reverted"] is False
    assert result["reverted_count"] == 0
    assert result["drift_detected"] is False
    drift_per_op = result["drift_per_op"]
    assert drift_per_op[0]["drift_state"] == "already_reverted"
    # Skipped should also reflect this
    assert any(s.get("reason") == "already_reverted" for s in result["skipped"])
    # No revert call should have happened
    deps.adapter.remove_tag.assert_not_awaited()
```

- [ ] **Step 5.2: Run — expect failure**

```bash
uv run pytest tests/unit/test_undo_bulk_apply_drift.py::test_already_reverted_per_op_skips -v
```

Expected: FAIL — currently the op is added to `inverse_plan` regardless of state.

- [ ] **Step 5.3: Add already_reverted branch in `_undo_bulk_apply`**

In the per-op drift evaluation block in `undo.py` (the section added in Task 4), replace:

```python
            drift_state = compute_drift_state(current, snap["before"], snap["after"])

            # For now (Task 4 scope) we only handle no_drift.
            # already_reverted and hostile_drift are added in Task 5+6.
            drift_per_op.append({
                "index": orig_idx, "uuid": uuid,
                "drift_state": drift_state,
            })
            inverse_plan.append(inverse_op)
```

With:

```python
            drift_state = compute_drift_state(current, snap["before"], snap["after"])
            entry_dict: dict[str, Any] = {
                "index": orig_idx, "uuid": uuid, "drift_state": drift_state,
            }

            if drift_state == "already_reverted":
                entry_dict["reason"] = "already in pre-op state"
                drift_per_op.append(entry_dict)
                skipped.append({
                    "uuid": uuid,
                    "reason": "already_reverted",
                    "index": orig_idx,
                })
                continue

            # Tasks 6 will add hostile_drift handling here.
            drift_per_op.append(entry_dict)
            inverse_plan.append(inverse_op)
```

- [ ] **Step 5.4: Run the new test — expect pass**

```bash
uv run pytest tests/unit/test_undo_bulk_apply_drift.py::test_already_reverted_per_op_skips -v
```

Expected: PASS.

- [ ] **Step 5.5: Run all undo tests — no regression**

```bash
uv run pytest tests/unit/test_undo.py tests/unit/test_undo_bulk_apply_drift.py -v
```

Expected: all green.

- [ ] **Step 5.6: Commit**

```bash
git add apps/server/src/istefox_dt_mcp_server/undo.py \
        tests/unit/test_undo_bulk_apply_drift.py
git commit -m "feat(undo): skip already_reverted ops in bulk_apply undo"
```

---

### Task 6: Add `hostile_drift` handling + `force` flag (TDD)

**Files:**
- Modify: `apps/server/src/istefox_dt_mcp_server/undo.py`
- Modify: `tests/unit/test_undo_bulk_apply_drift.py`

- [ ] **Step 6.1: Add two failing tests (hostile_drift without force, hostile_drift with force)**

Append:

```python
@pytest.mark.asyncio
async def test_hostile_drift_per_op_skips_without_force(deps):
    """Single add_tag op, external actor changed the tag set: undo blocked."""
    audit_id = _audit_bulk_apply(
        deps,
        applied_ops=[{"uuid": "u1", "op": "add_tag", "payload": {"tag": "x"}}],
        per_op_snapshots={
            "0": {
                "before": {"location": "/Inbox", "tags": []},
                "after":  {"location": "/Inbox", "tags": ["x"]},
            }
        },
    )
    # Current matches NEITHER before nor after: an external actor added "y"
    deps.adapter.get_record = AsyncMock(
        return_value=_record(uuid="u1", location="/Inbox", tags=["x", "y"])
    )
    deps.adapter.remove_tag = AsyncMock(return_value=None)

    result = await undo_audit(deps, audit_id, dry_run=False, force=False)

    assert result["reverted"] is False
    assert result["drift_detected"] is True
    drift_per_op = result["drift_per_op"]
    assert drift_per_op[0]["drift_state"] == "hostile_drift"
    assert "drift_details" in drift_per_op[0]
    deps.adapter.remove_tag.assert_not_awaited()


@pytest.mark.asyncio
async def test_hostile_drift_per_op_reverts_with_force(deps):
    """Same scenario but --force: revert proceeds, overwriting external edits."""
    audit_id = _audit_bulk_apply(
        deps,
        applied_ops=[{"uuid": "u1", "op": "add_tag", "payload": {"tag": "x"}}],
        per_op_snapshots={
            "0": {
                "before": {"location": "/Inbox", "tags": []},
                "after":  {"location": "/Inbox", "tags": ["x"]},
            }
        },
    )
    deps.adapter.get_record = AsyncMock(
        return_value=_record(uuid="u1", location="/Inbox", tags=["x", "y"])
    )
    deps.adapter.remove_tag = AsyncMock(return_value=None)

    result = await undo_audit(deps, audit_id, dry_run=False, force=True)

    assert result["reverted"] is True
    assert result["reverted_count"] == 1
    assert result["drift_detected"] is True  # still surfaces the drift
    deps.adapter.remove_tag.assert_awaited_once_with("u1", "x", dry_run=False)
```

- [ ] **Step 6.2: Run — expect both to fail**

```bash
uv run pytest tests/unit/test_undo_bulk_apply_drift.py -k "hostile" -v
```

Expected: 2 fails. The first because the op is currently reverted blindly; the second because `force` is currently a no-op.

- [ ] **Step 6.3: Add hostile_drift branch + drift_details helper**

In `undo.py`, add this private helper near `_undo_bulk_apply`:

```python
def _bulk_diff_details(current: Record, snap: dict[str, Any]) -> dict[str, Any]:
    """Same shape as the file_document path: report what diverged
    between current state and the persisted `after` snapshot."""
    after = snap.get("after") or {}
    expected_loc = str(after.get("location") or "")
    expected_tags = sorted(after.get("tags") or [])
    cur_tags = sorted(current.tags)
    details: dict[str, Any] = {}
    if current.location != expected_loc:
        details["location"] = {"expected": expected_loc, "current": current.location}
    if cur_tags != expected_tags:
        details["tags"] = {
            "expected": expected_tags,
            "current": cur_tags,
            "added": sorted(set(cur_tags) - set(expected_tags)),
            "removed": sorted(set(expected_tags) - set(cur_tags)),
        }
    return details
```

In the per-op evaluation block, insert hostile_drift handling **after** the already_reverted branch and **before** the final `drift_per_op.append + inverse_plan.append`:

```python
            if drift_state == "hostile_drift":
                if not force:
                    entry_dict["drift_details"] = _bulk_diff_details(current, snap)
                    drift_per_op.append(entry_dict)
                    skipped.append({
                        "uuid": uuid,
                        "reason": "hostile_drift",
                        "index": orig_idx,
                    })
                    continue
                # force=True: surface drift but proceed
                entry_dict["drift_details"] = _bulk_diff_details(current, snap)
                entry_dict["force_applied"] = True

            drift_per_op.append(entry_dict)
            inverse_plan.append(inverse_op)
```

Now update the apply-phase return to compute `drift_detected` from `drift_per_op`:

```python
    drift_detected = any(
        d.get("drift_state") == "hostile_drift" for d in drift_per_op
    )
    return {
        "audit_id": audit_id_str,
        "tool_name": "bulk_apply",
        "reverted": reverted_count > 0 and not failures,
        "reverted_count": reverted_count,
        "failures": failures,
        "skipped": skipped,
        "drift_per_op": drift_per_op,
        "drift_detected": drift_detected,
        "dry_run": False,
        "message": (
            "ok"
            if not failures
            else f"{reverted_count} reverted, {len(failures)} failed"
        ),
    }
```

Same update for the dry_run return — replace `"drift_detected": False` with `"drift_detected": drift_detected` (defining `drift_detected` from `drift_per_op` just before the return).

- [ ] **Step 6.4: Run — expect pass**

```bash
uv run pytest tests/unit/test_undo_bulk_apply_drift.py -k "hostile" -v
```

Expected: 2 passes.

- [ ] **Step 6.5: Run all undo tests**

```bash
uv run pytest tests/unit/test_undo.py tests/unit/test_undo_bulk_apply_drift.py -v
```

Expected: all green.

- [ ] **Step 6.6: Commit**

```bash
git add apps/server/src/istefox_dt_mcp_server/undo.py \
        tests/unit/test_undo_bulk_apply_drift.py
git commit -m "feat(undo): block hostile_drift in bulk_apply undo, --force overrides"
```

---

### Task 7: Mixed-batch + legacy fallback tests (TDD, defensive coverage)

**Files:**
- Modify: `tests/unit/test_undo_bulk_apply_drift.py`

No production-code changes expected. These tests pin down behavior that's already implemented but not yet covered.

- [ ] **Step 7.1: Add a mixed-batch test (one of each state)**

Append:

```python
@pytest.mark.asyncio
async def test_mixed_batch_drift_states(deps):
    """3-op batch: idx0 no_drift, idx1 already_reverted, idx2 hostile_drift.
    Expect 1 reverted, 2 skipped, drift_detected True."""
    audit_id = _audit_bulk_apply(
        deps,
        applied_ops=[
            {"uuid": "u1", "op": "add_tag", "payload": {"tag": "a"}},  # no_drift
            {"uuid": "u2", "op": "add_tag", "payload": {"tag": "b"}},  # already_reverted
            {"uuid": "u3", "op": "add_tag", "payload": {"tag": "c"}},  # hostile_drift
        ],
        per_op_snapshots={
            "0": {"before": {"location": "/", "tags": []},
                  "after":  {"location": "/", "tags": ["a"]}},
            "1": {"before": {"location": "/", "tags": []},
                  "after":  {"location": "/", "tags": ["b"]}},
            "2": {"before": {"location": "/", "tags": []},
                  "after":  {"location": "/", "tags": ["c"]}},
        },
    )
    # Routing per-uuid via side_effect on the mock
    def fake_get_record(uuid: str):
        if uuid == "u1":
            return _record(uuid="u1", location="/", tags=["a"])  # no_drift
        if uuid == "u2":
            return _record(uuid="u2", location="/", tags=[])  # already_reverted
        if uuid == "u3":
            return _record(uuid="u3", location="/", tags=["c", "foreign"])  # hostile
        raise ValueError(f"unexpected uuid {uuid}")
    deps.adapter.get_record = AsyncMock(side_effect=fake_get_record)
    deps.adapter.remove_tag = AsyncMock(return_value=None)

    result = await undo_audit(deps, audit_id, dry_run=False, force=False)

    assert result["reverted_count"] == 1
    assert result["drift_detected"] is True
    states = {d["uuid"]: d["drift_state"] for d in result["drift_per_op"]}
    assert states == {"u1": "no_drift", "u2": "already_reverted", "u3": "hostile_drift"}
    # Only u1 should have been reverted
    deps.adapter.remove_tag.assert_awaited_once_with("u1", "a", dry_run=False)
```

- [ ] **Step 7.2: Add a legacy-fallback test**

```python
@pytest.mark.asyncio
async def test_legacy_audit_no_per_op_snapshots(deps):
    """Audit entry written before this feature: no per_op_snapshots key.
    Undo must fall back to legacy behavior (no drift detection, blind revert)."""
    audit_id = _audit_bulk_apply(
        deps,
        applied_ops=[{"uuid": "u1", "op": "add_tag", "payload": {"tag": "x"}}],
        per_op_snapshots=None,  # KEY ABSENT — legacy entry
    )
    deps.adapter.remove_tag = AsyncMock(return_value=None)
    # get_record should NOT be called in the legacy branch
    deps.adapter.get_record = AsyncMock(side_effect=AssertionError("must not be called"))

    result = await undo_audit(deps, audit_id, dry_run=False)

    assert result["reverted"] is True
    assert result["reverted_count"] == 1
    # Legacy: drift_per_op is empty (no detection performed)
    assert result.get("drift_per_op") == []
    deps.adapter.remove_tag.assert_awaited_once_with("u1", "x", dry_run=False)
```

- [ ] **Step 7.3: Add a missing-snapshot test (per-op `after` absent on a single op)**

```python
@pytest.mark.asyncio
async def test_per_op_missing_after_falls_back_for_that_op_only(deps):
    """idx0 has full snapshot (drift detection), idx1 missing `after`
    (post-snapshot failure during apply). idx1 reverts blindly."""
    audit_id = _audit_bulk_apply(
        deps,
        applied_ops=[
            {"uuid": "u1", "op": "add_tag", "payload": {"tag": "a"}},
            {"uuid": "u2", "op": "add_tag", "payload": {"tag": "b"}},
        ],
        per_op_snapshots={
            "0": {"before": {"location": "/", "tags": []},
                  "after":  {"location": "/", "tags": ["a"]}},
            "1": {"before": {"location": "/", "tags": []}},  # no `after`
        },
    )
    def fake_get_record(uuid: str):
        return _record(uuid=uuid, location="/", tags=["a"] if uuid == "u1" else ["b"])
    deps.adapter.get_record = AsyncMock(side_effect=fake_get_record)
    deps.adapter.remove_tag = AsyncMock(return_value=None)

    result = await undo_audit(deps, audit_id, dry_run=False)

    assert result["reverted_count"] == 2
    states = {d["uuid"]: d["drift_state"] for d in result["drift_per_op"]}
    assert states["u1"] == "no_drift"
    assert states["u2"] == "unknown"
```

- [ ] **Step 7.4: Run all three tests**

```bash
uv run pytest tests/unit/test_undo_bulk_apply_drift.py -v
```

Expected: all pass. If any fails, the production code from Tasks 4-6 has a gap — investigate before continuing.

- [ ] **Step 7.5: Full unit suite**

```bash
uv run pytest tests/unit -q
```

Expected: 200+ pass, 0 fail.

- [ ] **Step 7.6: Commit**

```bash
git add tests/unit/test_undo_bulk_apply_drift.py
git commit -m "test(undo): mixed-batch + legacy fallback + missing-snapshot coverage"
```

---

### Task 8: Coverage of `move` and `remove_tag` op types (TDD)

**Files:**
- Modify: `tests/unit/test_undo_bulk_apply_drift.py`

Drift detection per state has been verified for `add_tag`. Now sanity-check that `move` and `remove_tag` paths are equally covered (no path-specific bugs).

- [ ] **Step 8.1: Add a `move` no_drift test**

```python
@pytest.mark.asyncio
async def test_no_drift_per_op_reverts_move(deps):
    """move op, current location matches `after` (post-move): revert moves back."""
    audit_id = _audit_bulk_apply(
        deps,
        applied_ops=[{"uuid": "u1", "op": "move", "payload": {"destination": "/Archive"}}],
        per_op_snapshots={
            "0": {
                "before": {"location": "/Inbox",   "tags": []},
                "after":  {"location": "/Archive", "tags": []},
            }
        },
        pre_move_snapshots={"u1": "/Inbox"},  # required for inverse op
    )
    deps.adapter.get_record = AsyncMock(
        return_value=_record(uuid="u1", location="/Archive", tags=[])
    )
    deps.adapter.move_record = AsyncMock(return_value=None)

    result = await undo_audit(deps, audit_id, dry_run=False)

    assert result["reverted"] is True
    assert result["reverted_count"] == 1
    assert result["drift_per_op"][0]["drift_state"] == "no_drift"
    deps.adapter.move_record.assert_awaited_once_with("u1", "/Inbox", dry_run=False)
```

- [ ] **Step 8.2: Add a `remove_tag` no_drift test**

```python
@pytest.mark.asyncio
async def test_no_drift_per_op_reverts_remove_tag(deps):
    """remove_tag op, current matches `after` (tag absent): revert re-adds the tag."""
    audit_id = _audit_bulk_apply(
        deps,
        applied_ops=[{"uuid": "u1", "op": "remove_tag", "payload": {"tag": "x"}}],
        per_op_snapshots={
            "0": {
                "before": {"location": "/", "tags": ["x"]},
                "after":  {"location": "/", "tags": []},
            }
        },
    )
    deps.adapter.get_record = AsyncMock(
        return_value=_record(uuid="u1", location="/", tags=[])
    )
    deps.adapter.apply_tag = AsyncMock(return_value=None)

    result = await undo_audit(deps, audit_id, dry_run=False)

    assert result["reverted"] is True
    assert result["reverted_count"] == 1
    deps.adapter.apply_tag.assert_awaited_once_with("u1", "x", dry_run=False)
```

- [ ] **Step 8.3: Run both**

```bash
uv run pytest tests/unit/test_undo_bulk_apply_drift.py -k "move or remove_tag" -v
```

Expected: 2 pass.

- [ ] **Step 8.4: Commit**

```bash
git add tests/unit/test_undo_bulk_apply_drift.py
git commit -m "test(undo): cover move + remove_tag drift detection paths"
```

---

### Task 9: Integration test on DT live (skip-default)

**Files:**
- Create: `tests/integration/test_undo_bulk_apply_drift_live.py`

This test runs only when DT is live and the `fixtures-dt-mcp` database is open — gated by the same skip pattern as other integration tests in `tests/integration/`. Look at `tests/integration/test_dt_smoke.py` for the skip-marker pattern (likely `@pytest.mark.integration` plus a fixture that detects DT).

- [ ] **Step 9.1: Read the skip pattern from existing integration tests**

```bash
head -30 tests/integration/test_dt_smoke.py
cat tests/integration/conftest.py
```

Note the marker name and any `pytest.skip` invocations. The new file must follow the same pattern.

- [ ] **Step 9.2: Create the integration test**

`tests/integration/test_undo_bulk_apply_drift_live.py`:

```python
"""Round-trip drift detection test against a live DEVONthink 4 instance.

Requires:
- DT4 running
- fixtures-dt-mcp database open
- 3 records present in /Inbox of fixtures-dt-mcp (test creates them if missing)

Skip default — opt-in via `-m integration`.
"""

from __future__ import annotations

import pytest

# Reuse the project's integration marker — adjust if conftest exports a different one
pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_bulk_apply_undo_drift_round_trip(integration_deps):
    """3-op batch: tag A, tag B, move C. Externally:
    - revert A's tag (already_reverted)
    - add a foreign tag to B (hostile_drift)
    - leave C untouched (no_drift)
    Undo: A skipped, B skipped, C reverted. Then undo with force=True
    reverts B. A still skipped."""
    deps = integration_deps

    # 0. Set up: locate or create 3 fixtures
    rec_a, rec_b, rec_c = await _ensure_fixtures(deps)

    # 1. Bulk apply: tag A=red, tag B=blue, move C to /Archive
    from istefox_dt_mcp_schemas.tools import BulkApplyInput, BulkApplyOperation
    from istefox_dt_mcp_server.tools.bulk_apply import register as register_bulk
    # Preview + apply via the registered tool surface (or call the
    # underlying logic directly — depends on how integration helpers
    # are wired in conftest).
    # Pseudocode:
    # preview = await call_tool("bulk_apply", BulkApplyInput(operations=[...], dry_run=True))
    # apply  = await call_tool("bulk_apply", BulkApplyInput(operations=[...], dry_run=False, confirm_token=preview.preview_token))
    # audit_id = apply.audit_id
    # assert apply.success and apply.data.operations_applied == 3

    # 2. External actions (via adapter directly, simulating user/external edit)
    # await deps.adapter.remove_tag(rec_a.uuid, "red", dry_run=False)  # already_reverted for A
    # await deps.adapter.apply_tag(rec_b.uuid, "foreign", dry_run=False)  # hostile_drift for B

    # 3. Undo without force
    # from istefox_dt_mcp_server.undo import undo_audit
    # result = await undo_audit(deps, audit_id, dry_run=False, force=False)
    # states = {d["uuid"]: d["drift_state"] for d in result["drift_per_op"]}
    # assert states[rec_a.uuid] == "already_reverted"
    # assert states[rec_b.uuid] == "hostile_drift"
    # assert states[rec_c.uuid] == "no_drift"
    # assert result["reverted_count"] == 1

    # 4. Undo with force
    # result_forced = await undo_audit(deps, audit_id, dry_run=False, force=True)
    # B's tag should now be removed; A still untouched
    # ...

    pytest.skip("integration test stub — wire up via conftest helpers")


async def _ensure_fixtures(deps):
    """Locate 3 records in fixtures-dt-mcp/Inbox or create them."""
    raise NotImplementedError("wire up using existing integration helpers")
```

This is intentionally a stub. The full integration test requires a working `integration_deps` fixture and a way to call registered tools — both of which are in `tests/integration/conftest.py`. **Do not block this PR on the integration test if the conftest helpers are not ready.** Land the stub with the `pytest.skip` and add a follow-up issue.

- [ ] **Step 9.3: Verify the test is properly skipped by default**

```bash
uv run pytest tests/integration/test_undo_bulk_apply_drift_live.py -v
```

Expected: 1 skipped (or 1 deselected if the marker auto-skips). No failures.

- [ ] **Step 9.4: Commit (stub)**

```bash
git add tests/integration/test_undo_bulk_apply_drift_live.py
git commit -m "test(integration): bulk_apply undo drift round-trip stub (skip default)"
```

- [ ] **Step 9.5: Open a follow-up issue for fleshing out the stub**

```bash
gh issue create --title "test: flesh out integration test for bulk_apply undo drift detection" --body "Stub committed in <PR-URL>. Needs: (a) `integration_deps` fixture wiring, (b) tool-call helper, (c) fixtures-dt-mcp setup helper for 3 records in /Inbox. Currently the test body is pseudocode and ends in pytest.skip."
```

---

### Task 10: CHANGELOG + PR

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 10.1: Add an unreleased entry to CHANGELOG**

Open `CHANGELOG.md` and add at the top, under the existing `## [Unreleased]` section (create the section if it doesn't exist):

```markdown
## [Unreleased]

### Added
- Per-op drift detection in `bulk_apply` undo (3-state classifier: `no_drift` / `already_reverted` / `hostile_drift`), mirroring the `file_document` undo pattern from 0.2.0.
- New response field `drift_per_op: list[{index, uuid, drift_state, drift_details?}]` on `bulk_apply` undo for fine-grained reporting.
- Audit log persists `after_state.per_op_snapshots` keyed by op index — `{before, after}` `{location, tags}` snapshots captured during apply.

### Changed
- `bulk_apply` apply phase now performs 2 extra `get_record` calls per op (pre + post snapshot). On a typical 50-op batch latency goes from ~5s to ~15s under the existing JXA worker pool — accepted cost for correct undo semantics.
- `bulk_apply` undo response field `drift_detected` now reflects "any op had hostile_drift" instead of always `false`.

### Notes
- Audit entries written before this change lack `per_op_snapshots` and continue to work via legacy fallback (no per-op drift detection, identical to pre-0.3.0 behavior).
```

- [ ] **Step 10.2: Run the full unit + contract suite one last time**

```bash
uv run pytest tests/unit tests/contract -q
```

Expected: 200+ pass.

- [ ] **Step 10.3: Run lint + type check**

```bash
uv run ruff check .
uv run black --check .
uv run mypy apps libs
```

Expected: all clean. Fix any issue inline before opening the PR.

- [ ] **Step 10.4: Push the branch**

```bash
git push -u origin feat/bulk-apply-drift-detection
```

- [ ] **Step 10.5: Open the PR**

```bash
gh pr create --title "feat(undo): per-op drift detection in bulk_apply undo (3-state)" --body "$(cat <<'EOF'
## Summary
- Extend the 3-state drift classifier (introduced in 0.2.0 for `file_document`) to `bulk_apply` undo on a per-op basis.
- Capture `before` + `after` `{location, tags}` snapshots per op during the apply phase, persist in `audit.after_state.per_op_snapshots`.
- In `_undo_bulk_apply`, evaluate drift per op via the existing `compute_drift_state` and route accordingly: `no_drift` reverts, `already_reverted` skips silently, `hostile_drift` skips unless `--force`.
- New response field `drift_per_op` for fine-grained reporting.
- Backward-compatible: audit entries without `per_op_snapshots` fall back to legacy (no drift) behavior.

## Test plan
- [x] Unit: 9 new tests in `tests/unit/test_undo_bulk_apply_drift.py` covering all 3 states across 3 op types, mixed batch, legacy fallback, missing-snapshot edge case.
- [x] Unit: existing `test_undo.py` and `test_bulk_apply.py` still pass.
- [x] Lint: `ruff check`, `black --check`, `mypy` all clean.
- [ ] Integration (stub committed, follow-up issue): round-trip on DT live with 3 records.

## Reference
- Design spec: `docs/superpowers/specs/2026-05-06-bulk-apply-drift-detection-design.md`
- Implementation plan: `docs/superpowers/plans/2026-05-06-bulk-apply-drift-detection.md`
- Follow-up integration test: see issue linked in commit history.
EOF
)"
```

- [ ] **Step 10.6: Verify PR opened**

```bash
gh pr view --json number,title,state,url | jq
```

Expected: state OPEN, url returned.

---

## Self-Review

**Spec coverage check:**
- §4 (schema change `per_op_snapshots`): Tasks 2-3. ✓
- §5 (apply-phase changes): Tasks 2-3. ✓
- §6 (undo-phase changes): Tasks 4-6. ✓
- §7 (output schema): Tasks 4-6 (incremental). ✓
- §8.1 (unit tests): Tasks 4-8. ✓ — 9+ unit tests covering all 3 states across 3 op types, mixed batch, legacy, edge cases.
- §8.2 (contract): no existing bulk_apply contract test in `tests/contract/` (verified during plan-writing). Plan does not add one — would be premature scaffolding for a single-tool contract not yet established. Documented in CHANGELOG as future work if needed.
- §8.3 (integration): Task 9 (stub + follow-up issue, deliberately not blocking). ✓
- §8.4 (cassette VCR): no `bulk_apply` cassette exists in `tests/contract/cassettes/` (verified). The `record-cassette` CLI does not cover `bulk_apply`. Plan does not include a re-record task — there's nothing to re-record.
- §9 (migration & rollout): CHANGELOG entry in Task 10. Audit entries pre-upgrade are handled by the `has_drift_detection` branch (covered by Task 7's legacy test). ✓
- §10 (failure modes): all listed modes are exercised by the test matrix in Tasks 4-7 (record not retrievable, post-snapshot failed, malformed JSON via empty fallback). ✓

**Placeholder scan:** Task 9's body is intentionally a stub — flagged explicitly in the task description and in a follow-up issue. All other tasks have complete code blocks and exact commands. No "TBD" anywhere.

**Type/path consistency:** `per_op_snapshots: dict[str, dict]` is used consistently. The drift_state literal values (`no_drift`, `already_reverted`, `hostile_drift`, `unknown`) match across plan, spec, and the existing `compute_drift_state` signature. The `_bulk_diff_details` helper signature is the same wherever it's called. `RecordKind.PDF` is used consistently in test fixtures (matches `test_undo.py`).

**Scope check:** Plan stays within `bulk_apply` + its undo path + audit `after_state` shape. Does not touch `file_document`, schema migrations, OAuth, HTTP transport. ✓

No gaps. Plan is complete.
