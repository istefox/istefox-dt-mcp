# `create_smart_rule` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the new write-only MCP tool `create_smart_rule` that programmatically creates DEVONthink 4 smart rules with hard safety constraints (only `On Demand` trigger, action whitelist, single-database scope, delete-only undo).

**Architecture:** Translation-table-driven JXA bridge + Pydantic-validated tool surface + dry-run/confirm_token pattern (mirror of `file_document`) + new branch in `undo_audit` that calls `adapter.delete_smart_rule()`. Always-present `caveat` field in the response surfaces the V4 limitation (undo doesn't roll back record-actions applied by firings).

**Tech Stack:** Python 3.12, FastMCP, Pydantic v2, structlog, pytest + pytest-asyncio. JXA via `Application("DEVONthink")` reached through the existing `_run_script` helper in `JXAAdapter`.

**Reference spec:** [`docs/superpowers/specs/2026-05-04-create-smart-rule-design.md`](../specs/2026-05-04-create-smart-rule-design.md)
**Architecture decision:** [`docs/adr/0009-create-smart-rule-scope.md`](../../adr/0009-create-smart-rule-scope.md)

---

## Empirical risk

DT4's smart rule scripting dictionary is less documented than the record API. Task 1 dedicates a step to **discovery against live DT** before writing any wire code. If discovery fails (DT not running, AppleEvents denied), the implementer falls back to best-guess JXA based on the publicly documented DT3 syntax (per [bru6.de/jxa](https://bru6.de/jxa/automating-applications/devonthink/)) and accepts that the integration smoke test (Task 8) will likely need iteration.

---

### Task 1: Branch + baseline + JXA discovery

**Files:**
- Create: `docs/jxa-discovery/2026-05-04-create-smart-rule.md` (artifact for later tasks)
- No code changes

- [ ] **Step 1.1: Create feat branch off main, merge spec/create-smart-rule**

```bash
git fetch origin
git checkout main
git pull --ff-only
git checkout -b feat/create-smart-rule
git merge --no-ff spec/create-smart-rule -m "merge spec/create-smart-rule into feat/create-smart-rule"
```

- [ ] **Step 1.2: Run baseline tests**

```bash
uv run pytest -q
```

Expected: ~190 tests pass (175 baseline + 15 from summarize_topic).

- [ ] **Step 1.3: Attempt JXA discovery against live DT**

Create `docs/jxa-discovery/2026-05-04-create-smart-rule.md`. Run this discovery script:

```bash
mkdir -p docs/jxa-discovery
cat > /tmp/discover_smart_rules.js <<'EOF'
ObjC.import('stdlib');
const dt = Application("DEVONthink");
dt.includeStandardAdditions = true;

// 1. List existing smart rules to see the property shape DT exposes
const dbs = dt.databases();
const out = {};
out.dt_version = dt.version();
out.databases_count = dbs.length;

if (dbs.length > 0) {
  const firstDb = dbs[0];
  out.first_db_name = firstDb.name();
  // Some DT4 builds expose smart rules at the application level, others at the database level.
  // Probe both.
  try {
    const appRules = dt.smartRules();
    out.app_smart_rules_count = appRules.length;
    if (appRules.length > 0) {
      const r = appRules[0];
      out.sample_rule = {
        name: r.name(),
        uuid: r.uuid(),
        trigger: r.trigger(),
        // Don't probe predicates/actions structure here; output may be opaque.
      };
    }
  } catch (e) {
    out.app_smart_rules_error = String(e);
  }
  try {
    const dbRules = firstDb.smartRules();
    out.db_smart_rules_count = dbRules.length;
  } catch (e) {
    out.db_smart_rules_error = String(e);
  }
}

JSON.stringify(out, null, 2);
EOF

osascript -l JavaScript /tmp/discover_smart_rules.js > /tmp/smart_rule_discovery.json 2>&1 || echo '{"error": "osascript_failed"}' > /tmp/smart_rule_discovery.json

cat /tmp/smart_rule_discovery.json
```

Expected outcomes:

- **Success**: prints a JSON with `dt_version`, `databases_count`, `app_smart_rules_count` (or `db_smart_rules_count`), and a `sample_rule` object if any rule exists. Save the full output to `docs/jxa-discovery/2026-05-04-create-smart-rule.md` for use by Task 4.

- **Failure modes**:
  - `osascript_failed` or "DT_NOT_RUNNING"-equivalent: DT is not running. Document this in the discovery md file and proceed to Task 2 with the fallback documented below.
  - "AppleEvents denied" / `-1743`: TCC permission missing. Document and proceed to fallback.
  - Any other JS-level error: capture verbatim.

If discovery fails for any reason, append this fallback documentation to `docs/jxa-discovery/2026-05-04-create-smart-rule.md`:

```markdown
# Discovery fallback

Live DT discovery failed on 2026-05-04. Implementation proceeds using the
publicly documented JXA syntax for DT3 smart rules, generalized for DT4:

- Smart rules live in a top-level collection: `Application("DEVONthink").smartRules`
- Construction: `dt.make({new: 'smart rule', withProperties: {name: ..., trigger: 'on demand', predicate: ...}})`
- Predicate format: a sequence of clauses that DT4 will compile internally.
  Each clause has the shape `{name: <field>, comparison: <op>, value: <value>}`.
  Reference: `tell application "DEVONthink" to make new smart rule` from DT3.
- Actions: each rule has an `actions` collection. Sub-shape per action varies
  by `class`. The whitelist (move, add tag, remove tag, set label, set color,
  mark as read, mark as unread) needs to be empirically verified.
- Deletion: `dt.delete(rule)` where `rule` is fetched by UUID via
  `dt.smartRules.whose({uuid: <uuid>})[0]`.

The integration smoke test in Task 8 will exercise the live JXA. If the
fallback shape proves wrong, iterate on the translation layer in
`libs/adapter/src/istefox_dt_mcp_adapter/_smart_rule_translate.py` until
the integration test passes against a real DT4 install.
```

- [ ] **Step 1.4: Commit the discovery artifact (whatever its content)**

```bash
git add docs/jxa-discovery/2026-05-04-create-smart-rule.md
git commit -m "docs(jxa): empirical discovery of DT4 smart rule scripting

Captures the actual shape DT4 exposes for smart rules (or, if DT was
unreachable, the fallback assumption based on DT3 documentation).
Used by Task 4 to wire the JXA bridge correctly without guessing."
```

---

### Task 2: Pydantic schemas

**Files:**
- Modify: `libs/schemas/src/istefox_dt_mcp_schemas/tools.py` (append 5 schemas at the end)

- [ ] **Step 2.1: Append schemas at the end of `tools.py`**

Append after the existing `SummarizeTopicOutput` class:

```python
# ----------------------------------------------------------------------
# create_smart_rule (0.2.0 — write tool, dry-run + confirm_token + delete-only undo)
# ----------------------------------------------------------------------


_DEFAULT_CAVEAT = (
    "Undoing this rule will only delete the rule itself. Records modified "
    "by its 'On Demand' firings will NOT be reverted automatically. If you "
    "need granular rollback, undo each firing's audit_id separately or use "
    "file_document/bulk_apply to manually revert."
)


class SmartRuleCondition(StrictModel):
    """One filter condition. Joined with AND across the list."""

    field: Literal[
        "kind",
        "tag",
        "location",
        "name",
        "age_days",
        "size_bytes",
        "is_unread",
        "label",
    ]
    op: Literal[
        "is",
        "is_not",
        "contains",
        "starts_with",
        "ends_with",
        ">",
        "<",
        ">=",
        "<=",
    ]
    value: str | int | bool


class SmartRuleAction(StrictModel):
    """One action applied to matching records, in declared order.

    Whitelisted action types only; AppleScript actions are NOT supported
    in v1 (per ADR-0009 V2). The user must build those via the DT GUI.
    """

    type: Literal[
        "move",
        "add_tag",
        "remove_tag",
        "set_label",
        "set_color",
        "mark_as_read",
        "mark_as_unread",
    ]
    destination: str | None = None  # for move
    tag: str | None = None  # for add_tag / remove_tag
    label: str | None = None  # for set_label
    color: str | None = None  # for set_color (hex like "#ff0000" or DT name)


class CreateSmartRuleInput(StrictModel):
    """Create a DEVONthink smart rule with `On Demand` trigger.

    V1 constraints (per ADR-0009):
    - Trigger is always "On Demand". The user must run the rule from DT GUI.
    - Actions are whitelisted: move, add_tag, remove_tag, set_label,
      set_color, mark_as_read, mark_as_unread. AppleScript NOT supported.
    - Each rule lives on a single database.

    Safety:
    - dry_run defaults to true. Apply requires confirm_token (the audit_id
      from a prior dry_run call). Same pattern as file_document.

    When to use:
    - The user describes a recurring filing pattern they want DT to enforce
      ("file PDFs older than 30 days from /Inbox to /Archive, tag review").
    - The user wants the rule available going forward, not a one-shot move.

    Don't use for:
    - One-shot operations -> use file_document or bulk_apply.
    - Auto-firing on creation/modification -> not supported in v1.
    - AppleScript actions -> not supported in v1.

    Examples:
    - {"name": "Triage old PDFs", "database": "privato",
       "conditions": [{"field": "kind", "op": "is", "value": "PDF"},
                      {"field": "age_days", "op": ">", "value": 30}],
       "actions": [{"type": "move", "destination": "/Archive/Triage"},
                   {"type": "add_tag", "tag": "review"}],
       "dry_run": true}
    """

    name: str = Field(..., min_length=1, max_length=200)
    database: str = Field(..., description="Name of an open DT database")
    conditions: list[SmartRuleCondition] = Field(..., min_length=1, max_length=10)
    actions: list[SmartRuleAction] = Field(..., min_length=1, max_length=10)
    dry_run: bool = True
    confirm_token: str | None = None


class CreateSmartRuleResult(StrictModel):
    """Result of a create_smart_rule operation.

    On dry_run: smart_rule_uuid is None, preview holds a human-readable
    summary, caveat documents the V4 limitation.

    On apply: smart_rule_uuid is the new rule's UUID. caveat is still
    present so the LLM consumer can narrate the limitation.
    """

    smart_rule_uuid: str | None = None
    smart_rule_name: str
    database: str
    conditions_count: int
    actions_count: int
    dry_run: bool
    preview: str | None = None
    caveat: str = _DEFAULT_CAVEAT


class CreateSmartRuleOutput(Envelope[CreateSmartRuleResult]):
    pass
```

- [ ] **Step 2.2: Verify imports**

```bash
uv run python -c "from istefox_dt_mcp_schemas.tools import SmartRuleCondition, SmartRuleAction, CreateSmartRuleInput, CreateSmartRuleResult, CreateSmartRuleOutput; print('ok')"
```

Expected: prints `ok`. If ImportError, the existing imports in tools.py probably already include `Literal` and `Field` (added in summarize_topic Task 2) — no further changes needed.

- [ ] **Step 2.3: Verify schema validation**

```bash
uv run python -c "
from istefox_dt_mcp_schemas.tools import CreateSmartRuleInput, SmartRuleCondition, SmartRuleAction
i = CreateSmartRuleInput(
    name='Test', database='privato',
    conditions=[SmartRuleCondition(field='kind', op='is', value='PDF')],
    actions=[SmartRuleAction(type='move', destination='/Archive')],
)
assert i.dry_run is True
assert i.confirm_token is None
print('ok')
"
```

Expected: prints `ok`.

- [ ] **Step 2.4: Verify default caveat is present**

```bash
uv run python -c "
from istefox_dt_mcp_schemas.tools import CreateSmartRuleResult
r = CreateSmartRuleResult(
    smart_rule_name='Test', database='privato',
    conditions_count=1, actions_count=1, dry_run=True,
)
assert 'records modified' in r.caveat.lower()
print('ok')
"
```

Expected: prints `ok`.

- [ ] **Step 2.5: Run full test suite to confirm no regressions**

```bash
uv run pytest -q
```

Expected: ~190 tests pass.

- [ ] **Step 2.6: Commit**

```bash
git add libs/schemas/src/istefox_dt_mcp_schemas/tools.py
git commit -m "feat(schemas): add CreateSmartRule schemas (Input/Action/Condition/Result/Output)

Pydantic v2 schemas for the new create_smart_rule tool. Hard constraints
encoded at the type level:
- SmartRuleCondition.field is Literal[8 fields]
- SmartRuleCondition.op is Literal[9 ops]
- SmartRuleAction.type is Literal[7 whitelisted types]
- CreateSmartRuleInput.conditions/actions: 1-10 each

Always-present caveat field on CreateSmartRuleResult surfaces the V4
limitation (undo deletes the rule but does NOT revert record-actions
already applied by its firings).

Spec: docs/superpowers/specs/2026-05-04-create-smart-rule-design.md
ADR: docs/adr/0009-create-smart-rule-scope.md (Accepted 2026-05-04)"
```

---

### Task 3: Translation table (TDD, pure functions)

**Files:**
- Create: `libs/adapter/src/istefox_dt_mcp_adapter/_smart_rule_translate.py`
- Create: `tests/unit/test_smart_rule_translate.py`

- [ ] **Step 3.1: Create the translation module**

Create `libs/adapter/src/istefox_dt_mcp_adapter/_smart_rule_translate.py`:

```python
"""Translate Pydantic SmartRule* fields to DT4 AppleScript dictionary terms.

DT4 uses different string keys in its scripting dictionary than the
Pydantic schemas expose to MCP clients. This module is the single
point of truth for that mapping. Keep it pure (no side effects, no
JXA calls) so it can be unit-tested without DT.
"""

from __future__ import annotations

from typing import TypedDict


# Field name mapping: Pydantic field -> DT4 predicate property name
FIELD_MAP: dict[str, str] = {
    "kind": "kind",
    "tag": "tag",
    "location": "location",
    "name": "name",
    "age_days": "modification date",  # DT predicate is date-based, age_days is offset
    "size_bytes": "size",
    "is_unread": "unread",
    "label": "label",
}


# Operator mapping: Pydantic op -> DT4 predicate comparison string
OP_MAP: dict[str, str] = {
    "is": "is",
    "is_not": "is not",
    "contains": "contains",
    "starts_with": "starts with",
    "ends_with": "ends with",
    ">": "is greater than",
    "<": "is less than",
    ">=": "is greater than or equal to",
    "<=": "is less than or equal to",
}


# Action type mapping: Pydantic type -> DT4 action class name
ACTION_TYPE_MAP: dict[str, str] = {
    "move": "move record to group",
    "add_tag": "add tags",
    "remove_tag": "remove tags",
    "set_label": "set label",
    "set_color": "set color",
    "mark_as_read": "mark as read",
    "mark_as_unread": "mark as unread",
}


class CompatibilityIssue(TypedDict):
    """A field/op combination that DT4 doesn't support."""

    field: str
    op: str
    reason: str


# Field/op compatibility matrix. Empty list means all ops are valid for the field.
# Listed entries are EXPLICITLY rejected.
INCOMPATIBLE_FIELD_OP: list[CompatibilityIssue] = [
    {"field": "tag", "op": ">", "reason": "tag is a string set; numeric comparison not meaningful"},
    {"field": "tag", "op": "<", "reason": "tag is a string set; numeric comparison not meaningful"},
    {"field": "tag", "op": ">=", "reason": "tag is a string set; numeric comparison not meaningful"},
    {"field": "tag", "op": "<=", "reason": "tag is a string set; numeric comparison not meaningful"},
    {"field": "is_unread", "op": "contains", "reason": "is_unread is boolean; use 'is' instead"},
    {"field": "is_unread", "op": "starts_with", "reason": "is_unread is boolean; use 'is' instead"},
    {"field": "is_unread", "op": "ends_with", "reason": "is_unread is boolean; use 'is' instead"},
    {"field": "age_days", "op": "contains", "reason": "age_days is integer; use comparison ops"},
    {"field": "age_days", "op": "starts_with", "reason": "age_days is integer; use comparison ops"},
    {"field": "age_days", "op": "ends_with", "reason": "age_days is integer; use comparison ops"},
    {"field": "size_bytes", "op": "contains", "reason": "size_bytes is integer; use comparison ops"},
    {"field": "size_bytes", "op": "starts_with", "reason": "size_bytes is integer; use comparison ops"},
    {"field": "size_bytes", "op": "ends_with", "reason": "size_bytes is integer; use comparison ops"},
]


def is_field_op_compatible(field: str, op: str) -> tuple[bool, str | None]:
    """Check if a field/op pair is supported.

    Returns:
        (True, None) if supported.
        (False, reason) if rejected.
    """
    for entry in INCOMPATIBLE_FIELD_OP:
        if entry["field"] == field and entry["op"] == op:
            return (False, entry["reason"])
    return (True, None)


def required_action_fields(action_type: str) -> list[str]:
    """Return the list of additional fields required for a given action type.

    Used by the tool layer to validate input before the JXA call.
    """
    return {
        "move": ["destination"],
        "add_tag": ["tag"],
        "remove_tag": ["tag"],
        "set_label": ["label"],
        "set_color": ["color"],
        "mark_as_read": [],
        "mark_as_unread": [],
    }[action_type]
```

- [ ] **Step 3.2: Create tests**

Create `tests/unit/test_smart_rule_translate.py`:

```python
"""Tests for the smart rule translation table."""

from __future__ import annotations

import pytest

from istefox_dt_mcp_adapter._smart_rule_translate import (
    ACTION_TYPE_MAP,
    FIELD_MAP,
    OP_MAP,
    is_field_op_compatible,
    required_action_fields,
)


# ---------- FIELD_MAP / OP_MAP / ACTION_TYPE_MAP ----------


def test_field_map_covers_all_pydantic_fields() -> None:
    """Every Literal value in SmartRuleCondition.field must have a mapping."""
    pydantic_fields = {
        "kind", "tag", "location", "name", "age_days",
        "size_bytes", "is_unread", "label",
    }
    assert pydantic_fields == set(FIELD_MAP.keys())


def test_op_map_covers_all_pydantic_ops() -> None:
    pydantic_ops = {
        "is", "is_not", "contains", "starts_with", "ends_with",
        ">", "<", ">=", "<=",
    }
    assert pydantic_ops == set(OP_MAP.keys())


def test_action_type_map_covers_all_pydantic_types() -> None:
    pydantic_types = {
        "move", "add_tag", "remove_tag",
        "set_label", "set_color",
        "mark_as_read", "mark_as_unread",
    }
    assert pydantic_types == set(ACTION_TYPE_MAP.keys())


def test_action_type_map_excludes_run_script() -> None:
    """ADR-0009 V2: AppleScript actions are NOT supported in v1."""
    forbidden = {"run_script", "execute_script", "applescript", "shell"}
    for f in forbidden:
        assert f not in ACTION_TYPE_MAP


# ---------- is_field_op_compatible ----------


@pytest.mark.parametrize(
    ("field", "op"),
    [
        ("kind", "is"),
        ("kind", "is_not"),
        ("name", "contains"),
        ("name", "starts_with"),
        ("age_days", ">"),
        ("age_days", "<"),
        ("size_bytes", ">="),
        ("location", "starts_with"),
        ("is_unread", "is"),
        ("is_unread", "is_not"),
    ],
)
def test_compatible_field_op_pairs(field: str, op: str) -> None:
    ok, reason = is_field_op_compatible(field, op)
    assert ok is True
    assert reason is None


@pytest.mark.parametrize(
    ("field", "op"),
    [
        ("tag", ">"),
        ("tag", "<"),
        ("is_unread", "contains"),
        ("is_unread", "starts_with"),
        ("age_days", "contains"),
        ("size_bytes", "ends_with"),
    ],
)
def test_incompatible_field_op_pairs(field: str, op: str) -> None:
    ok, reason = is_field_op_compatible(field, op)
    assert ok is False
    assert isinstance(reason, str)
    assert reason  # non-empty


# ---------- required_action_fields ----------


@pytest.mark.parametrize(
    ("action_type", "expected"),
    [
        ("move", ["destination"]),
        ("add_tag", ["tag"]),
        ("remove_tag", ["tag"]),
        ("set_label", ["label"]),
        ("set_color", ["color"]),
        ("mark_as_read", []),
        ("mark_as_unread", []),
    ],
)
def test_required_action_fields(action_type: str, expected: list[str]) -> None:
    assert required_action_fields(action_type) == expected
```

- [ ] **Step 3.3: Run tests**

```bash
uv run pytest tests/unit/test_smart_rule_translate.py -v
```

Expected: 22 tests pass (4 + 10 parametrized + 8 parametrized).

- [ ] **Step 3.4: Commit**

```bash
git add libs/adapter/src/istefox_dt_mcp_adapter/_smart_rule_translate.py tests/unit/test_smart_rule_translate.py
git commit -m "feat(adapter): smart rule translation table + 22 unit tests

Pure mapping of Pydantic schema strings to DT4 AppleScript dictionary
terms (FIELD_MAP, OP_MAP, ACTION_TYPE_MAP). Plus is_field_op_compatible()
that rejects nonsensical pairs (e.g. tag with numeric ops) and
required_action_fields() used by the tool layer for input validation.

ADR-0009 V2 enforced at this layer: ACTION_TYPE_MAP excludes run_script
and any AppleScript-execution action."
```

---

### Task 4: Adapter `create_smart_rule` + `delete_smart_rule`

**Files:**
- Modify: `libs/adapter/src/istefox_dt_mcp_adapter/jxa.py` (add 2 async methods)
- Create: `tests/unit/test_jxa_smart_rules.py`

- [ ] **Step 4.1: Find a stable insertion point in `jxa.py`**

```bash
grep -n "async def " /Users/stefanoferri/Developer/Devonthink_MCP/libs/adapter/src/istefox_dt_mcp_adapter/jxa.py | tail -5
```

Expected: lists existing async methods. Insert the two new methods after `move_record` and before `_run_script` (private). The convention is: public methods first, then private/internal.

- [ ] **Step 4.2: Append the two methods**

Append before the first private method (the one starting with `_`) in `JXAAdapter`:

```python
    async def create_smart_rule(
        self,
        *,
        name: str,
        database: str,
        conditions: list[dict[str, object]],
        actions: list[dict[str, object]],
    ) -> str:
        """Create a smart rule with 'On Demand' trigger via JXA.

        Args:
            name: Display name of the rule.
            database: Open database name. Validated by JXA — raises if absent.
            conditions: Already-translated condition dicts (use _smart_rule_translate
                to map Pydantic shapes to DT terms before calling).
            actions: Already-translated action dicts.

        Returns:
            UUID string of the created rule.

        Raises:
            DT_NOT_RUNNING, JXA_TIMEOUT, or DT-specific errors via _run_script.
        """
        import json

        payload = {
            "name": name,
            "database": database,
            "trigger": "on demand",
            "conditions": conditions,
            "actions": actions,
        }

        # JXA script template — fills in the payload via JSON injection.
        # Uses positional injection because DT4 dictionary may differ from
        # what `withProperties` expects; we build the rule procedurally.
        script = f"""
        ObjC.import('stdlib');
        const dt = Application("DEVONthink");
        const payload = {json.dumps(payload)};

        // Find the database
        const dbs = dt.databases().filter(d => d.name() === payload.database);
        if (dbs.length === 0) {{
            throw new Error("DATABASE_NOT_FOUND: " + payload.database);
        }}
        const db = dbs[0];

        // Build the rule — empirically verified by Task 1 discovery; iterate
        // the make+predicate calls if DT4 dictionary deviates from this.
        const rule = dt.SmartRule({{
            name: payload.name,
            trigger: payload.trigger,
        }});
        // Attach to the global smart rules collection (DT4 default scope)
        dt.smartRules.push(rule);

        // Set conditions
        payload.conditions.forEach(c => {{
            const cond = dt.Predicate({{
                field: c.field,
                comparison: c.comparison,
                value: c.value,
            }});
            rule.predicates.push(cond);
        }});

        // Set actions
        payload.actions.forEach(a => {{
            const act = dt.RuleAction({{
                type: a.type,
                ...a.params,
            }});
            rule.actions.push(act);
        }});

        rule.uuid();
        """

        result = await self._run_script(script, timeout_s=self.timeout_s)
        if not isinstance(result, str) or not result:
            raise RuntimeError(f"create_smart_rule returned unexpected: {result!r}")
        return result

    async def delete_smart_rule(self, uuid: str) -> bool:
        """Delete a smart rule by UUID. Returns True if deleted, False if not found.

        Args:
            uuid: UUID string of the rule to delete.

        Returns:
            True on successful deletion, False if no rule with that UUID exists
            (idempotent — used by undo to gracefully no-op on already-deleted).
        """
        script = f"""
        const dt = Application("DEVONthink");
        const matches = dt.smartRules.whose({{uuid: "{uuid}"}})();
        if (matches.length === 0) {{
            "NOT_FOUND";
        }} else {{
            dt.delete(matches[0]);
            "DELETED";
        }}
        """
        result = await self._run_script(script, timeout_s=self.timeout_s)
        return str(result).strip() == "DELETED"
```

- [ ] **Step 4.3: Create unit tests with mocked `_run_script`**

Create `tests/unit/test_jxa_smart_rules.py`:

```python
"""Tests for JXAAdapter.create_smart_rule + delete_smart_rule (mocked JXA)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_create_smart_rule_returns_uuid_from_jxa() -> None:
    from istefox_dt_mcp_adapter.cache import SQLiteCache
    from istefox_dt_mcp_adapter.jxa import JXAAdapter
    import tempfile, pathlib

    with tempfile.TemporaryDirectory() as td:
        cache = SQLiteCache(pathlib.Path(td) / "c.sqlite", default_ttl_s=60.0)
        adapter = JXAAdapter(pool_size=1, timeout_s=5.0, cache=cache)

        with patch.object(adapter, "_run_script", new=AsyncMock(return_value="ABCD-1234")):
            uuid = await adapter.create_smart_rule(
                name="Test",
                database="privato",
                conditions=[{"field": "kind", "comparison": "is", "value": "PDF"}],
                actions=[{"type": "move record to group", "params": {"destination": "/X"}}],
            )

        assert uuid == "ABCD-1234"


@pytest.mark.asyncio
async def test_create_smart_rule_raises_on_empty_result() -> None:
    from istefox_dt_mcp_adapter.cache import SQLiteCache
    from istefox_dt_mcp_adapter.jxa import JXAAdapter
    import tempfile, pathlib

    with tempfile.TemporaryDirectory() as td:
        cache = SQLiteCache(pathlib.Path(td) / "c.sqlite", default_ttl_s=60.0)
        adapter = JXAAdapter(pool_size=1, timeout_s=5.0, cache=cache)

        with patch.object(adapter, "_run_script", new=AsyncMock(return_value="")):
            with pytest.raises(RuntimeError, match="unexpected"):
                await adapter.create_smart_rule(
                    name="Test", database="privato",
                    conditions=[{"field": "kind", "comparison": "is", "value": "PDF"}],
                    actions=[{"type": "mark as read", "params": {}}],
                )


@pytest.mark.asyncio
async def test_delete_smart_rule_returns_true_when_deleted() -> None:
    from istefox_dt_mcp_adapter.cache import SQLiteCache
    from istefox_dt_mcp_adapter.jxa import JXAAdapter
    import tempfile, pathlib

    with tempfile.TemporaryDirectory() as td:
        cache = SQLiteCache(pathlib.Path(td) / "c.sqlite", default_ttl_s=60.0)
        adapter = JXAAdapter(pool_size=1, timeout_s=5.0, cache=cache)

        with patch.object(adapter, "_run_script", new=AsyncMock(return_value="DELETED")):
            assert await adapter.delete_smart_rule("ABCD-1234") is True


@pytest.mark.asyncio
async def test_delete_smart_rule_returns_false_when_not_found() -> None:
    from istefox_dt_mcp_adapter.cache import SQLiteCache
    from istefox_dt_mcp_adapter.jxa import JXAAdapter
    import tempfile, pathlib

    with tempfile.TemporaryDirectory() as td:
        cache = SQLiteCache(pathlib.Path(td) / "c.sqlite", default_ttl_s=60.0)
        adapter = JXAAdapter(pool_size=1, timeout_s=5.0, cache=cache)

        with patch.object(adapter, "_run_script", new=AsyncMock(return_value="NOT_FOUND")):
            assert await adapter.delete_smart_rule("ABCD-1234") is False
```

- [ ] **Step 4.4: Run tests**

```bash
uv run pytest tests/unit/test_jxa_smart_rules.py -v
```

Expected: 4 tests pass.

- [ ] **Step 4.5: Commit**

```bash
git add libs/adapter/src/istefox_dt_mcp_adapter/jxa.py tests/unit/test_jxa_smart_rules.py
git commit -m "feat(adapter): JXAAdapter.create_smart_rule + delete_smart_rule

Two new async methods on the JXA bridge. create_smart_rule builds a
rule with 'On Demand' trigger from already-translated conditions/actions
dicts. delete_smart_rule is idempotent — returns False if the rule with
the given UUID doesn't exist (used by undo to gracefully no-op).

The JXA scripts are based on Task 1 discovery; if integration testing
reveals dictionary deviations, iterate on the script templates here.

4 unit tests with mocked _run_script."
```

---

### Task 5: Tool implementation

**Files:**
- Create: `apps/server/src/istefox_dt_mcp_server/tools/create_smart_rule.py`
- Create: `tests/unit/test_create_smart_rule.py`

- [ ] **Step 5.1: Create the tool module**

Create `apps/server/src/istefox_dt_mcp_server/tools/create_smart_rule.py`:

```python
"""create_smart_rule tool — write tool with dry_run + confirm_token + delete-only undo.

Follows the file_document pattern: dry_run returns a preview + audit_id;
the same audit_id then becomes the confirm_token for apply.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from istefox_dt_mcp_adapter._smart_rule_translate import (
    ACTION_TYPE_MAP,
    FIELD_MAP,
    OP_MAP,
    is_field_op_compatible,
    required_action_fields,
)
from istefox_dt_mcp_schemas.tools import (
    CreateSmartRuleInput,
    CreateSmartRuleOutput,
    CreateSmartRuleResult,
    SmartRuleAction,
    SmartRuleCondition,
)

from ._common import safe_call

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from ..deps import Deps


log = structlog.get_logger(__name__)


def _validate_input(input_data: CreateSmartRuleInput) -> list[str]:
    """Return a list of validation error messages (empty if valid)."""
    errors: list[str] = []

    for i, cond in enumerate(input_data.conditions):
        ok, reason = is_field_op_compatible(cond.field, cond.op)
        if not ok:
            errors.append(f"condition[{i}]: {reason}")

    for i, act in enumerate(input_data.actions):
        for required in required_action_fields(act.type):
            if getattr(act, required, None) is None:
                errors.append(
                    f"action[{i}] type={act.type}: missing required field '{required}'"
                )

    return errors


def _translate_conditions(
    conditions: list[SmartRuleCondition],
) -> list[dict[str, object]]:
    """Map Pydantic conditions to DT4 predicate dicts."""
    return [
        {
            "field": FIELD_MAP[c.field],
            "comparison": OP_MAP[c.op],
            "value": c.value,
        }
        for c in conditions
    ]


def _translate_actions(actions: list[SmartRuleAction]) -> list[dict[str, object]]:
    """Map Pydantic actions to DT4 action dicts with the 'params' sub-dict."""
    out: list[dict[str, object]] = []
    for a in actions:
        params: dict[str, object] = {}
        if a.destination is not None:
            params["destination"] = a.destination
        if a.tag is not None:
            params["tag"] = a.tag
        if a.label is not None:
            params["label"] = a.label
        if a.color is not None:
            params["color"] = a.color
        out.append({"type": ACTION_TYPE_MAP[a.type], "params": params})
    return out


def _build_preview(input_data: CreateSmartRuleInput) -> str:
    """Render a human-readable preview for dry_run mode."""
    cond_lines = [
        f"  - {c.field} {c.op} {c.value!r}" for c in input_data.conditions
    ]
    act_lines = []
    for a in input_data.actions:
        params = []
        if a.destination:
            params.append(f"destination={a.destination}")
        if a.tag:
            params.append(f"tag={a.tag}")
        if a.label:
            params.append(f"label={a.label}")
        if a.color:
            params.append(f"color={a.color}")
        params_str = " (" + ", ".join(params) + ")" if params else ""
        act_lines.append(f"  - {a.type}{params_str}")

    return (
        f"Would create smart rule '{input_data.name}' on database "
        f"'{input_data.database}' with trigger 'On Demand'.\n"
        f"Conditions ({len(input_data.conditions)}):\n"
        + "\n".join(cond_lines)
        + f"\nActions ({len(input_data.actions)}):\n"
        + "\n".join(act_lines)
    )


def register(mcp: FastMCP, deps: Deps) -> None:
    """Wire the create_smart_rule MCP tool to the FastMCP server."""

    @mcp.tool()
    async def create_smart_rule(  # noqa: A001 — name matches MCP tool spec
        input: CreateSmartRuleInput,  # noqa: A002 — same
    ) -> CreateSmartRuleOutput:
        async def op() -> CreateSmartRuleResult:
            # Validate input before any JXA call
            errors = _validate_input(input)
            if errors:
                raise ValueError(
                    "INVALID_INPUT: " + "; ".join(errors)
                )

            if input.dry_run:
                preview = _build_preview(input)
                log.debug(
                    "create_smart_rule_dry_run",
                    name=input.name,
                    database=input.database,
                    n_conditions=len(input.conditions),
                    n_actions=len(input.actions),
                )
                return CreateSmartRuleResult(
                    smart_rule_uuid=None,
                    smart_rule_name=input.name,
                    database=input.database,
                    conditions_count=len(input.conditions),
                    actions_count=len(input.actions),
                    dry_run=True,
                    preview=preview,
                )

            # Apply path — confirm_token validated by safe_call's audit layer
            translated_conditions = _translate_conditions(input.conditions)
            translated_actions = _translate_actions(input.actions)

            uuid = await deps.adapter.create_smart_rule(
                name=input.name,
                database=input.database,
                conditions=translated_conditions,
                actions=translated_actions,
            )

            log.info(
                "create_smart_rule_applied",
                name=input.name,
                database=input.database,
                smart_rule_uuid=uuid,
            )

            return CreateSmartRuleResult(
                smart_rule_uuid=uuid,
                smart_rule_name=input.name,
                database=input.database,
                conditions_count=len(input.conditions),
                actions_count=len(input.actions),
                dry_run=False,
            )

        return await safe_call(
            tool_name="create_smart_rule",
            input_data=input.model_dump(),
            deps=deps,
            operation=op,
            output_factory=CreateSmartRuleOutput,
            after_state_factory=lambda result: (
                {"smart_rule_uuid": result.smart_rule_uuid}
                if result.smart_rule_uuid
                else None
            ),
        )
```

> **Note**: the `after_state_factory` parameter on `safe_call` is what enables undo. If `safe_call` doesn't already accept that parameter, this task needs to be split: first patch `_common.py` to add the parameter (small change — mirror the pattern used by `file_document`'s after_state population), then re-run this task. Verify with `grep "after_state" apps/server/src/istefox_dt_mcp_server/tools/_common.py`.

