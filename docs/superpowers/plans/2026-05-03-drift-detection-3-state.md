# Drift Detection 3-State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace binary drift detection in `undo_audit()` (file_document only) with a 3-state classifier (`no_drift` / `already_reverted` / `hostile_drift`), eliminating the `--force` requirement when the user has already manually reverted to the pre-apply state.

**Architecture:** Add a pure function `compute_drift_state(current, before_state, after_state)` that classifies the current DT record against the audit snapshots. Refactor `undo_audit()` to dispatch on the classifier output: `no_drift` reverts (existing path), `already_reverted` short-circuits as a successful no-op, `hostile_drift` blocks unless `--force`. Response gains a new `drift_state: str` field next to legacy `drift_detected: bool`. No schema migration: `before_state` + `after_state` are already persisted on `AuditEntry`.

**Tech Stack:** Python 3.12, pytest + pytest-asyncio, structlog, Pydantic v2, AsyncMock for adapter. Project layout: `apps/server/src/istefox_dt_mcp_server/`.

**Reference spec:** [`docs/superpowers/specs/2026-05-03-drift-detection-3-state-design.md`](../specs/2026-05-03-drift-detection-3-state-design.md)

---

### Task 1: Branch + baseline

**Files:**
- No file changes — preparation only

- [ ] **Step 1.1: Switch to a new feature branch off main**

```bash
git checkout main
git pull --ff-only
git checkout -b feat/drift-detection-3-state
```

- [ ] **Step 1.2: Run the existing unit test suite to establish baseline**

```bash
uv run pytest tests/unit/test_undo.py -v
```

Expected: 12 tests pass, ~1s runtime. If anything fails, stop and investigate before continuing — the plan assumes a green baseline.

- [ ] **Step 1.3: Read the current `undo.py` and `test_undo.py` once before making changes**

```bash
wc -l apps/server/src/istefox_dt_mcp_server/undo.py tests/unit/test_undo.py
# Expected: 345 + 323 = 668 lines total
```

Skim the two files. Note the existing helpers `_record()` and `_audit_file_document()` in the test module — Task 2 and Task 3 reuse them.

---

### Task 2: Add `compute_drift_state` pure function (TDD, unit-level only)

**Files:**
- Modify: `apps/server/src/istefox_dt_mcp_server/undo.py` (add new function, no behavioral change yet)
- Modify: `tests/unit/test_undo.py` (add 7 new tests at the end of the file)

- [ ] **Step 2.1: Add 7 failing tests at the bottom of `tests/unit/test_undo.py`**

Append this block at the end of the file (after the last existing test). The tests directly exercise the new pure function — no `deps` fixture needed.

