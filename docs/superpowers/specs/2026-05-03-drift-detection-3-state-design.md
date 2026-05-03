# Drift Detection 3-State — Design Spec

- **Status**: approved 2026-05-03
- **Target version**: 0.2.0
- **Owner**: istefox
- **Scope**: `undo` of `file_document` audit entries (CLI + MCP tool surface)
- **Out of scope**: `bulk_apply` undo, audit log schema migrations

---

## 1. Context

In 0.1.0 the `undo` command implements binary drift detection: it compares the current DEVONthink state against `after_state` (the snapshot persisted by `file_document` immediately after a successful write) and either reverts safely or refuses, requiring the caller to pass `--force` to override.

This collapses two operationally distinct situations into the same outcome:

- The user has already manually reverted the change (the record is back to `before_state`). Forcing here is a no-op at best, confusing at worst.
- An external actor (smart rule, manual edit unrelated to the original op, third-party process) has modified the record into a state that matches neither `before_state` nor `after_state`. Forcing here legitimately overwrites foreign work.

Today both paths require `--force`. This is a false positive in the first case and dilutes the safety meaning of the flag.

## 2. Goals

- Distinguish three drift states in `undo` of `file_document`: `no_drift`, `already_reverted`, `hostile_drift`.
- Eliminate `--force` requirement when the record is already in pre-apply state.
- Reserve `--force` semantics exclusively for `hostile_drift` (legitimately overriding an external edit).
- Surface the new state to consumers (CLI, MCP tool) without breaking the existing `drift_detected: bool` contract.
- Produce richer `drift_details` for `already_reverted` so the user can see why the tool concluded the change was already undone.

## 3. Non-goals

- Extending 3-state detection to `bulk_apply` undo. That requires per-op `after_state` snapshots not captured today; deferred to 0.3.0+.
- Migrating legacy audit entries (pre-W10, no `after_state`). Those continue under the existing heuristic fallback (binary).
- Auto-detecting partial reverts and treating them as `already_reverted`. Strict equality with `before_state` only — partial reverts fall through to `hostile_drift`.
- Adding new fields to `AuditEntry` (Pydantic schema). All required state is already persisted.

## 4. Detection algorithm

A new pure function lives in `apps/server/src/istefox_dt_mcp_server/undo.py`:

```python
def compute_drift_state(
    current: RecordSnapshot,
    before_state: dict[str, Any],
    after_state: dict[str, Any] | None,
) -> Literal["no_drift", "already_reverted", "hostile_drift"]:
    ...
```

Order of evaluation (first match wins):

1. **`no_drift`** — `after_state is not None` AND
   `current.location == after_state["location"]` AND
   `set(current.tags) == set(after_state.get("tags", []))`.
2. **`already_reverted`** — strict match with `before_state`:
   `current.location == before_state["location"]` AND
   `set(current.tags) == set(before_state.get("tags", []))`.
3. **`hostile_drift`** — anything else.

Set comparison on tags ignores order (DEVONthink may re-sort tags on persistence). String comparison on location is exact.

### Legacy fallback (audit entries without `after_state`)

When `after_state is None` (audit entries written by the connector pre-W10), we cannot distinguish `no_drift` from `already_reverted`: both can produce `current.location == destination_hint`. The function returns only two values in that branch:

- `no_drift` if `current.location == input_data["destination_hint"]`
- `hostile_drift` otherwise

`already_reverted` is structurally unreachable for legacy entries. This is documented as a known limitation in the user-facing docs and as a comment in code.

## 5. Behavior matrix

| Drift state | Condition | `--force` semantics | Action |
|---|---|---|---|
| `no_drift` | `current == after_state` | irrelevant | revert proceeds (move + tag removal) |
| `already_reverted` | `current == before_state` | ignored; response includes `force_ignored: true`, log event `force_unused` with `reason: already_reverted` | successful no-op: returns `reverted: false`, `message: "record already in pre-apply state"`. CLI exits 0, MCP tool returns `success: true` |
| `hostile_drift` | else | required to proceed | without `--force`: returns `reverted: false`, `drift_details` populated with current/expected diff. With `--force`: revert proceeds and overwrites |

`dry_run` interaction: dry-run preview reports the same `drift_state` and the action that *would* be taken in apply mode. No side effects in any state.

## 6. Response schema

The dict returned by `undo_audit` gains one new key, `drift_state`. The legacy `drift_detected: bool` is preserved to keep 0.1.0 consumers (tests, scripts) working.

`drift_details` shape varies by drift state:

- `no_drift`: not present in response
- `already_reverted`: present, includes `matched_against: "before_state"` plus location/tags both showing current and before values for confirmation
- `hostile_drift`: present, same shape as 0.1.0 (expected vs current, added/removed for tags)

### Mapping legacy ↔ new

| `drift_state` | `drift_detected` |
|---|---|
| `no_drift` | `false` |
| `already_reverted` | `false` |
| `hostile_drift` | `true` |