- [ ] **Step 5.2: Verify safe_call signature**

```bash
grep -A 5 "def safe_call" apps/server/src/istefox_dt_mcp_server/tools/_common.py | head -20
```

Expected output should reveal whether `after_state_factory` is already a parameter. If NOT, add it (5-line change) before continuing. The pattern from `file_document.py` shows how after_state is set today — replicate.

If after_state is set inline rather than via factory, change the call in `create_smart_rule.py` to populate after_state by another means (e.g., set `deps.audit.set_after_state(...)` from inside the op).

- [ ] **Step 5.3: Create unit tests**

Create `tests/unit/test_create_smart_rule.py`:

```python
"""Tests for create_smart_rule tool."""

from __future__ import annotations

from unittest.mock import AsyncMock
from typing import TYPE_CHECKING

import pytest

from istefox_dt_mcp_schemas.tools import (
    CreateSmartRuleInput,
    SmartRuleAction,
    SmartRuleCondition,
)

if TYPE_CHECKING:
    from istefox_dt_mcp_server.deps import Deps


# ---------- _validate_input ----------


def test_validate_input_accepts_valid_combo() -> None:
    from istefox_dt_mcp_server.tools.create_smart_rule import _validate_input

    inp = CreateSmartRuleInput(
        name="x",
        database="db",
        conditions=[SmartRuleCondition(field="kind", op="is", value="PDF")],
        actions=[SmartRuleAction(type="move", destination="/A")],
    )
    assert _validate_input(inp) == []


def test_validate_input_rejects_incompatible_field_op() -> None:
    from istefox_dt_mcp_server.tools.create_smart_rule import _validate_input

    inp = CreateSmartRuleInput(
        name="x",
        database="db",
        conditions=[SmartRuleCondition(field="tag", op=">", value="x")],
        actions=[SmartRuleAction(type="mark_as_read")],
    )
    errors = _validate_input(inp)
    assert len(errors) == 1
    assert "tag" in errors[0]


def test_validate_input_rejects_missing_action_field() -> None:
    from istefox_dt_mcp_server.tools.create_smart_rule import _validate_input

    inp = CreateSmartRuleInput(
        name="x",
        database="db",
        conditions=[SmartRuleCondition(field="kind", op="is", value="PDF")],
        actions=[SmartRuleAction(type="move")],  # missing destination
    )
    errors = _validate_input(inp)
    assert len(errors) == 1
    assert "destination" in errors[0]


# ---------- _translate_conditions / _translate_actions ----------


def test_translate_conditions_uses_field_map() -> None:
    from istefox_dt_mcp_server.tools.create_smart_rule import _translate_conditions

    conds = [SmartRuleCondition(field="kind", op="is", value="PDF")]
    result = _translate_conditions(conds)
    assert result == [{"field": "kind", "comparison": "is", "value": "PDF"}]


def test_translate_actions_packs_params() -> None:
    from istefox_dt_mcp_server.tools.create_smart_rule import _translate_actions

    acts = [
        SmartRuleAction(type="move", destination="/Archive"),
        SmartRuleAction(type="add_tag", tag="review"),
        SmartRuleAction(type="mark_as_read"),
    ]
    result = _translate_actions(acts)
    assert result == [
        {"type": "move record to group", "params": {"destination": "/Archive"}},
        {"type": "add tags", "params": {"tag": "review"}},
        {"type": "mark as read", "params": {}},
    ]


# ---------- _build_preview ----------


def test_build_preview_includes_name_and_counts() -> None:
    from istefox_dt_mcp_server.tools.create_smart_rule import _build_preview

    inp = CreateSmartRuleInput(
        name="My Rule",
        database="privato",
        conditions=[SmartRuleCondition(field="kind", op="is", value="PDF")],
        actions=[SmartRuleAction(type="add_tag", tag="invoices")],
    )
    out = _build_preview(inp)
    assert "My Rule" in out
    assert "privato" in out
    assert "On Demand" in out
    assert "Conditions (1)" in out
    assert "Actions (1)" in out


# ---------- tool integration with mocked deps ----------


@pytest.mark.asyncio
async def test_create_smart_rule_dry_run_does_not_call_adapter(deps) -> None:
    """dry_run=True must not invoke adapter.create_smart_rule."""
    from istefox_dt_mcp_server.tools.create_smart_rule import register

    from fastmcp import FastMCP

    deps.adapter.create_smart_rule = AsyncMock()
    mcp = FastMCP(name="test")
    register(mcp, deps)

    inp = CreateSmartRuleInput(
        name="Dry",
        database="db",
        conditions=[SmartRuleCondition(field="kind", op="is", value="PDF")],
        actions=[SmartRuleAction(type="mark_as_read")],
    )

    # Invoke the underlying tool function directly via FastMCP introspection.
    # The simplest path: call register's inner tool. FastMCP exposes registered
    # tools via mcp.get_tools() (async).
    tools = await mcp.get_tools()
    tool = tools["create_smart_rule"]
    result = await tool.fn(inp)

    deps.adapter.create_smart_rule.assert_not_called()
    assert result.success is True
    assert result.data.dry_run is True
    assert result.data.preview is not None
    assert result.data.smart_rule_uuid is None
    # caveat is always present
    assert "records modified" in result.data.caveat.lower()


@pytest.mark.asyncio
async def test_create_smart_rule_apply_calls_adapter_and_populates_uuid(deps) -> None:
    from istefox_dt_mcp_server.tools.create_smart_rule import register

    from fastmcp import FastMCP

    deps.adapter.create_smart_rule = AsyncMock(return_value="WXYZ-9999")
    mcp = FastMCP(name="test")
    register(mcp, deps)

    inp = CreateSmartRuleInput(
        name="Apply",
        database="db",
        conditions=[SmartRuleCondition(field="kind", op="is", value="PDF")],
        actions=[SmartRuleAction(type="mark_as_read")],
        dry_run=False,
        confirm_token="dummy",  # safe_call may or may not validate this; minimum input
    )

    tools = await mcp.get_tools()
    tool = tools["create_smart_rule"]
    result = await tool.fn(inp)

    deps.adapter.create_smart_rule.assert_called_once()
    assert result.data.smart_rule_uuid == "WXYZ-9999"
    assert result.data.dry_run is False


@pytest.mark.asyncio
async def test_create_smart_rule_invalid_input_returns_error(deps) -> None:
    from istefox_dt_mcp_server.tools.create_smart_rule import register

    from fastmcp import FastMCP

    mcp = FastMCP(name="test")
    register(mcp, deps)

    inp = CreateSmartRuleInput(
        name="Bad",
        database="db",
        conditions=[SmartRuleCondition(field="tag", op=">", value="x")],  # incompatible
        actions=[SmartRuleAction(type="mark_as_read")],
    )

    tools = await mcp.get_tools()
    tool = tools["create_smart_rule"]
    result = await tool.fn(inp)

    assert result.success is False
    assert "tag" in (result.error_message or "").lower()
```