```python
# ---------- compute_drift_state (3-state classifier) ----------


def test_compute_drift_state_no_drift_exact_match() -> None:
    from istefox_dt_mcp_server.undo import compute_drift_state

    current = _record(location="/Archive", tags=["invoices"])
    before = {"location": "/Inbox", "tags": []}
    after = {"location": "/Archive", "tags": ["invoices"]}

    assert compute_drift_state(current, before, after) == "no_drift"


def test_compute_drift_state_no_drift_tag_order_irrelevant() -> None:
    from istefox_dt_mcp_server.undo import compute_drift_state

    current = _record(location="/Archive", tags=["b", "a"])
    before = {"location": "/Inbox", "tags": []}
    after = {"location": "/Archive", "tags": ["a", "b"]}

    assert compute_drift_state(current, before, after) == "no_drift"


def test_compute_drift_state_already_reverted_strict_match() -> None:
    from istefox_dt_mcp_server.undo import compute_drift_state

    current = _record(location="/Inbox", tags=[])
    before = {"location": "/Inbox", "tags": []}
    after = {"location": "/Archive", "tags": ["invoices"]}

    assert compute_drift_state(current, before, after) == "already_reverted"


def test_compute_drift_state_partial_revert_is_hostile() -> None:
    """Strict match: location matches before, but tag from apply is still
    present. Per spec Q1 = A, this is hostile_drift, not already_reverted."""
    from istefox_dt_mcp_server.undo import compute_drift_state

    current = _record(location="/Inbox", tags=["invoices"])
    before = {"location": "/Inbox", "tags": []}
    after = {"location": "/Archive", "tags": ["invoices"]}

    assert compute_drift_state(current, before, after) == "hostile_drift"


def test_compute_drift_state_unrelated_location_is_hostile() -> None:
    from istefox_dt_mcp_server.undo import compute_drift_state

    current = _record(location="/OPS", tags=["misfiled"])
    before = {"location": "/Inbox", "tags": []}
    after = {"location": "/Archive", "tags": ["invoices"]}

    assert compute_drift_state(current, before, after) == "hostile_drift"


def test_compute_drift_state_legacy_no_after_state_no_drift() -> None:
    """Pre-W10 audit entry (after_state=None). Falls back to comparing
    current.location with the before snapshot — if they match, treat as
    no_drift (the apply moved the record elsewhere, so being back at
    'before' here is unreachable in legacy semantics; we conservatively
    say no_drift only when current still matches the apply target,
    which we can't tell, so we degrade to no_drift only if there's
    nothing to compare. Spec section 4 legacy fallback."""
    from istefox_dt_mcp_server.undo import compute_drift_state

    # Legacy classifier knows only `current` vs `before` (no after).
    # Without after_state, the only safe positive is "current still
    # matches before" — which is `already_reverted` if interpretable,
    # but legacy returns no_drift when nothing diverged.
    current = _record(location="/Inbox", tags=[])
    before = {"location": "/Inbox", "tags": []}

    assert compute_drift_state(current, before, None) == "no_drift"


def test_compute_drift_state_legacy_no_after_state_hostile_when_diverged() -> None:
    from istefox_dt_mcp_server.undo import compute_drift_state

    current = _record(location="/OPS", tags=[])
    before = {"location": "/Inbox", "tags": []}

    assert compute_drift_state(current, before, None) == "hostile_drift"
```

- [ ] **Step 2.2: Run the new tests to verify they fail with ImportError**

```bash
uv run pytest tests/unit/test_undo.py -v -k "compute_drift_state"
```

Expected: 7 tests fail with `ImportError: cannot import name 'compute_drift_state' from 'istefox_dt_mcp_server.undo'`.

- [ ] **Step 2.3: Add the `compute_drift_state` function near the top of `undo.py`**

Open `apps/server/src/istefox_dt_mcp_server/undo.py`. Add this function **right after the `log = structlog.get_logger(__name__)` line** (currently line 31), before the `async def undo_audit(...)` declaration:

```python
DriftState = Literal["no_drift", "already_reverted", "hostile_drift"]


def compute_drift_state(
    current: Record,
    before_state: dict[str, Any],
    after_state: dict[str, Any] | None,
) -> DriftState:
    """Classify current DT record against audit snapshots.

    Order of evaluation (first match wins):
        1. ``no_drift`` — current matches ``after_state`` (the snapshot
           captured by file_document immediately after a successful
           apply). Safe to revert.
        2. ``already_reverted`` — current matches ``before_state``
           strictly (location equal AND tag set equal). The user (or
           an external actor) has restored the pre-apply state;
           reverting is a no-op.
        3. ``hostile_drift`` — neither matches. Reverting will overwrite
           changes; caller must opt in via ``--force``.

    Legacy fallback (``after_state is None``): only ``no_drift`` and
    ``hostile_drift`` are reachable. ``already_reverted`` requires a
    captured after-snapshot to disambiguate from the apply target.

    Args:
        current: Live DT record snapshot (from ``adapter.get_record``).
        before_state: ``AuditEntry.before_state`` dict; must contain
            ``location: str`` and ``tags: list[str]``.
        after_state: ``AuditEntry.after_state`` dict, or ``None`` for
            legacy entries written before W10.

    Returns:
        One of ``"no_drift"``, ``"already_reverted"``, ``"hostile_drift"``.
    """
    before_location = str(before_state.get("location") or "")
    before_tags = set(before_state.get("tags") or [])

    if after_state is not None:
        after_location = str(after_state.get("location") or "")
        after_tags = set(after_state.get("tags") or [])
        if current.location == after_location and set(current.tags) == after_tags:
            return "no_drift"
        if current.location == before_location and set(current.tags) == before_tags:
            return "already_reverted"
        return "hostile_drift"

    # Legacy branch — no after_state, only 2 outcomes possible.
    if current.location == before_location and set(current.tags) == before_tags:
        return "no_drift"
    return "hostile_drift"
```

