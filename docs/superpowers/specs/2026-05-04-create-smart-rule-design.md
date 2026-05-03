# `create_smart_rule` Tool — Design Spec

- **Status**: **DRAFT** — pending user review of ADR-0009
- **Target version**: 0.2.0 (after `summarize_topic` lands)
- **Owner**: istefox
- **Scope**: new write-only MCP tool that programmatically creates DEVONthink smart rules
- **Out of scope**: editing/deleting existing rules (delete is the undo path; explicit edit is 0.3.0+), AppleScript-based actions, scheduled triggers
- **Architecture decision**: see [ADR-0009](../../adr/0009-create-smart-rule-scope.md)

---

## 1. Context

DEVONthink 4 has a built-in automation system called **Smart Rules**. A smart rule is a persistent object in DT that ties three pieces together:

- **Trigger** — when the rule fires (on creation, on modification, on demand, scheduled, ...).
- **Conditions** — filter records the rule applies to (kind, tag, location, name pattern, date, ...).
- **Actions** — what happens to matching records (move, add tag, set color, run AppleScript, ...).

Today the connector cannot create smart rules — users must build them in the DT GUI. This is the first tool that creates a non-record DT object, which makes it architecturally distinct from `file_document` / `bulk_apply` (which mutate existing records).

The 0.0.x roadmap (see ADR-0004) deferred `create_smart_rule` to v2 because it's a "case edge for power user, low expected frequency". For 0.2.0 the reconsideration is: smart rules let users encode triage logic once and have DT enforce it forever — the LLM proposing them is a high-leverage capability for power users coordinating large archives.

This spec deliberately constrains the surface: only "On Demand" trigger, only whitelisted actions, no AppleScript. ADR-0009 captures the rationale for these guardrails.

## 2. Goals

- Programmatic smart rule creation via MCP tool, gated by `dry_run` preview.
- Safety-first defaults: minimal trigger surface (On Demand only), action whitelist, no arbitrary AppleScript.
- Undo via `audit_id`: deleting the created smart rule restores the prior DT state.
- Stable schema: clients (Claude) get a uniform `SmartRuleSpec` shape they can build incrementally.
- Coexist with manual rules: the tool never edits/deletes pre-existing rules.

## 3. Non-goals

- **AppleScript actions** — explicitly excluded in v1 (security + reproducibility concerns; user can wire AppleScript via the GUI if needed).
- **Scheduled triggers** — `On Schedule` not exposed in v1; introduces time-related side effects that interact poorly with audit logging.
- **`On Creation` / `On Modification` triggers** — auto-firing rules surface mass-edit consequences that are hard to undo via the tool surface. Excluded in v1.
- **Editing existing rules** — only creation. Edit is a future iteration; delete-and-recreate is the v1 workaround.
- **Cross-database rules** — each rule lives on a single database (DT model). Multi-DB is a future extension.

## 4. Tool description (for the LLM)

```
create_smart_rule — Create a DEVONthink smart rule that filters records and
applies actions on demand. Useful for codifying a recurring filing pattern
the user wants DT to enforce.

V1 constraints:
- Trigger is always "On Demand" (user manually runs the rule from DT UI).
- Actions are whitelisted: move, add tag, remove tag, set label, set color,
  mark as read, mark as unread.
- AppleScript action is NOT supported. The user must build that via DT UI.
- Each rule lives on a single database.

When to use:
- The user describes a recurring filing pattern ("file PDFs older than 30
  days from /Inbox to /Archive, tag them 'review'").
- The user wants DT to enforce the rule going forward, not a one-shot move.

Don't use for:
- One-shot operations -> use `file_document` or `bulk_apply`.
- Time-triggered rules -> not supported in v1.
- Auto-firing on creation/modification -> not supported in v1.
- AppleScript actions -> not supported in v1; user creates manually.

Examples:
- {"name": "Triage old PDFs", "database": "privato",
   "conditions": [{"field": "kind", "op": "is", "value": "PDF"},
                  {"field": "age_days", "op": ">", "value": 30}],
   "actions": [{"type": "move", "destination": "/Archive/Triage"},
               {"type": "add_tag", "tag": "review"}],
   "dry_run": true}
```