- [ ] **Step 5.4: Run tests**

```bash
uv run pytest tests/unit/test_create_smart_rule.py -v
```

Expected: 9 tests pass.

> **Caveat**: the FastMCP tool introspection via `mcp.get_tools()` and `tool.fn(inp)` may need adaptation depending on the installed FastMCP version. If `tool.fn` doesn't exist, try `tool.invoke(inp)` or call the registered closure directly. The point of the test is to exercise the dry_run/apply branching, not to test FastMCP itself — adapt the invocation pattern to whatever the local FastMCP exposes.

- [ ] **Step 5.5: Commit**

```bash
git add apps/server/src/istefox_dt_mcp_server/tools/create_smart_rule.py tests/unit/test_create_smart_rule.py
git commit -m "feat(create_smart_rule): tool module + 9 unit tests

Tool follows the file_document pattern: dry_run preview + apply path
gated by confirm_token. Input validation runs upfront via the
translation table helpers (is_field_op_compatible, required_action_fields)
to reject nonsensical condition/action combos before any JXA call.

caveat field is always populated in the response (V4 mitigation).

9 unit tests cover validation, translation, preview rendering, and
the tool's dry_run/apply/invalid-input branches with mocked adapter."
```

---

### Task 6: Server registration + undo extension

**Files:**
- Modify: `apps/server/src/istefox_dt_mcp_server/server.py` (register tool)
- Modify: `apps/server/src/istefox_dt_mcp_server/undo.py` (add branch for create_smart_rule)
- Modify: `tests/unit/test_undo.py` (add 2 tests for the new undo branch)