Also update the imports at the top of `undo.py`. The current imports section is:

```python
from typing import TYPE_CHECKING, Any
from uuid import UUID
```

Change to:

```python
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from istefox_dt_mcp_schemas.common import Record  # noqa: TC001 — runtime use in compute_drift_state
```

- [ ] **Step 2.4: Run the new tests, verify they pass**

```bash
uv run pytest tests/unit/test_undo.py -v -k "compute_drift_state"
```

Expected: 7 tests pass.

- [ ] **Step 2.5: Run the full undo test file to verify no regressions**

```bash
uv run pytest tests/unit/test_undo.py -v
```

Expected: 19 tests pass (12 existing + 7 new).

- [ ] **Step 2.6: Commit**

```bash
git add apps/server/src/istefox_dt_mcp_server/undo.py tests/unit/test_undo.py
git commit -m "feat(undo): add compute_drift_state 3-state classifier (pure function)

Pure function classifies current DT state against audit before/after
snapshots:
- no_drift: current matches after_state, revert safe
- already_reverted: current matches before_state strictly, revert no-op
- hostile_drift: anything else, requires --force

Legacy entries (after_state=None) collapse to 2-state behavior.
Function is wired in by Task 3 — this commit is additive, no behavior
change to undo_audit yet.

Spec: docs/superpowers/specs/2026-05-03-drift-detection-3-state-design.md"
```

---

### Task 3: Wire `compute_drift_state` into `undo_audit` + `already_reverted` branch

**Files:**
- Modify: `apps/server/src/istefox_dt_mcp_server/undo.py` (refactor the drift-check block in `undo_audit`)
- Modify: `tests/unit/test_undo.py` (add 5 integration tests)

- [ ] **Step 3.1: Add 5 integration tests for the new state behaviors**

Append at the end of `tests/unit/test_undo.py`:

