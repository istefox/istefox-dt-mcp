# JXA Discovery — DT4 Smart Rules

Date: 2026-05-04
**Discovery partial**: DT4 was running and responded to basic introspection, but
the `smartRules()` collection is NOT accessible via JXA scripting.

## Discovery output

```json
{
  "dt_version": "4.2.2",
  "databases_count": 2,
  "first_db_name": "(redacted — personal data)",
  "app_smart_rules_error": "Error: Messaggio incomprensibile.",
  "db_smart_rules_error": "Error: Impossibile convertire tipi."
}
```

Additional probes (iterations 2–6):

- `dt.smartRules` property exists as a JXA function specifier but calling it
  returns `Error: Messaggio incomprensibile.` (AppleEvent error -1708 / handler
  not found).
- `dt.smartRules.whose(...)` — `whose` is `undefined` on the specifier.
- `dt.make({ new: 'smart rule', ... })` — `Error: Impossibile creare una classe.`
  (tried: `smart rule`, `smartRule`, `SmartRule`, `smart-rule`, `rule`, `Rule`).
- No alternative creation verb (`createSmartRule`, `makeSmartRule`, etc.) exists
  in the sdef — those names simply returned `"function"` because every JXA
  property access on an app object returns `"function"`.
- `dt.properties()` at application level does NOT include `smartRules`.

## Key finding: SmartRules.plist

Smart rules are stored at:

```
~/Library/Application Support/DEVONthink/SmartRules.plist
```

The file is a plist array where each element has:

| Key | Type | Description |
|---|---|---|
| `name` | string | Rule name (human-readable) |
| `Enabled` | bool | Whether the rule is active |
| `data` | binary data | **Opaque binary blob** — DT4 internal serialisation format |
| `sync.UUID` | string | UUID (stable identifier) |
| `sync.date` | date | Last modification date |
| `IndexOffset` | int | Ordering position |
| `settings` | dict | UI settings (browser view, sorting) |

The `data` field is a proprietary binary encoding. It is NOT plist-serialisable
to a documented format (observed: custom binary with `KSTPKEVQ`, `KACTCLAS`,
`RLAT`, `TEXT` markers — looks like a KeyedArchiver variant).

## sdef analysis

```
Command exposed: "perform smart rule" (code DTpacda0)
Parameters: name (optional), record (optional), trigger (rule event, optional)
Returns: boolean
```

The sdef exposes NO create/delete/update commands for smart rules.
The `rule event` enumeration covers: creation, import, clipping, download,
rename, move, classify, replicate, duplicate, tagging, flagging, labelling,
rating, move into database, move to external folder, commenting, convert, OCR,
imprint, trashing, open, open externally, edit externally, launch, no event.

## Conclusions

- DT4 version: **4.2.2**
- Smart rules are **NOT scriptable** via JXA/AppleScript in DT4.2.2:
  the collection is not enumerable, creation is not supported, and no
  create/delete commands exist in the sdef.
- The only scripting surface is `perform smart rule` (trigger by name).
- Smart rules live in `~/Library/Application Support/DEVONthink/SmartRules.plist`
  but the `data` field uses an opaque binary serialisation that cannot be
  synthesised without reverse-engineering DT4 internals — **unsafe and fragile**.
- `dt.smartRules()` throws `-1708` (event not handled) — the method is
  registered in the sdef as a collection element type but DT4 does not
  implement the handler.

## Implications for Task 4 — create_smart_rule implementation

Given the above, **the JXA-based `create_smart_rule` tool cannot be implemented
as originally scoped**. The implementer must choose one of:

### Option A — `perform smart rule` only (narrow scope)
Reduce `create_smart_rule` to a "run an existing rule by name/UUID" tool.
This is fully supported: `dt.performSmartRule({ name: "My Rule" })` returns
`true/false`. Write ops (create/delete) must be dropped from v1 scope.
Recommended if the goal is a working v1 tool.

### Option B — Plist manipulation (high risk)
Read/write `SmartRules.plist` directly. Risk: the `data` blob is binary and
opaque — writing a malformed blob would silently corrupt all rules. Not
recommended without full reverse-engineering of the DT4 serialisation format.

### Option C — Defer to DT developer confirmation
File a support request with DEVONtechnologies asking whether `smart rules`
will be scriptable in a future DT4 minor release or if there is a documented
x-callback-url or HTTP API for rule management.

### Syntax for Option A (the only safe JXA path)

```javascript
// Perform a named smart rule (trigger = on demand)
const dt = Application("DEVONthink");
const ok = dt.performSmartRule({ name: "My Rule" });
// Returns: true on success, false if rule not found or not triggered

// Perform with a specific trigger event
const ok2 = dt.performSmartRule({
  name: "My Rule",
  trigger: "no event"
});
```

This is the shape the integration smoke test in Task 8 should exercise.
If any future DT update makes `smartRules()` enumerable, iterate on the
translation layer in `libs/adapter/src/istefox_dt_mcp_adapter/_smart_rule_translate.py`.