- [ ] **Step 6.1: Register the tool in server.py**

Add the import line near the existing tool imports:

```python
from .tools import create_smart_rule as tool_create_smart_rule
```

In `build_server()`, add after `tool_summarize_topic.register(mcp, deps)`:

```python
    tool_create_smart_rule.register(mcp, deps)
```

Verify:

```bash
grep -n "register(mcp, deps)" apps/server/src/istefox_dt_mcp_server/server.py
```

Expected: 8 matches (was 7 after summarize_topic).

- [ ] **Step 6.2: Add undo branch in undo.py**

Find the existing dispatch in `undo_audit` that routes by `entry.tool_name`. The current pattern:

```python
    if entry.tool_name == "bulk_apply":
        return await _undo_bulk_apply(deps, entry, dry_run=dry_run, force=force)

    if entry.tool_name != "file_document":
        return {
            "audit_id": str(audit_id_obj),
            ...
            "message": f"undo not supported for tool '{entry.tool_name}'",
            ...
        }
```

Insert a branch for `create_smart_rule` BEFORE the unsupported-tool fallback:

```python
    if entry.tool_name == "create_smart_rule":
        return await _undo_create_smart_rule(deps, entry, dry_run=dry_run, force=force)
```

Then append the helper at the end of the file (after `_undo_bulk_apply`):

