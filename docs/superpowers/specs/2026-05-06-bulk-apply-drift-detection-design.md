# Bulk Apply Per-Op Drift Detection — Design Spec

- **Status**: proposed 2026-05-06
- **Target version**: 0.3.0
- **Owner**: istefox
- **Scope**: `bulk_apply` tool (apply phase) + `_undo_bulk_apply` (undo path) + audit `after_state` schema
- **Out of scope**: SQL migration of historical audit rows, drift detection in `bulk_apply` preview phase, cassette re-record beyond what's needed for tests

---

## 1. Context

PR #43 (landed in 0.2.0) introduced 3-state drift detection for `undo` of `file_document` audit entries. The classifier is in `apps/server/src/istefox_dt_mcp_server/undo.py::compute_drift_state` and distinguishes:

- `no_drift` — current DT state matches `after_state`. Revert proceeds.
- `already_reverted` — current matches `before_state`. Revert is a no-op.
- `hostile_drift` — current matches neither. Revert blocked unless `--force`.

`_undo_bulk_apply` (same file, line 320+) was **explicitly left out** of the refactor. Its docstring (line 339) states: *"`force` is currently a no-op for bulk undo (per-op drift detection is post-MVP — the audit_after_state doesn't have per-op after-snapshots)"*.

Today every bulk undo:
- Returns `drift_detected: False` unconditionally.
- Reverts every applied op blindly. If a record was externally modified after the bulk apply, the undo silently overwrites that modification.
- Cannot distinguish "user already restored this op" from "external actor changed the record" — exactly the same false-positive collapse PR #43 fixed for `file_document`.

This spec extends the same 3-state semantics to `bulk_apply`, on a per-op basis.

## 2. Goals

- For each op in a bulk undo, compute `drift_state ∈ {no_drift, already_reverted, hostile_drift}` independently.
- Skip ops with `already_reverted` (no-op; already in pre-apply state).
- Skip ops with `hostile_drift` unless `--force` is passed; surface what diverged in `drift_details`.
- Apply ops with `no_drift` (current behavior path).
- Output a per-op breakdown (`drift_per_op`) so the caller can see exactly what happened.
- Reuse `compute_drift_state` from `undo.py` — single source of truth for the classifier.
- Backward-compatible with audit entries written before this change.

## 3. Non-goals

- Migrating legacy bulk audit entries to the new schema. Pre-upgrade entries fall back to current behavior (no per-op drift detection).
- Drift detection in the `bulk_apply` preview phase (`dry_run=true`). The preview validates op shape only; no DT state to compare against.
- New SQL columns. `before_state` / `after_state` are already JSON blobs — only the inner structure changes.
- Per-op latency optimization. Extra `get_record` calls are accepted as cost.
- Unifying `file_document` and `bulk_apply` audit schemas. Two separate shapes, one shared classifier function.

## 4. Schema change: `after_state.per_op_snapshots`

Today (`bulk_apply.py:184-209`), after a successful apply, `after_state` has shape:

```json
{
  "applied": [
    {"uuid": "...", "op": "add_tag", "payload": {"tag": "x"}},
    ...
  ],
  "operations_applied": N,
  "pre_move_snapshots": {"<uuid>": "<location>", ...}
}
```

After the change, `after_state` adds a new key:

```json
{
  "applied": [...],
  "operations_applied": N,
  "pre_move_snapshots": {...},
  "per_op_snapshots": {
    "0": {
      "before": {"location": "...", "tags": ["a", "b"]},
      "after":  {"location": "...", "tags": ["a", "b", "x"]}
    },
    "1": {...}
  }
}
```

**Indexed by string-formatted op index**, not by uuid. Rationale: the same uuid can appear multiple times in a single batch (e.g., `add_tag X` then `add_tag Y` on the same record). Index is the only stable per-op key.

`pre_move_snapshots` is **kept as-is** for backward compat and because it carries the location pre-move keyed by uuid (used to compute the inverse `move`). `per_op_snapshots[idx].before.location` will duplicate this for `move` ops. Acceptable redundancy: avoids restructuring the existing undo path.