```python
# ---------- undo_audit dispatching on drift_state ----------


@pytest.mark.asyncio
async def test_undo_already_reverted_no_force_returns_noop(deps: Deps) -> None:
    """current matches before_state → already_reverted, no JXA mutation."""
    audit_id = _audit_file_document(
        deps,
        before_location="/Inbox",
        before_tags=[],
        after_location="/Archive",
        after_tags=["invoices"],
    )
    deps.adapter.get_record = AsyncMock(
        return_value=_record(location="/Inbox", tags=[])
    )
    deps.adapter.move_record = AsyncMock()
    deps.adapter.remove_tag = AsyncMock()

    result = await undo_audit(deps, audit_id, dry_run=False, force=False)

    assert result["reverted"] is False
    assert result["drift_state"] == "already_reverted"
    assert result["drift_detected"] is False  # legacy contract
    assert "already" in str(result["message"]).lower()
    deps.adapter.move_record.assert_not_called()
    deps.adapter.remove_tag.assert_not_called()


@pytest.mark.asyncio
async def test_undo_already_reverted_with_force_ignores_force(deps: Deps) -> None:
    """--force in already_reverted: response flags force_ignored, no JXA call."""
    audit_id = _audit_file_document(
        deps,
        before_location="/Inbox",
        before_tags=[],
        after_location="/Archive",
        after_tags=["invoices"],
    )
    deps.adapter.get_record = AsyncMock(
        return_value=_record(location="/Inbox", tags=[])
    )
    deps.adapter.move_record = AsyncMock()
    deps.adapter.remove_tag = AsyncMock()

    result = await undo_audit(deps, audit_id, dry_run=False, force=True)

    assert result["reverted"] is False
    assert result["drift_state"] == "already_reverted"
    assert result.get("force_ignored") is True
    deps.adapter.move_record.assert_not_called()
    deps.adapter.remove_tag.assert_not_called()


@pytest.mark.asyncio
async def test_undo_no_drift_includes_drift_state_field(deps: Deps) -> None:
    """Existing no-drift path: drift_state="no_drift", drift_detected=False."""
    audit_id = _audit_file_document(
        deps,
        before_location="/Inbox",
        before_tags=[],
        after_location="/Archive",
        after_tags=["invoices"],
    )
    deps.adapter.get_record = AsyncMock(
        return_value=_record(location="/Archive", tags=["invoices"])
    )
    deps.adapter.move_record = AsyncMock()
    deps.adapter.remove_tag = AsyncMock()

    result = await undo_audit(deps, audit_id, dry_run=False, force=False)

    assert result["reverted"] is True
    assert result["drift_state"] == "no_drift"
    assert result["drift_detected"] is False


@pytest.mark.asyncio
async def test_undo_hostile_drift_no_force_blocks(deps: Deps) -> None:
    """Existing hostile-drift path: drift_state="hostile_drift", blocked."""
    audit_id = _audit_file_document(
        deps,
        before_location="/Inbox",
        before_tags=[],
        after_location="/Archive",
        after_tags=["invoices"],
    )
    deps.adapter.get_record = AsyncMock(
        return_value=_record(location="/OPS", tags=["misfiled"])
    )

    result = await undo_audit(deps, audit_id, dry_run=False, force=False)

    assert result["reverted"] is False
    assert result["drift_state"] == "hostile_drift"
    assert result["drift_detected"] is True  # legacy contract preserved
    assert "drift_details" in result


@pytest.mark.asyncio
async def test_undo_hostile_drift_with_force_proceeds(deps: Deps) -> None:
    """--force in hostile_drift overrides as today."""
    audit_id = _audit_file_document(
        deps,
        before_location="/Inbox",
        before_tags=[],
        after_location="/Archive",
        after_tags=["invoices"],
    )
    deps.adapter.get_record = AsyncMock(
        return_value=_record(location="/OPS", tags=["misfiled"])
    )
    deps.adapter.move_record = AsyncMock()
    deps.adapter.remove_tag = AsyncMock()

    result = await undo_audit(deps, audit_id, dry_run=False, force=True)

    assert result["reverted"] is True
    assert result["drift_state"] == "hostile_drift"
    deps.adapter.move_record.assert_called()
```

- [ ] **Step 3.2: Run the new tests, verify they fail**

```bash
uv run pytest tests/unit/test_undo.py -v -k "drift_state or already_reverted or hostile"
```