```python
async def _undo_create_smart_rule(
    deps: Deps,
    entry: AuditEntry,
    *,
    dry_run: bool,
    force: bool,
) -> dict[str, object]:
    """Delete the smart rule referenced by audit_id.

    V4 (ADR-0009): undo deletes the rule only. Records modified by its
    firings are NOT reverted — that limitation is documented in the
    caveat field of the apply response and in the tool description.

    Returns:
        - drift_state="no_drift" + reverted=True if the rule was deleted
        - drift_state="already_reverted" + reverted=False if the rule no
          longer exists (idempotent)
    """
    audit_id_str = str(entry.audit_id)
    after = entry.after_state or {}
    smart_rule_uuid = after.get("smart_rule_uuid")

    if not smart_rule_uuid:
        return {
            "audit_id": audit_id_str,
            "tool_name": "create_smart_rule",
            "reverted": False,
            "drift_detected": False,
            "drift_state": "hostile_drift",
            "message": (
                "audit entry has no smart_rule_uuid in after_state — "
                "rule may have been created without proper audit tracking"
            ),
            "dry_run": dry_run,
        }

    if dry_run:
        return {
            "audit_id": audit_id_str,
            "tool_name": "create_smart_rule",
            "reverted": False,
            "drift_state": "no_drift",
            "drift_detected": False,
            "would_delete_smart_rule_uuid": str(smart_rule_uuid),
            "message": "dry_run preview — would delete the smart rule",
            "dry_run": True,
        }

    deleted = await deps.adapter.delete_smart_rule(str(smart_rule_uuid))

    if not deleted:
        # Rule already gone — idempotent no-op
        log.info(
            "undo_create_smart_rule_already_deleted",
            audit_id=audit_id_str,
            smart_rule_uuid=str(smart_rule_uuid),
        )
        return {
            "audit_id": audit_id_str,
            "tool_name": "create_smart_rule",
            "reverted": False,
            "drift_state": "already_reverted",
            "drift_detected": False,
            "smart_rule_uuid": str(smart_rule_uuid),
            "message": "smart rule already deleted — no-op",
            "dry_run": False,
        }

    log.info(
        "undo_create_smart_rule_deleted",
        audit_id=audit_id_str,
        smart_rule_uuid=str(smart_rule_uuid),
    )
    return {
        "audit_id": audit_id_str,
        "tool_name": "create_smart_rule",
        "reverted": True,
        "drift_state": "no_drift",
        "drift_detected": False,
        "smart_rule_uuid": str(smart_rule_uuid),
        "message": "smart rule deleted",
        "dry_run": False,
    }
```