## 5. Apply-phase changes (`bulk_apply.py`)

Two new `get_record` calls per op (one before dispatch, one after):

```python
# Inside the apply loop, replacing the current "validate → dispatch → record applied" sequence

per_op_snapshots: dict[str, dict[str, Any]] = {}

for idx, bop in enumerate(input.operations):
    validation = _validate_op(idx, bop)
    if validation.status == "failed":
        outcomes.append(validation)
        # ... existing fail handling
        continue

    # Snapshot BEFORE the op
    try:
        rec_before = await deps.adapter.get_record(bop.record_uuid)
    except AdapterError:
        # existing RECORD_NOT_FOUND path
        ...
        continue

    # For move ops, reuse rec_before.location for pre_move_snapshots
    if bop.op == "move":
        pre_move_snapshots[bop.record_uuid] = rec_before.location

    try:
        await _dispatch_op(deps, bop)
    except AdapterError as e:
        # existing failure path
        ...
        continue

    # Snapshot AFTER successful op
    try:
        rec_after = await deps.adapter.get_record(bop.record_uuid)
        per_op_snapshots[str(idx)] = {
            "before": {"location": rec_before.location, "tags": list(rec_before.tags)},
            "after":  {"location": rec_after.location,  "tags": list(rec_after.tags)},
        }
    except AdapterError:
        # Record applied but post-snapshot failed (rare). Mark op as
        # applied but without per-op snapshot — undo will fall back to
        # legacy binary detection for THIS op only.
        log.warning("post_snapshot_failed", uuid=bop.record_uuid, op=bop.op, idx=idx)

    outcomes.append(BulkOpOutcome(index=idx, ..., status="applied"))
    applied += 1
```

Then in the final `set_after_state` call (line 202), include `per_op_snapshots`.

**Cost**: `bulk_apply` was 1 JXA round-trip per op (the dispatch). Becomes 3 (before + dispatch + after). For `move` ops, the existing `pre_move_snapshots` lookup at line 102 was already a `get_record` — fold it into `rec_before` to keep cost at 3, not 4. On a 50-op batch this means ~150 JXA calls vs 50; with the worker pool semaphore (4-8 concurrent, per `CLAUDE.md` §2.3) and a typical 50-200 ms per call, total batch latency goes from ~5s to ~15s. Acceptable for an op the user explicitly opts into via `confirm_token`.

## 6. Undo-phase changes (`undo.py::_undo_bulk_apply`)

The current logic builds `inverse_plan` from `after_state.applied` and applies each inverse op blindly. Replace with per-op drift evaluation.