## 5. Input schema

`SmartRuleCondition` and `SmartRuleAction` are leaf models, then composed into `CreateSmartRuleInput`.

```python
class SmartRuleCondition(StrictModel):
    """One filter condition. Joined with AND across the list."""

    field: Literal[
        "kind", "tag", "location", "name", "age_days",
        "size_bytes", "is_unread", "label",
    ]
    op: Literal["is", "is_not", "contains", "starts_with", "ends_with",
                ">", "<", ">=", "<="]
    value: str | int | bool


class SmartRuleAction(StrictModel):
    """One action applied to matching records, in declared order."""

    type: Literal[
        "move", "add_tag", "remove_tag",
        "set_label", "set_color",
        "mark_as_read", "mark_as_unread",
    ]
    destination: str | None = None  # for move
    tag: str | None = None          # for add_tag / remove_tag
    label: str | None = None        # for set_label
    color: str | None = None        # for set_color (hex or DT name)


class CreateSmartRuleInput(StrictModel):
    """Create a DEVONthink smart rule with `On Demand` trigger and
    whitelisted actions. Dry-run by default."""

    name: str = Field(..., min_length=1, max_length=200)
    database: str = Field(..., description="Name of an open DT database")
    conditions: list[SmartRuleCondition] = Field(..., min_length=1, max_length=10)
    actions: list[SmartRuleAction] = Field(..., min_length=1, max_length=10)
    dry_run: bool = True
    confirm_token: str | None = None  # apply requires the audit_id of a prior dry-run
```

## 6. Output schema

```python
class CreateSmartRuleResult(StrictModel):
    smart_rule_uuid: str | None = None  # populated on apply only
    smart_rule_name: str
    database: str
    conditions_count: int
    actions_count: int
    dry_run: bool
    preview: str | None = None  # human-readable summary, populated on dry_run

class CreateSmartRuleOutput(Envelope[CreateSmartRuleResult]):
    pass
```

## 7. Behavior matrix

| Mode | Action |
|---|---|
| `dry_run=True` (default) | Validate input. Compute summary. **Do NOT** create the rule. Return `audit_id` (the eventual `confirm_token`). No JXA write call. |
| `dry_run=False, confirm_token=<id>` | Validate `confirm_token` matches a recent dry-run for the same input. Create the rule via JXA. Persist `smart_rule_uuid` in audit log for undo. |
| `dry_run=False, confirm_token=None` | Reject — error envelope `MISSING_CONFIRM_TOKEN`. Same pattern as `file_document`. |

## 8. JXA bridge addition

New method `JXAAdapter.create_smart_rule(...)` in `libs/adapter/src/istefox_dt_mcp_adapter/jxa.py`. Builds a JXA script that:

1. Looks up the database by name.
2. Constructs a `make new smart rule` call with the `name`, conditions converted to DT internal format, and actions ditto.
3. Returns the new rule's UUID.

Conditions and actions need translation from our schema to DT's internal AppleScript dictionary names. The translation table goes in a small helper:

```python
# In libs/adapter/src/istefox_dt_mcp_adapter/_smart_rule_translate.py
CONDITION_FIELD_MAP = {"kind": "kind", "tag": "tags", ...}
ACTION_TYPE_MAP = {"move": "move record to group", "add_tag": "add tags", ...}
```

The mapping table is small (~20 entries) and tested in isolation.

For undo, a parallel method `delete_smart_rule(uuid)` is added — looks up the rule by UUID and removes it.

## 9. Audit log + undo