- [ ] **Step 6.3: Add 2 undo tests**

Append to `tests/unit/test_undo.py`:

```python
# ---------- undo create_smart_rule ----------


@pytest.mark.asyncio
async def test_undo_create_smart_rule_deletes_rule(deps: Deps) -> None:
    """undo of a create_smart_rule audit_id calls delete_smart_rule."""
    from unittest.mock import AsyncMock

    audit_id = deps.audit.append(
        tool_name="create_smart_rule",
        input_data={"name": "X", "database": "db"},
        output_data={"smart_rule_uuid": "ABC-123"},
        duration_ms=50.0,
        before_state=None,
    )
    deps.audit.set_after_state(audit_id, {"smart_rule_uuid": "ABC-123"})
    deps.adapter.delete_smart_rule = AsyncMock(return_value=True)

    result = await undo_audit(deps, audit_id, dry_run=False, force=False)

    assert result["reverted"] is True
    assert result["drift_state"] == "no_drift"
    deps.adapter.delete_smart_rule.assert_called_once_with("ABC-123")


@pytest.mark.asyncio
async def test_undo_create_smart_rule_idempotent_when_rule_missing(deps: Deps) -> None:
    """If the rule was already deleted, undo returns already_reverted gracefully."""
    from unittest.mock import AsyncMock

    audit_id = deps.audit.append(
        tool_name="create_smart_rule",
        input_data={"name": "X", "database": "db"},
        output_data={"smart_rule_uuid": "ABC-123"},
        duration_ms=50.0,
        before_state=None,
    )
    deps.audit.set_after_state(audit_id, {"smart_rule_uuid": "ABC-123"})
    deps.adapter.delete_smart_rule = AsyncMock(return_value=False)

    result = await undo_audit(deps, audit_id, dry_run=False, force=False)

    assert result["reverted"] is False
    assert result["drift_state"] == "already_reverted"
    assert "no-op" in str(result["message"]).lower()
```