Rationale: `drift_detected` semantically meant "should the user worry?" — `already_reverted` is *not* something to worry about, so it maps to `false`.

### Example responses

**`no_drift` (apply mode)**:
```json
{
  "audit_id": "...",
  "target_record_uuid": "...",
  "drift_detected": false,
  "drift_state": "no_drift",
  "reverted": true,
  "message": "ok",
  "dry_run": false
}
```

**`already_reverted` (apply mode, with or without `--force`)**:
```json
{
  "audit_id": "...",
  "target_record_uuid": "...",
  "drift_detected": false,
  "drift_state": "already_reverted",
  "drift_details": {
    "matched_against": "before_state",
    "location": {"current": "/DEMO", "before": "/DEMO"},
    "tags": {"current": [], "before": []}
  },
  "reverted": false,
  "message": "record already in pre-apply state, nothing to revert",
  "force_ignored": true,
  "dry_run": false
}
```

`force_ignored` is present only when the caller passed `--force` and the state was `already_reverted` — gives audit visibility for "user intended override but was a no-op".

**`hostile_drift` (apply mode, no force)**:
```json
{
  "audit_id": "...",
  "target_record_uuid": "...",
  "drift_detected": true,
  "drift_state": "hostile_drift",
  "drift_details": {
    "location": {"expected": "/DEMO/Archive", "current": "/OPS"},
    "tags": {"expected": ["invoices"], "current": ["misfiled"], "added": ["misfiled"], "removed": ["invoices"]}
  },
  "reverted": false,
  "message": "record moved/edited since the original write; pass --force to revert anyway (will overwrite intervening changes)",
  "dry_run": false
}
```

`drift_details` keeps the existing 0.1.0 shape (expected vs current, added/removed for tags) — additive change only.

## 7. Backwards compatibility

- **`AuditEntry` schema**: unchanged. All required fields exist already.
- **Audit log on disk**: no migration. Existing rows in `audit.sqlite` work as-is.
- **Legacy entries (pre-W10)**: continue under the fallback heuristic, returning binary states only.
- **Existing tests**: `test_undo.py` (12 tests) continues to pass — `drift_detected` semantics preserved. New tests added for `drift_state` and `already_reverted` behavior.
- **CLI users / scripts** reading `drift_detected: bool`: continue working. Adopting `drift_state` is opt-in.
- **MCP tool consumers** (Claude/Cursor/Cline): see `drift_state` as a new string field in the tool response. The schema published in `tools/list` will include it; the LLM can either consume it or fall back to `drift_detected`.

## 8. Test plan

### Unit (in `tests/unit/test_undo.py`, extend the existing file)

New tests for `compute_drift_state`:

1. `current` matches `after_state` exactly → `no_drift`
2. `current.tags` permuted vs `after_state.tags` (same set, different order) → `no_drift`
3. `current` matches `before_state` exactly → `already_reverted`
4. `current.location` matches before, `current.tags` extends before → `hostile_drift`
5. `current` matches neither → `hostile_drift`
6. `after_state is None`, `current.location == destination_hint` → `no_drift` (legacy)
7. `after_state is None`, `current.location != destination_hint` → `hostile_drift` (legacy)

New tests for `undo_audit` integration:

8. `already_reverted` without `--force` → `reverted: false, drift_state: "already_reverted"`, no JXA mutation calls
9. `already_reverted` with `--force` → same outcome + `force_ignored: true`
10. `hostile_drift` without `--force` → existing behavior preserved (drift_details populated)
11. `hostile_drift` with `--force` → revert applied (existing behavior preserved)
12. `no_drift` apply mode → revert applied (existing behavior preserved)

### Integration (in `tests/integration/test_undo_drift.py` — new file, marked `integration`)

Optional, requires DT running. Smoke verifies the three states end-to-end against a live DT database. Skip-by-default, runnable manually.

## 9. Implementation note

The change set is small enough to fit in one PR:

- `compute_drift_state()` pure function (new, ~30 LoC)
- `undo_audit()` refactor to call it and route to one of three branches (~50 LoC delta)
- New tests (~120 LoC)
- CHANGELOG entry under `[Unreleased]`
- README troubleshooting row update (current "drift_detected: true" entry mentions `--force`; we add a note distinguishing `already_reverted` from `hostile_drift`)

Estimated effort: 1-2 sessions. No new dependencies.

## 10. Risks & open questions

- **Risk**: an audit entry where `after_state` was captured incorrectly (e.g. DT returned a stale snapshot) could classify `current` as `hostile_drift` when in fact nothing changed externally. Mitigation: the existing `drift_details` in `hostile_drift` makes the field-level diff visible, so the user can spot the false positive. No code change beyond what 0.1.0 already does.
- **Open question**: does Claude (the LLM consumer) need explicit instructions in the tool description about the new `drift_state` semantics? Probably yes — we add a one-line mention to the `undo` tool description in `apps/server/src/istefox_dt_mcp_server/tools/`. Decided in the implementation plan.