- `tool_name = "create_smart_rule"`
- `input_data = input.model_dump()` (full spec; useful for replay/debug)
- `output_data = {"smart_rule_uuid": ..., "rule_name": ..., "database": ...}`
- `before_state = None` (the rule didn't exist before)
- `after_state = {"smart_rule_uuid": <new uuid>}` (used by `undo` to know what to delete)

`undo` of a `create_smart_rule` audit_id calls `adapter.delete_smart_rule(after_state["smart_rule_uuid"])` to remove the rule. Drift detection is binary in this case:
- `no_drift`: the rule still exists with the expected uuid → safe delete.
- `hostile_drift`: the rule was already deleted by the user, or its uuid doesn't resolve → return success with `already_reverted` (gracefully no-op).

## 10. Error handling

- `DATABASE_NOT_FOUND`: input `database` doesn't match an open DB.
- `INVALID_CONDITION`: a condition uses an unsupported `field/op/value` triple (e.g. `op=">"` on `field=tag`).
- `INVALID_ACTION`: an action has missing required fields (e.g. `type=move` without `destination`).
- `MISSING_CONFIRM_TOKEN`: dry-run not provided before apply.
- `JXA_TIMEOUT`: standard 5s timeout exceeded (smart rule creation is normally <100ms).

## 11. Test plan

### Unit tests (no JXA)

In `tests/unit/test_create_smart_rule.py`:

1. Schema validation: required fields, field type constraints, list length bounds (10).
2. Condition op compatibility: `op=">"` on `field=tag` rejects.
3. Action requirement matrix: `type=move` requires `destination`, `type=add_tag` requires `tag`, etc.
4. Dry-run path: returns audit_id, no JXA call.
5. Apply without confirm_token: returns MISSING_CONFIRM_TOKEN.
6. Apply with stale confirm_token: returns CONFIRM_TOKEN_EXPIRED.
7. JXA error → error envelope with recovery_hint.
8. Smart rule translation table: each Pydantic field → expected DT AppleScript term (table-driven test).

### Contract tests (cassette-based)

In `tests/contract/test_create_smart_rule_contract.py`: 1-2 cassettes capturing the JXA `make new smart rule` call shape.

### Integration tests (`-m integration`, requires DT)

In `tests/integration/test_create_smart_rule_integration.py`:
- Smoke: create + delete roundtrip on a real DT database.
- Verify the rule shows up in DT GUI smart rules list.
- Verify "On Demand" run actually filters and applies actions on test records.

## 12. Implementation note (for future plan)

- Files (estimate):
  - `libs/schemas/.../tools.py` — append `SmartRuleCondition`, `SmartRuleAction`, `CreateSmartRuleInput/Result/Output`.
  - `libs/adapter/.../jxa.py` — add `create_smart_rule` and `delete_smart_rule` methods.
  - `libs/adapter/.../_smart_rule_translate.py` (new) — translation table.
  - `apps/server/.../tools/create_smart_rule.py` (new) — tool register.
  - `apps/server/.../undo.py` — new branch handling `tool_name == "create_smart_rule"`.
  - `apps/server/.../server.py` — register the tool.
  - CHANGELOG, README, ADR-0009 (this PR's companion).
- Estimated effort: 3-4 sessions (~500 LoC + tests).

## 13. Risks & open questions

- **Risk**: DT4's smart rule AppleScript dictionary has been less documented than the record API. May require empirical exploration to discover the right `make new smart rule` syntax. Mitigation: integration test against live DT before wiring up the JXA bridge; if dictionary is missing properties, raise visibility (could push the tool to 0.3.0).
- **Open**: should the apply path also return a "first run preview" (count of records the rule would touch on its first On Demand run)? Decision: **no** in v1 — the user runs the rule manually in DT UI and sees the preview there. Adding preview-of-preview here doubles JXA work. Reconsider in 0.3.0 if users ask.
- **Open**: should `undo` of create_smart_rule also revert the actions the rule has applied since creation? Decision: **no** — the audit log doesn't track per-firing record changes (the rule lives in DT, not in the connector). Undo only deletes the rule itself; users keep responsibility for downstream cleanup. Documented as known limitation in the tool description and CHANGELOG.

## 14. ADR linkage

This spec depends on **ADR-0009 — `create_smart_rule` scope and safety boundaries** for the architectural decisions about:
- Trigger restriction to "On Demand" only
- Action whitelist (no AppleScript)
- Single-database scope per rule
- Undo semantics (delete-only, no record-action rollback)

ADR-0009 must be approved by the user before implementation begins.