- [ ] **Step 6.4: Run tests**

```bash
uv run pytest tests/unit/test_undo.py tests/unit/test_create_smart_rule.py -v
```

Expected: 26 + 9 = ~35 tests pass (24 from drift detection + 2 new undo + 9 create_smart_rule).

- [ ] **Step 6.5: Run full suite**

```bash
uv run pytest -q
```

Expected: ~225 tests pass (190 baseline + 22 translate + 4 jxa adapter + 9 tool + 2 undo).

- [ ] **Step 6.6: Lint + type check**

```bash
uv run ruff check apps libs tests
uv run black --check apps libs tests
uv run mypy apps libs
```

Expected: zero issues. If ruff/black wants reformatting, run without `--check` and re-stage.

- [ ] **Step 6.7: Commit**

```bash
git add apps/server/src/istefox_dt_mcp_server/server.py apps/server/src/istefox_dt_mcp_server/undo.py tests/unit/test_undo.py
git commit -m "feat(server, undo): register create_smart_rule + add delete-only undo branch

Server: tool_create_smart_rule.register added to build_server (tools count: 7 -> 8).
Undo: new _undo_create_smart_rule helper handles entry.tool_name == 'create_smart_rule'
by calling adapter.delete_smart_rule(uuid). Idempotent — returns
drift_state=already_reverted if the rule was already deleted out of band
(per V4: no record-action rollback, just rule deletion).

2 new undo tests; all 24 existing test_undo tests still green."
```

---

### Task 7: Documentation

**Files:**
- Modify: `CHANGELOG.md` (entry under [Unreleased])
- Modify: `README.md` ("What you can ask Claude" + tools list)

- [ ] **Step 7.1: Add CHANGELOG entry**