```python
async def _undo_bulk_apply(deps, entry, *, dry_run, force):
    after = entry.after_state or {}
    applied = after.get("applied") or []
    snapshots = after.get("pre_move_snapshots") or {}
    per_op = after.get("per_op_snapshots") or {}

    # Legacy fallback: no per_op_snapshots → current behavior (no drift detection)
    has_drift_detection = bool(per_op)

    inverse_plan: list[dict[str, Any]] = []
    drift_per_op: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    # Walk applied in REVERSE (LIFO) but keep the original index
    # for snapshot lookup. Build a list of (original_index, op) pairs.
    indexed_applied = list(enumerate(applied))
    for orig_idx, op in reversed(indexed_applied):
        # ... (compute inverse op as today: add_tag→remove_tag, etc.)

        if has_drift_detection:
            snap = per_op.get(str(orig_idx))
            if snap is None:
                # Per-op snapshot missing for this specific op (post-snapshot
                # failed at apply time). Skip drift check for this op.
                drift_per_op.append({"index": orig_idx, "uuid": uuid,
                                     "drift_state": "unknown",
                                     "reason": "no per-op snapshot"})
                # Add to inverse_plan unconditionally (legacy behavior for this op)
                inverse_plan.append(inverse_op)
                continue

            try:
                current = await deps.adapter.get_record(uuid)
            except AdapterError:
                drift_per_op.append({"index": orig_idx, "uuid": uuid,
                                     "drift_state": "unknown",
                                     "reason": "record not retrievable"})
                skipped.append({"uuid": uuid, "reason": "record not retrievable"})
                continue

            drift_state = compute_drift_state(current, snap["before"], snap["after"])
            entry_dict = {"index": orig_idx, "uuid": uuid, "drift_state": drift_state}

            if drift_state == "already_reverted":
                entry_dict["reason"] = "already in pre-op state"
                drift_per_op.append(entry_dict)
                skipped.append({"uuid": uuid, "reason": "already_reverted",
                                "index": orig_idx})
                continue

            if drift_state == "hostile_drift" and not force:
                entry_dict["drift_details"] = _diff_details(current, snap)
                drift_per_op.append(entry_dict)
                skipped.append({"uuid": uuid, "reason": "hostile_drift",
                                "index": orig_idx})
                continue

            # no_drift, or hostile_drift + force
            drift_per_op.append(entry_dict)
            inverse_plan.append(inverse_op)
        else:
            # Legacy path — no per-op snapshots, no drift check
            inverse_plan.append(inverse_op)

    # ... (dry_run path returns drift_per_op + skipped + inverse_plan)
    # ... (apply path executes inverse_plan, accumulates failures, returns aggregate)
```

A small helper `_diff_details(current, snap)` mirrors the `drift_details` shape used in the `file_document` path (location/tags expected vs current). Lives in `undo.py` next to `_undo_bulk_apply`.

`compute_drift_state` is **reused unchanged** — it operates on `RecordSnapshot` (current) vs two dicts (`before_state`, `after_state`). The dicts here are `snap["before"]` and `snap["after"]`, same shape as `file_document` already passes.

## 7. Output schema (`undo.py` return value)

Today's bulk undo return shape stays mostly the same. Additions are marked **NEW**.

```json
{
  "audit_id": "...",
  "tool_name": "bulk_apply",
  "reverted": <true if all reverts succeeded, false otherwise>,
  "reverted_count": N,
  "drift_detected": <true iff at least one op is hostile_drift>,
  "drift_per_op": [                                          // NEW
    {"index": 0, "uuid": "...", "drift_state": "no_drift"},
    {"index": 1, "uuid": "...", "drift_state": "already_reverted",
     "reason": "already in pre-op state"},
    {"index": 2, "uuid": "...", "drift_state": "hostile_drift",
     "drift_details": {"tags": {"expected": [...], "current": [...]}}}
  ],
  "would_revert": [...],   // dry_run only, unchanged
  "skipped": [
    {"uuid": "...", "reason": "already_reverted", "index": 1},
    {"uuid": "...", "reason": "hostile_drift", "index": 2}
  ],
  "failures": [...],
  "force_acknowledged": <bool>,
  "dry_run": <bool>,
  "message": "ok" | "<reverted_count> reverted, <failures> failed, <skipped> skipped"
}
```

Backward compat: clients reading `reverted`, `reverted_count`, `failures`, `skipped`, `drift_detected` see them with the same semantics. New clients can opt into `drift_per_op` for fine-grained reporting.

## 8. Testing strategy

Per `CLAUDE.md` §6 + ADR-0005 (4-tier).

### 8.1 Unit (mock adapter, no JXA)

New file: `tests/unit/test_undo_bulk_apply_drift.py`. Covers:

- All 3 drift states for each of the 3 op types (`add_tag`, `remove_tag`, `move`) → 9 happy-path tests.
- Mixed batch: 3 ops, one in each drift state. Verify per-op resolution and aggregate `drift_detected: True`.
- `force=True` with hostile_drift → all reverted regardless.
- `force=True` with already_reverted → still skipped (force has no effect on this state, mirroring `file_document` behavior).
- Missing `per_op_snapshots` (legacy entry) → falls back to current behavior, `drift_per_op` empty/absent.
- Missing snapshot for one op (post-snapshot-failed case) → that op skipped with `drift_state: "unknown"`, others processed normally.
- `get_record` fails for one op during undo → `drift_state: "unknown"`, op skipped, others processed.