Expected: 5 tests fail (KeyError on `drift_state`, or AssertionError because the field doesn't exist yet).

- [ ] **Step 3.3: Refactor the drift-check block in `undo_audit`**

Open `apps/server/src/istefox_dt_mcp_server/undo.py`. The current block at lines ~109-168 computes `drift_detected` ad-hoc and either returns blocked-with-drift or falls through to the revert path. Replace it with a 3-state dispatch.

Find this section (currently lines 102-168, ending at the `}` before `if dry_run:`):

```python
    input_data = entry.input_json or {}
    before_location = str(entry.before_state.get("location") or "")
    before_tags: list[str] = list(entry.before_state.get("tags") or [])

    # Compute tags to remove and drift status. With after_state
    # available (W10+) we know exactly what the op produced and can
    # tell apart "user changed it" from "this is what we applied".
    if entry.after_state is not None:
        after_location = str(entry.after_state.get("location") or "")
        after_tags = set(entry.after_state.get("tags") or [])
        tags_added = sorted(after_tags - set(before_tags))
        drift_detected = (
            current.location != after_location or set(current.tags) != after_tags
        )
    else:
        # Legacy fallback (pre-W10 audit entries): infer tags added
        # from current minus before, and check drift by comparing the
        # current location to the original destination_hint.
        tags_added = [t for t in current.tags if t not in before_tags]
        drift_detected = current.location != before_location and not _is_first_undo(
            current.location, input_data
        )

    if drift_detected and not force:
        # Surface WHAT diverged so the user can decide if it's a real
        # external edit (then probably don't undo) or a false positive
        # (e.g. DT auto-added a tag, sorted tags differently, returned
        # location with a trailing slash). Fast path to debugging
        # without inspecting the SQLite audit log by hand.
        drift_details: dict[str, object] = {}
        if entry.after_state is not None:
            after_loc = str(entry.after_state.get("location") or "")
            after_t = sorted(entry.after_state.get("tags") or [])
            cur_t = sorted(current.tags)
            if current.location != after_loc:
                drift_details["location"] = {
                    "expected": after_loc,
                    "current": current.location,
                }
            if cur_t != after_t:
                drift_details["tags"] = {
                    "expected": after_t,
                    "current": cur_t,
                    "added": sorted(set(cur_t) - set(after_t)),
                    "removed": sorted(set(after_t) - set(cur_t)),
                }
        else:
            if current.location != before_location:
                drift_details["location"] = {
                    "expected_match_destination_hint": input_data.get(
                        "destination_hint"
                    ),
                    "current": current.location,
                    "before": before_location,
                }
        return {
            "audit_id": str(audit_id_obj),
            "target_record_uuid": target_uuid,
            "reverted": False,
            "drift_detected": True,
            "drift_details": drift_details,
            "message": (
                "record moved/edited since the original write; pass --force "
                "to revert anyway (will overwrite intervening changes)"
            ),
            "dry_run": dry_run,
        }
```

Replace it with this new block:

```python
    input_data = entry.input_json or {}
    before_location = str(entry.before_state.get("location") or "")
    before_tags: list[str] = list(entry.before_state.get("tags") or [])

    drift_state = compute_drift_state(current, entry.before_state, entry.after_state)

    # Tags added by the original apply (used by the revert path to know
    # which tags to strip). With after_state available we know exactly
    # what was added; in the legacy branch we infer from current.
    if entry.after_state is not None:
        after_tags = set(entry.after_state.get("tags") or [])
        tags_added = sorted(after_tags - set(before_tags))
    else:
        tags_added = [t for t in current.tags if t not in before_tags]

    if drift_state == "already_reverted":
        # User restored the pre-apply state on their own. Undo is a
        # no-op; --force is ignored (it has meaning only in
        # hostile_drift). Surface the matched-against snapshot for
        # visibility.
        if force:
            log.info(
                "force_unused",
                audit_id=str(audit_id_obj),
                reason="already_reverted",
            )
        return {
            "audit_id": str(audit_id_obj),
            "target_record_uuid": target_uuid,
            "reverted": False,
            "drift_detected": False,
            "drift_state": "already_reverted",
            "drift_details": {
                "matched_against": "before_state",
                "location": {
                    "current": current.location,
                    "before": before_location,
                },
                "tags": {
                    "current": sorted(current.tags),
                    "before": sorted(before_tags),
                },
            },
            **({"force_ignored": True} if force else {}),
            "message": "record already in pre-apply state, nothing to revert",
            "dry_run": dry_run,
        }

    if drift_state == "hostile_drift" and not force:
        drift_details: dict[str, object] = {}
        if entry.after_state is not None:
            after_loc = str(entry.after_state.get("location") or "")
            after_t = sorted(entry.after_state.get("tags") or [])
            cur_t = sorted(current.tags)
            if current.location != after_loc:
                drift_details["location"] = {
                    "expected": after_loc,
                    "current": current.location,
                }
            if cur_t != after_t:
                drift_details["tags"] = {
                    "expected": after_t,
                    "current": cur_t,
                    "added": sorted(set(cur_t) - set(after_t)),
                    "removed": sorted(set(after_t) - set(cur_t)),
                }
        else:
            if current.location != before_location:
                drift_details["location"] = {
                    "expected_match_destination_hint": input_data.get(
                        "destination_hint"
                    ),
                    "current": current.location,
                    "before": before_location,
                }
        return {
            "audit_id": str(audit_id_obj),
            "target_record_uuid": target_uuid,
            "reverted": False,
            "drift_detected": True,
            "drift_state": "hostile_drift",
            "drift_details": drift_details,
            "message": (
                "record moved/edited since the original write; pass --force "
                "to revert anyway (will overwrite intervening changes)"
            ),
            "dry_run": dry_run,
        }
```

Then update the two response dicts further down in `undo_audit` (currently the `if dry_run:` and final-success branches) to include `drift_state`. Find this dict (currently around lines 170-182):

```python
    if dry_run:
        return {
            "audit_id": str(audit_id_obj),
            "target_record_uuid": target_uuid,
            "reverted": False,
            "drift_detected": drift_detected,
            "message": "dry_run preview",
            "would_revert": {
                "move_to": before_location,
                "tags_to_remove": tags_added,
            },
            "dry_run": dry_run,
        }
```

Change to:

```python
    if dry_run:
        return {
            "audit_id": str(audit_id_obj),
            "target_record_uuid": target_uuid,
            "reverted": False,
            "drift_detected": drift_state == "hostile_drift",
            "drift_state": drift_state,
            "message": "dry_run preview",
            "would_revert": {
                "move_to": before_location,
                "tags_to_remove": tags_added,
            },
            "dry_run": dry_run,
        }
```

Find the final success dict (currently around lines 197-204):

```python
    return {
        "audit_id": str(audit_id_obj),
        "target_record_uuid": target_uuid,
        "reverted": True,
        "drift_detected": drift_detected,
        "message": "ok",
        "dry_run": dry_run,
    }
```

Change to:

```python
    return {
        "audit_id": str(audit_id_obj),
        "target_record_uuid": target_uuid,
        "reverted": True,
        "drift_detected": drift_state == "hostile_drift",
        "drift_state": drift_state,
        "message": "ok",
        "dry_run": dry_run,
    }
```

The local variable `drift_detected` is no longer assigned anywhere — the linter may flag it. Verify with `uv run ruff check apps/server/src/istefox_dt_mcp_server/undo.py` after the edits; if a stale reference remains, remove it.

- [ ] **Step 3.4: Run the new integration tests, verify they pass**

```bash
uv run pytest tests/unit/test_undo.py -v -k "drift_state or already_reverted or hostile"
```

Expected: 5 tests pass.

- [ ] **Step 3.5: Run the FULL test_undo.py to confirm no regressions in the 12 legacy tests**

```bash
uv run pytest tests/unit/test_undo.py -v
```

Expected: 24 tests pass (12 original + 7 from Task 2 + 5 from Task 3).

- [ ] **Step 3.6: Run the full project test suite as a smoke check**

```bash
uv run pytest -q
```

Expected: all unit + contract tests pass (around 168 total in 0.1.0; should be 173 now with the 5 added in Task 3 — the 7 from Task 2 are pure-function tests that count separately).

- [ ] **Step 3.7: Run lint + type check**

```bash
uv run ruff check apps/server/src/istefox_dt_mcp_server/undo.py tests/unit/test_undo.py
uv run mypy apps/server/src/istefox_dt_mcp_server/undo.py
```

Expected: zero issues. If there's a stale `drift_detected = ...` assignment from the old block, ruff will flag it as unused — delete it.

- [ ] **Step 3.8: Commit**

```bash
git add apps/server/src/istefox_dt_mcp_server/undo.py tests/unit/test_undo.py
git commit -m "feat(undo): dispatch on 3-state drift classifier in undo_audit

Wires compute_drift_state into the file_document undo path. New
behavior:
- already_reverted: returns successful no-op, --force ignored with
  force_ignored: true in response and structlog event force_unused
- no_drift: existing revert path, response gains drift_state field
- hostile_drift: existing block-with-details path, drift_state=hostile_drift

Legacy drift_detected: bool preserved (true iff hostile_drift).
12 existing tests continue to pass; 5 new integration tests added.

Spec: docs/superpowers/specs/2026-05-03-drift-detection-3-state-design.md"
```

---

### Task 4: Update CHANGELOG and README troubleshooting

**Files:**
- Modify: `CHANGELOG.md` (add bullet under `[Unreleased]`)
- Modify: `README.md` (update troubleshooting top-5 row about `drift_detected`)

- [ ] **Step 4.1: Find the `[Unreleased]` section in CHANGELOG.md**

```bash
grep -n "## \[Unreleased\]" CHANGELOG.md
```

Expected: one line number around the top of the file.

- [ ] **Step 4.2: Add an entry under `[Unreleased]`**

In `CHANGELOG.md`, just below the `## [Unreleased]` heading and any existing `### Added` / `### Changed` subsections, add:

```markdown
### Added (drift detection 3-state)

- `undo` of `file_document` now classifies drift into three states instead of
  two: `no_drift`, `already_reverted`, `hostile_drift`. Response gains a new
  `drift_state` field next to the legacy `drift_detected: bool`.
- `already_reverted` (record matches `before_state` strictly): undo returns a
  successful no-op and **does not require `--force`**. If `--force` is passed
  it's logged as `force_unused` and surfaced in the response as
  `force_ignored: true`.
- `--force` semantics narrowed: only relevant for `hostile_drift` (record in
  a state that matches neither `before_state` nor `after_state`).
- `compute_drift_state(current, before_state, after_state)` exposed as a pure
  helper in `istefox_dt_mcp_server.undo` for testing and downstream tooling.

### Compatibility

- No `AuditEntry` schema change; existing audit rows in `audit.sqlite` work
  as-is. Legacy entries written before W10 (no `after_state`) continue under
  the binary fallback (only `no_drift` / `hostile_drift` reachable).
- Existing `drift_detected: bool` semantics preserved: `true` only for
  `hostile_drift`.
- Scope limited to `file_document` undo. `bulk_apply` undo is unchanged
  (deferred to 0.3.0+).
```

- [ ] **Step 4.3: Update the README troubleshooting row about `drift_detected`**

```bash
grep -n "drift_detected: true" README.md
```

Expected: a row in the troubleshooting table around line 135.

Replace this row:

```markdown
| `drift_detected: true` (on undo) | Undo refuses to roll back | The record was modified after the original apply. Run `istefox-dt-mcp audit list --recent` for context, then add `--force` if the rollback is still what you want |
```

With:

```markdown
| `drift_state: hostile_drift` (on undo) | Undo refuses to roll back | The record was modified after the original apply by something other than your prior undo. Run `istefox-dt-mcp audit list --recent` for context, inspect `drift_details` in the response, then add `--force` if the rollback is still what you want. **Note:** if `drift_state: already_reverted`, the record is already back to the pre-apply state — no `--force` needed, undo returns a no-op |
```

- [ ] **Step 4.4: Sanity-check the changes**

```bash
git diff CHANGELOG.md README.md
```

Read the diff. Confirm: CHANGELOG entry under `[Unreleased]`, README troubleshooting row updated.

- [ ] **Step 4.5: Commit**

```bash
git add CHANGELOG.md README.md
git commit -m "docs: document drift detection 3-state in CHANGELOG + README

- CHANGELOG: new entry under [Unreleased] covering the additive
  drift_state field, already_reverted no-op semantics, --force scope
  narrowing, and backward compatibility guarantees.
- README: troubleshooting row rewritten around drift_state: hostile_drift
  and includes the no-op message for already_reverted."
```

---

### Task 5: Push, open PR, verify CI

**Files:**
- No file changes — git + GitHub flow only.

- [ ] **Step 5.1: Push the branch**

```bash
git push -u origin feat/drift-detection-3-state
```

Expected: branch tracked on origin.

- [ ] **Step 5.2: Open the PR**

```bash
gh pr create --title "feat(undo): drift detection 3-state for file_document" --body "$(cat <<'EOF'
## Summary

Implements the drift detection 3-state design for \`undo\` of \`file_document\` audit entries. Replaces the binary \`drift_detected\` check with a classifier that distinguishes three operationally distinct cases:

- **\`no_drift\`** — current matches \`after_state\`, revert proceeds (existing path).
- **\`already_reverted\`** — current matches \`before_state\` strictly. Undo is a successful no-op, and **\`--force\` is no longer required** for this case.
- **\`hostile_drift\`** — anything else. Existing block-with-\`drift_details\` path; \`--force\` still required to override.

The legacy \`drift_detected: bool\` field is preserved (\`true\` iff \`hostile_drift\`). New \`drift_state: str\` field added alongside it.

## Spec

[docs/superpowers/specs/2026-05-03-drift-detection-3-state-design.md](https://github.com/istefox/istefox-dt-mcp/blob/spec/drift-detection-3-state/docs/superpowers/specs/2026-05-03-drift-detection-3-state-design.md) — approved 2026-05-03.

## Scope

- ✅ \`file_document\` undo
- ❌ \`bulk_apply\` undo (deferred to 0.3.0+; needs per-op after-snapshots)
- ❌ Audit log schema migration (none needed — \`before_state\` + \`after_state\` already persisted)

## Test plan

- [x] 7 new unit tests for \`compute_drift_state\` (pure function)
- [x] 5 new integration tests for \`undo_audit\` dispatching on the 3 states
- [x] All 12 existing \`test_undo.py\` tests continue to pass (legacy \`drift_detected\` semantics preserved)
- [x] Full \`uv run pytest -q\` green
- [x] \`uv run ruff check\` + \`uv run mypy\` clean

## Compatibility notes

- No \`AuditEntry\` schema change; existing audit rows in \`audit.sqlite\` work as-is.
- Legacy entries pre-W10 (no \`after_state\`) continue under the binary fallback. \`already_reverted\` is structurally unreachable for those — documented in code and in the spec.
- MCP tool consumers see a new \`drift_state\` field in the \`undo\` response; \`drift_detected: bool\` continues to work for any consumer reading the legacy field.

## Out of scope (followups for 0.3.0+)

- Per-op drift detection on \`bulk_apply\` undo (requires capturing per-op after-snapshots in \`bulk_apply\` apply path)
- Auto-detection of partial reverts as \`already_reverted\` (intentionally rejected per spec Q1 = strict match)
EOF
)"
```

Expected: a PR URL is printed.

- [ ] **Step 5.3: Wait for CI and verify it's green**

```bash
gh pr checks --watch
```

Expected: \`lint-and-test\` and \`mypy\` both pass within 1-2 minutes.

- [ ] **Step 5.4: Stop here**

Do **not** auto-merge. The PR is ready for human review (or for the user to merge manually after reading the diff). The plan ends with the PR open.

---

## Notes for the executor

- Run from repo root: `/Users/stefanoferri/Developer/Devonthink_MCP`.
- Python 3.12 is required (`uv run` should pick it up automatically from `.python-version` / `uv.lock`).
- If `uv run pytest` fails to import `istefox_dt_mcp_schemas` or `istefox_dt_mcp_server`, run `uv sync --all-packages` once to refresh the workspace install.
- The project follows Conventional Commits in English; commit messages above are pre-formatted.
- No `Co-Authored-By: Claude` trailer in any commit (per project convention).
- This plan stays small (≈200 LoC additive) on purpose. If you find a fix that drifts off-scope (e.g. wanting to also fix `bulk_apply` undo), open a separate issue/PR — do not bundle.