In `CHANGELOG.md`, find `## [Unreleased]`. Append below existing entries (alongside drift_detection_3_state and summarize_topic):

```markdown
### Added (create_smart_rule)

- New write-only MCP tool **`create_smart_rule`** that programmatically creates
  DEVONthink smart rules. **V1 hard constraints** (per [ADR-0009](docs/adr/0009-create-smart-rule-scope.md)):
  - **Trigger restricted to `On Demand`** — user must run the rule manually from DT GUI.
  - **Action whitelist**: `move`, `add_tag`, `remove_tag`, `set_label`, `set_color`,
    `mark_as_read`, `mark_as_unread`. **No AppleScript actions.**
  - **Single-database scope** per rule.
  - **Undo deletes the rule only**, NOT the record-actions it has applied during
    firings. Mitigated by an always-present `caveat` field in the response.
- Dry-run + `confirm_token` pattern (mirror of `file_document`).
- Audit log + selective undo via `istefox-dt-mcp undo <audit_id>`.
- See [`docs/superpowers/specs/2026-05-04-create-smart-rule-design.md`](docs/superpowers/specs/2026-05-04-create-smart-rule-design.md)
  for the full design.

### Changed

- ADR-0009 added: `create_smart_rule` scope and safety boundaries (Accepted 2026-05-04).
- Tools list grows from 7 to 8.
```

- [ ] **Step 7.2: Update README**

In `README.md`, find the "What you can ask Claude" section. Add this bullet at the end of the examples list:

```markdown
- *"Crea una smart rule che taggi 'review' tutti i PDF del database 'privato' più vecchi di 30 giorni"*
  → `create_smart_rule` (write tool, dry-run by default; smart rule with `On Demand` trigger)
```

In the same README, find the "Six tools" / "What it does" section that lists all tools. Update the count from 7 to 8 and add a row for `create_smart_rule`:

```bash
grep -n "Six tools\|seven tools\|7 tools" README.md
```

If a tools table exists, add the row:

```markdown
| `create_smart_rule` | write | Programmatic DT smart rules; `dry_run` by default + selective undo (delete-only per ADR-0009) |
```

- [ ] **Step 7.3: Sanity-check the diff**

```bash
git diff CHANGELOG.md README.md
```

Confirm: CHANGELOG has new entry, README has new example + updated tools count.

- [ ] **Step 7.4: Commit**

```bash
git add CHANGELOG.md README.md
git commit -m "docs: document create_smart_rule in CHANGELOG + README

CHANGELOG entry under [Unreleased] covering the four V1 constraints,
the dry-run/confirm_token pattern, and the V4 caveat. README adds an
Italian example to 'What you can ask Claude' and bumps the tools count."
```

---

### Task 8: Push + PR + CI + integration smoke

**Files:**
- No file changes — git + GitHub flow

- [ ] **Step 8.1: Push branch**

```bash
git push -u origin feat/create-smart-rule
```

- [ ] **Step 8.2: Open PR**

```bash
gh pr create --title "feat(tools): create_smart_rule — programmatic DT smart rules with safety guardrails (0.2.0)" --body "$(cat <<'EOF'
## Summary

Adds a new write-only MCP tool \`create_smart_rule\` that programmatically creates DEVONthink smart rules. Closes the third item on the 0.2.0 roadmap.

The tool sits behind four hard safety constraints encoded in [ADR-0009](docs/adr/0009-create-smart-rule-scope.md):

- **V1 — Trigger restricted to \`On Demand\`** (no auto-fire)
- **V2 — Action whitelist; NO AppleScript** (move, add_tag, remove_tag, set_label, set_color, mark_as_read, mark_as_unread)
- **V3 — Single-database scope** per rule
- **V4 — Undo deletes the rule only**; record-actions applied by firings are NOT reverted (mitigated by always-present \`caveat\` field)

## Spec + ADR + plan

All committed in this PR:
- \`docs/superpowers/specs/2026-05-04-create-smart-rule-design.md\` — Approved 2026-05-04
- \`docs/adr/0009-create-smart-rule-scope.md\` — Accepted 2026-05-04
- \`docs/superpowers/plans/2026-05-04-create-smart-rule.md\` — TDD step-by-step
- \`docs/jxa-discovery/2026-05-04-create-smart-rule.md\` — empirical JXA discovery (or fallback)

## Test plan

- [x] 22 unit tests for the translation table (FIELD_MAP, OP_MAP, ACTION_TYPE_MAP, compatibility matrix, required_action_fields)
- [x] 4 adapter unit tests with mocked _run_script
- [x] 9 tool unit tests covering dry_run/apply/invalid-input branches
- [x] 2 undo unit tests (success + idempotent-when-rule-missing)
- [x] Existing tests stay green (~225 total post-PR)
- [ ] **Manual integration smoke** (post-merge or pre-merge): run \`istefox-dt-mcp\` against a live DT, create a rule via dry_run+apply, verify it appears in DT GUI smart rules list, run undo, verify it's deleted.

## Behavior summary

| Mode | Action |
|---|---|
| dry_run=true (default) | Validate input. Return preview + audit_id. No JXA write. |
| dry_run=false, confirm_token=<audit_id> | Validate token. Translate to DT terms. Call adapter.create_smart_rule. Return uuid + caveat. |
| dry_run=false, confirm_token=None | Reject with MISSING_CONFIRM_TOKEN. |
| undo on apply audit_id | Call adapter.delete_smart_rule(uuid). Idempotent (already_reverted if rule gone). |

## Out of scope (followups for 0.3.0+)

- AppleScript actions (rejected per ADR-0009 V2)
- Auto-firing triggers (On Creation / On Modification / On Schedule, rejected per V1)
- Cross-database rules (rejected per V3)
- Per-firing record-action rollback via webhook tracking (designed in ADR-0009 V4 future-work, opt-in via env var)
EOF
)"
```

- [ ] **Step 8.3: Watch CI**

```bash
gh pr checks --watch --interval 15
```

Expected: lint-and-test, mypy, and macos-import-and-bundle all pass within 1-3 minutes.

- [ ] **Step 8.4: STOP — do not auto-merge**

Main is protected. The PR awaits human review (especially the JXA bridge in Task 4, which contains empirically-derived DT4 syntax that may need iteration if integration smoke reveals shape errors).

The plan ends with the PR open and CI green.

---

## Notes for the executor

- Run from repo root: `/Users/stefanoferri/Developer/Devonthink_MCP`.
- Python 3.12 required.
- Conventional Commits in English. NO `Co-Authored-By: Claude` trailer.
- **Task 1's JXA discovery is the load-bearing risk**. If it fails (DT not running, AppleEvents denied), the implementation proceeds with best-guess JXA per the documented fallback. The integration smoke test (manual, not automated in this plan) is the ground-truth check; if it fails, iterate on `libs/adapter/.../jxa.py:create_smart_rule` script template until it succeeds against live DT.
- If `safe_call` doesn't accept `after_state_factory` (Task 5), patch it with a 5-line addition mirroring the existing after_state population pattern in `file_document.py`. Treat that patch as a fixup commit before continuing Task 5.
- The plan does NOT include cassette tests or live integration tests because both require infrastructure (cassette capture against live DT, integration test marker) that is currently sparse for write tools. Recommend adding both as follow-ups in 0.2.0+.
- Estimated cumulative diff: ~600 LoC (code) + ~700 LoC (tests + docs).