### 8.2 Contract

Update `tests/contract/` if there's an existing `bulk_apply` undo contract. New schema is additive — existing contract should still pass; add a new contract test for `drift_per_op` shape.

### 8.3 Integration (skip default, requires DT live)

New file: `tests/integration/test_undo_bulk_apply_drift_live.py`. One round-trip test:

1. Set up 3 records in fixtures-dt-mcp.
2. Apply a bulk batch: tag record A, tag record B, move record C.
3. Manually revert record A's tag externally (simulating `already_reverted`).
4. Externally edit record B's tags (add a foreign tag — simulating `hostile_drift`).
5. Leave record C as the bulk left it.
6. Call undo. Verify: A skipped (`already_reverted`), B skipped (`hostile_drift`), C reverted (`no_drift`).
7. Call undo with `force=True`. Verify: B now also reverted; A still skipped.

### 8.4 Cassette VCR

Re-record the existing bulk_apply cassette via `record-cassette` CLI. The new `get_record` calls will be captured and replayed. No invariant changes needed beyond what `cassette_sanitizer` already handles. Verify cassette still passes the invariant tests (split DB/record name maps, real_uuid_map, trailing-slash, reference_url).

## 9. Migration & rollout

- **Audit entries written before merge**: missing `per_op_snapshots`. Legacy fallback in `_undo_bulk_apply` preserves their behavior. No migration script.
- **Audit entries written after merge**: gain the new shape automatically. Older clients (none in the wild — single-user) ignore the new field harmlessly.
- **Version bump**: minor (0.3.0). New behavior is opt-in by virtue of being undo-only and additive in output.
- **CHANGELOG entry**: under `## [0.3.0]`, section `### Changed` for the undo schema addition + section `### Added` for the new test files.

## 10. Failure modes & mitigations

| Failure | Behavior | Mitigation |
|---|---|---|
| Pre-snapshot `get_record` fails | Op aborts before dispatch (current behavior). Outcome: `RECORD_NOT_FOUND`. | Existing pattern, unchanged. |
| Dispatch fails | Op marked failed. No after-snapshot taken. | Current behavior. |
| Post-snapshot fails (rare: record deleted between dispatch and refetch) | Op recorded as applied; per-op snapshot omitted; undo for this op falls back to no drift detection. | Logged as warning. Op still revertible blindly. |
| `per_op_snapshots` absent in audit entry (legacy) | Undo path takes legacy branch; no per-op drift detection; behavior identical to today. | Bool flag `has_drift_detection` controls the branch. |
| Schema corruption (malformed JSON in `after_state`) | `after.get("per_op_snapshots") or {}` returns empty → legacy branch. | Defensive default. Audit log integrity is a separate concern. |
| `compute_drift_state` returns unexpected value | Current `Literal` typing prevents this at the type level. Runtime guard: explicit `if/elif` over the three states; else log error and treat as `unknown`. | Same defensive pattern as `_undo_bulk_apply` already has for unknown op types. |

## 11. Effort estimate

- Day 1: `bulk_apply.py` apply-phase changes + per-op snapshot persistence. Refactor existing pre-move snapshot capture to fold into `rec_before`.
- Day 2: `_undo_bulk_apply` rewrite with per-op drift evaluation. `_diff_details` helper.
- Day 3: Unit tests (~15 cases). Contract test additions.
- Day 4: Integration test on DT live. Cassette re-record.
- Day 5: Buffer for cassette sanitizer edge cases (per memory `tech_pattern_cassette_sanitizer.md`, the sanitizer has been the surprise sink in past PRs).

Total: 3-5 working days. One PR, branchable into smaller commits per file.

## 12. Open questions

None blocking. The approach mirrors `file_document` 3-state detection (proven in 0.2.0) and adds nothing structurally new.
