# MCP Resources + Prompts (0.5.0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 3 read-only, bounded, consent-gated `dt://` MCP Resources and 2 template-only MCP Prompts to istefox-dt-mcp, with zero new runtime deps and zero new JXA.

**Architecture:** Resources reuse existing adapter methods (`list_databases`, `get_record`, `get_record_text`). Cross-cutting concerns (scope `dt:read` gate, per-DB ConsentStore gate, audit) go through a new `safe_resource` helper that *raises* on failure (resources return raw content, not the `Envelope` that `safe_call` produces). Per-resource logic lives in pure async builder functions for testability; thin `@mcp.resource`/`@mcp.prompt` wrappers delegate to them.

**Tech Stack:** Python 3.12, FastMCP 3.2.4, Pydantic v2, pytest + pytest-asyncio, `uv`. Spec: `docs/superpowers/specs/2026-05-17-mcp-resources-prompts-design.md`.

---

## Conventions

- Run all commands from repo root `/Users/stefanoferri/Developer/Devonthink_MCP`.
- Test runner: `uv run pytest`. Lint/type gate: `uv run ruff check apps libs`, `uv run black --check apps libs`, `uv run mypy apps libs`.
- Commits: Conventional Commits in English, imperative, **no `Co-Authored-By` trailer**.
- Branch per PR (global rule: never commit to `main` directly). Branch names below.

## File Structure (decomposition lock)

| File | Responsibility |
|---|---|
| `libs/schemas/src/istefox_dt_mcp_schemas/tools.py` (modify) | 3 new Pydantic output models, reusing `common.Database`/`common.Record` |
| `apps/server/src/istefox_dt_mcp_server/resources/__init__.py` (create) | empty package marker |
| `apps/server/src/istefox_dt_mcp_server/resources/_common.py` (create) | `RESOURCE_MAX_CHARS`, `RESOURCE_JSON_BUDGET_CHARS`, `MAX_TAGS`, `bound_json`, `safe_resource` |
| `apps/server/src/istefox_dt_mcp_server/resources/dt_resources.py` (create) | pure builders + `register(mcp, deps)` with 3 `@mcp.resource` |
| `apps/server/src/istefox_dt_mcp_server/prompts/__init__.py` (create) | empty package marker |
| `apps/server/src/istefox_dt_mcp_server/prompts/dt_prompts.py` (create) | pure template fns + `register(mcp, deps)` with 2 `@mcp.prompt` |
| `apps/server/src/istefox_dt_mcp_server/server.py` (modify) | wire registrations, bump version, +1 instructions line |
| `docs/adr/0009-mcp-resources-prompts.md` (create) | ADR |
| `tests/unit/test_resources_common.py` (create) | `bound_json` + `safe_resource` scope/audit |
| `tests/unit/test_resources_databases.py` (create) | `dt://databases` consent + determinism |
| `tests/unit/test_resources_record.py` (create) | record metadata/text + consent + bound |
| `tests/unit/test_prompts.py` (create) | prompt templates + wiring |
| `tests/integration/test_resources_live.py` (create) | Tier-3 live resource reads |
| `scripts/smoke_e2e.py` (modify) | +1 resource step |

**No new contract test (deliberate, YAGNI):** resources add no new JXA; they call `get_record`/`get_record_text`/`list_databases` which already have contract cassettes. The bridge contract is unchanged, so there is nothing new to record. This matches the spec ("nessuna cassetta nuova").

---

# PR 1 — ADR + schemas

Branch: `feat/0.5.0-resources-schemas`

### Task 1: ADR-0009

**Files:**
- Create: `docs/adr/0009-mcp-resources-prompts.md`

- [ ] **Step 1: Write the ADR**

```markdown
# ADR-0009: MCP Resources + Prompts surfaces (bounded, consent-gated)

- **Status**: Accepted
- **Date**: 2026-05-17
- **Decisori**: istefox
- **Fonte**: docs/superpowers/specs/2026-05-17-mcp-resources-prompts-design.md, CLAUDE.md §2.2, ADR-0006

## Contesto

Il server espone 7 tool ma zero MCP Resources e zero Prompts, nonostante il
CLAUDE.md §2.2 imponga URI `dt://` stabili/deterministici e resource bounded
≤25K token. È l'unica grande superficie del protocollo MCP non coperta.

## Decisione

Adottare le superfici MCP Resources e Prompts.

- **Resources**: 3, read-only — `dt://databases`,
  `dt://record/{uuid}/metadata`, `dt://record/{uuid}/text`. URI deterministici
  e stabili basati sullo UUID DEVONthink. Ogni resource è bounded ≤25K token
  via troncamento esplicito (`RESOURCE_MAX_CHARS`, backstop
  `RESOURCE_JSON_BUDGET_CHARS`); mai dump di un intero database.
- **Sicurezza**: le read di resource passano per lo stesso gate scope
  `dt:read` + ConsentStore dei tool, tramite l'helper `safe_resource` (NON
  `safe_call`: le resource restituiscono contenuto raw e su errore devono
  *sollevare* un errore di protocollo MCP, non un envelope `success=false`).
  Record di un database non autorizzato, o con `database_uuid` non
  determinabile sotto un principal HTTP, sono negati (fail-closed).
- **Prompts**: 2, soli template (`weekly_review`, `triage_inbox`) che
  orchestrano i tool esistenti. Zero dipendenze/JXA.

## Razionale

Completa il protocollo a costo minimo: zero dipendenze runtime nuove, zero
script JXA nuovi, zero metodi adapter astratti nuovi. Riuso integrale
dell'infrastruttura 0.4.0 (adapter, ConsentStore, audit, scope).

## Conseguenze

- Aumenta di poco il costo di contesto delle liste resource/prompt
  (3+2 voci, descrizioni ≤1 riga). Accettato; YAGNI sul resto.
- La stima token è euristica (3.5 char/token, 60K char ≈30% headroom);
  mitigata da test che asserisce il bound.
- `total_chars` esatto non disponibile (richiederebbe JXA nuovo): deferito.

## Riferimenti

- Spec: docs/superpowers/specs/2026-05-17-mcp-resources-prompts-design.md
- ADR-0006 (OAuth scope model), ADR-0005 (test strategy 4-tier)
```

- [ ] **Step 2: Commit**

```bash
git checkout -b feat/0.5.0-resources-schemas
git add docs/adr/0009-mcp-resources-prompts.md
git commit -m "docs(adr): ADR-0009 MCP resources + prompts"
```

### Task 2: Schema models

**Files:**
- Modify: `libs/schemas/src/istefox_dt_mcp_schemas/tools.py:22-29` (imports) and append at end of file
- Test: `tests/unit/test_resources_common.py` (schema portion)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_resources_common.py`:

```python
"""Resource schema + helper unit tests (0.5.0)."""

from __future__ import annotations

from datetime import UTC, datetime

from istefox_dt_mcp_schemas.common import Database, Record
from istefox_dt_mcp_schemas.tools import (
    DatabaseListResource,
    RecordMetadataResource,
    RecordTextResource,
)


def _record(uuid: str = "R-1") -> Record:
    return Record(
        uuid=uuid,
        name="Doc",
        kind="PDF",
        location="/Inbox",
        reference_url=f"x-devonthink-item://{uuid}",
        creation_date=datetime(2026, 1, 1, tzinfo=UTC),
        modification_date=datetime(2026, 1, 2, tzinfo=UTC),
        tags=["a", "b"],
        database_uuid="DB-1",
    )


def test_database_list_resource_roundtrip() -> None:
    db = Database(uuid="DB-1", name="Alpha", path="/p", is_open=True)
    model = DatabaseListResource(databases=[db], truncated=False)
    dumped = model.model_dump(mode="json")
    assert dumped["databases"][0]["uuid"] == "DB-1"
    assert dumped["truncated"] is False


def test_record_metadata_resource_roundtrip() -> None:
    model = RecordMetadataResource(record=_record(), tags_truncated=False)
    dumped = model.model_dump(mode="json")
    assert dumped["record"]["uuid"] == "R-1"
    assert dumped["tags_truncated"] is False


def test_record_text_resource_roundtrip() -> None:
    model = RecordTextResource(
        uuid="R-1", text="hello", truncated=False, returned_chars=5
    )
    dumped = model.model_dump(mode="json")
    assert dumped == {
        "uuid": "R-1",
        "text": "hello",
        "truncated": False,
        "returned_chars": 5,
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_resources_common.py -q`
Expected: FAIL with `ImportError: cannot import name 'DatabaseListResource'`

- [ ] **Step 3: Add imports**

In `libs/schemas/src/istefox_dt_mcp_schemas/tools.py`, change the import block (currently lines 15-29) so the `__future__`/datetime block and the `.common` import include `Record` and `datetime`:

```python
from __future__ import annotations

from datetime import date, datetime  # noqa: TC003 — needed by Pydantic at runtime
from typing import Literal

from pydantic import Field, field_validator

from .common import (
    Database,
    Envelope,
    Record,
    RecordKind,
    RelatedResult,
    SearchResult,
    StrictModel,
)
```

- [ ] **Step 4: Append the 3 models**

At the **end** of `libs/schemas/src/istefox_dt_mcp_schemas/tools.py`:

```python
# ----------------------------------------------------------------------
# MCP resource payloads (0.5.0). These wrap the shared domain models so
# resource bodies stay DRY and validated. They are OUTPUT payloads we
# construct ourselves, hence StrictModel.
# ----------------------------------------------------------------------


class DatabaseListResource(StrictModel):
    """Body of the `dt://databases` resource."""

    databases: list[Database]
    truncated: bool = False


class RecordMetadataResource(StrictModel):
    """Body of `dt://record/{uuid}/metadata` — the record card, no text.

    `Record` already carries no document body, so it is reused whole.
    `tags_truncated` flags a defensive cap applied by the builder.
    """

    record: Record
    tags_truncated: bool = False


class RecordTextResource(StrictModel):
    """Body of `dt://record/{uuid}/text` — bounded plain text."""

    uuid: str
    text: str
    truncated: bool
    returned_chars: int
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_resources_common.py -q`
Expected: PASS (3 passed)

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check libs tests/unit/test_resources_common.py
uv run black libs tests/unit/test_resources_common.py
git add libs/schemas/src/istefox_dt_mcp_schemas/tools.py tests/unit/test_resources_common.py
git commit -m "feat(schemas): resource payload models for 0.5.0"
```

---

# PR 2 — `safe_resource` + `dt://databases`

Branch: `feat/0.5.0-resource-databases` (off `feat/0.5.0-resources-schemas`)

### Task 3: `resources/_common.py` — `bound_json`

**Files:**
- Create: `apps/server/src/istefox_dt_mcp_server/resources/__init__.py`
- Create: `apps/server/src/istefox_dt_mcp_server/resources/_common.py`
- Test: `tests/unit/test_resources_common.py` (append)

- [ ] **Step 1: Write the failing test** (append to `tests/unit/test_resources_common.py`)

```python
import json

from istefox_dt_mcp_server.resources._common import (
    RESOURCE_JSON_BUDGET_CHARS,
    bound_json,
)


def test_bound_json_small_payload_is_verbatim_and_sorted() -> None:
    body = bound_json({"b": 2, "a": 1})
    assert json.loads(body) == {"a": 1, "b": 2}
    assert body.index('"a"') < body.index('"b"')  # sort_keys


def test_bound_json_truncates_oversized_text_field() -> None:
    huge = "x" * (RESOURCE_JSON_BUDGET_CHARS * 2)
    body = bound_json(
        {"uuid": "R", "text": huge, "truncated": False, "returned_chars": len(huge)}
    )
    assert len(body) <= RESOURCE_JSON_BUDGET_CHARS
    parsed = json.loads(body)
    assert parsed["truncated"] is True
    assert parsed["returned_chars"] == len(parsed["text"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_resources_common.py -q`
Expected: FAIL with `ModuleNotFoundError: ... resources._common`

- [ ] **Step 3: Create the package marker**

Create `apps/server/src/istefox_dt_mcp_server/resources/__init__.py`:

```python
"""MCP resource registrations (0.5.0)."""
```

- [ ] **Step 4: Create `_common.py` with constants + `bound_json`**

Create `apps/server/src/istefox_dt_mcp_server/resources/_common.py`:

```python
"""Common helpers for MCP resources.

Resources differ from tools: they return raw content (a JSON string
here), not an `Envelope`. On failure the MCP protocol expects the read
to *raise* (FastMCP turns it into a protocol error), not to return a
`success=false` body. Hence `safe_resource` mirrors `safe_call`'s
building blocks (scope gate, audit, error translation) but raises
instead of producing an envelope.

`bound_json` enforces the CLAUDE.md §2.2 size bound: a hard ceiling on
the serialized payload, with text-field truncation as defense in depth.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from istefox_dt_mcp_adapter.errors import AdapterError

from ..audit import timer
from ..auth.consent import ReconsentRequiredError
from ..auth.scope import (
    InsufficientScopeError,
    Scope,
    current_context,
    current_scopes,
)
from ..tools._common import OAUTH_INSUFFICIENT_SCOPE, RECONSENT_REQUIRED

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ..deps import Deps

# ~17K tokens at a conservative 3.5 chars/token — well under the 25K
# Claude Code resource bound, leaving headroom for token-dense text.
RESOURCE_MAX_CHARS = 60_000

# Absolute ceiling on the serialized JSON payload (envelope + text).
RESOURCE_JSON_BUDGET_CHARS = 80_000

# Defensive cap on the tag list of a record metadata resource.
MAX_TAGS = 100


def bound_json(payload: dict[str, Any]) -> str:
    """Serialize `payload` deterministically and enforce the size bound.

    Deterministic: `sort_keys=True`, `default=str`. If the payload
    exceeds the budget (only plausible for the text resource), truncate
    its `text` field, mark `truncated`, and re-serialize. A final hard
    slice guarantees the ceiling even in pathological cases.
    """
    s = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    if len(s) <= RESOURCE_JSON_BUDGET_CHARS:
        return s
    if isinstance(payload.get("text"), str):
        overflow = len(s) - RESOURCE_JSON_BUDGET_CHARS
        keep = max(0, len(payload["text"]) - overflow - 64)
        payload = {
            **payload,
            "text": payload["text"][:keep],
            "truncated": True,
            "returned_chars": keep,
        }
        s = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return s[:RESOURCE_JSON_BUDGET_CHARS]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_resources_common.py -q`
Expected: PASS (5 passed)

- [ ] **Step 6: Commit**

```bash
git checkout -b feat/0.5.0-resource-databases
git add apps/server/src/istefox_dt_mcp_server/resources/ tests/unit/test_resources_common.py
git commit -m "feat(resources): bound_json + resource size constants"
```

### Task 4: `safe_resource`

**Files:**
- Modify: `apps/server/src/istefox_dt_mcp_server/resources/_common.py` (append `safe_resource`)
- Test: `tests/unit/test_resources_common.py` (append)

- [ ] **Step 1: Write the failing tests** (append to `tests/unit/test_resources_common.py`)

```python
import pytest
from istefox_dt_mcp_server.auth.scope import (
    InsufficientScopeError,
    RequestContext,
    Scope,
    reset_request_context,
    set_request_context,
)
from istefox_dt_mcp_server.resources._common import safe_resource


@pytest.mark.asyncio
async def test_safe_resource_returns_bound_body_and_audits(deps) -> None:
    async def op() -> dict:
        return {"ok": True}

    body = await safe_resource(uri="dt://x", deps=deps, operation=op)
    assert json.loads(body) == {"ok": True}
    recent = deps.audit.list_recent(limit=1)
    assert recent[0]["tool_name"] == "resource:dt://x"
    assert recent[0]["error_code"] is None


@pytest.mark.asyncio
async def test_safe_resource_denies_when_read_scope_missing(deps) -> None:
    ctx = RequestContext(principal_id="bob", granted_scopes=frozenset())
    token = set_request_context(ctx)
    try:
        with pytest.raises(InsufficientScopeError):
            await safe_resource(
                uri="dt://x",
                deps=deps,
                operation=lambda: (_ for _ in ()).throw(
                    AssertionError("operation must not run")
                ),
            )
    finally:
        reset_request_context(token)
    recent = deps.audit.list_recent(limit=1)
    assert recent[0]["error_code"] == "OAUTH_INSUFFICIENT_SCOPE"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_resources_common.py -q`
Expected: FAIL with `ImportError: cannot import name 'safe_resource'`

- [ ] **Step 3: Append `safe_resource` to `_common.py`**

```python
async def safe_resource(
    *,
    uri: str,
    deps: Deps,
    operation: Callable[[], Awaitable[dict[str, Any]]],
) -> str:
    """Run a resource builder behind the scope/consent/audit gate.

    `operation` returns the payload dict; it may raise
    `ReconsentRequiredError` (consent denied) or `AdapterError`. This
    helper enforces `Scope.READ`, audits every outcome (success or
    denial) with `tool_name="resource:<uri>"`, and *raises* on failure
    so FastMCP surfaces an MCP protocol error.
    """
    ctx = current_context()
    principal = ctx.principal_id if ctx is not None else "local"

    if Scope.READ not in current_scopes():
        deps.audit.append(
            tool_name=f"resource:{uri}",
            input_data={"uri": uri},
            output_data=None,
            duration_ms=0.0,
            principal=principal,
            error_code=OAUTH_INSUFFICIENT_SCOPE,
        )
        raise InsufficientScopeError(
            required=Scope.READ,
            granted=current_scopes(),
            principal_id=ctx.principal_id if ctx is not None else None,
        )

    with timer() as t:
        try:
            payload = await operation()
        except ReconsentRequiredError:
            deps.audit.append(
                tool_name=f"resource:{uri}",
                input_data={"uri": uri},
                output_data=None,
                duration_ms=t.duration_ms,
                principal=principal,
                error_code=RECONSENT_REQUIRED,
            )
            raise
        except AdapterError as e:
            deps.audit.append(
                tool_name=f"resource:{uri}",
                input_data={"uri": uri},
                output_data=None,
                duration_ms=t.duration_ms,
                principal=principal,
                error_code=e.code.value,
            )
            raise

    body = bound_json(payload)
    deps.audit.append(
        tool_name=f"resource:{uri}",
        input_data={"uri": uri},
        output_data={"bytes": len(body)},
        duration_ms=t.duration_ms,
        principal=principal,
    )
    return body
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_resources_common.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check apps tests/unit/test_resources_common.py
uv run black apps tests/unit/test_resources_common.py
git add apps/server/src/istefox_dt_mcp_server/resources/_common.py tests/unit/test_resources_common.py
git commit -m "feat(resources): safe_resource scope/consent/audit gate"
```

### Task 5: `dt://databases` resource + wiring

**Files:**
- Create: `apps/server/src/istefox_dt_mcp_server/resources/dt_resources.py`
- Modify: `apps/server/src/istefox_dt_mcp_server/server.py:16-22, 28, 31-44, 65`
- Test: `tests/unit/test_resources_databases.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_resources_databases.py`:

```python
"""dt://databases resource tests (0.5.0)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from istefox_dt_mcp_schemas.common import Database
from istefox_dt_mcp_server.auth.scope import (
    RequestContext,
    Scope,
    reset_request_context,
    set_request_context,
)
from istefox_dt_mcp_server.resources.dt_resources import build_databases_payload

if TYPE_CHECKING:
    from istefox_dt_mcp_server.deps import Deps


def _db(uuid: str, name: str) -> Database:
    return Database(uuid=uuid, name=name, path=f"/p/{uuid}", is_open=True)


@pytest.fixture
def all_dbs() -> list[Database]:
    return [_db("DB-C", "Gamma"), _db("DB-A", "Alpha"), _db("DB-B", "Beta")]


@pytest.mark.asyncio
async def test_stdio_sees_all_sorted_by_uuid(deps: Deps, all_dbs) -> None:
    deps.adapter.list_databases.return_value = all_dbs  # type: ignore[attr-defined]
    payload = await build_databases_payload(deps)
    uuids = [d["uuid"] for d in payload["databases"]]
    assert uuids == ["DB-A", "DB-B", "DB-C"]  # deterministic order
    assert payload["truncated"] is False


@pytest.mark.asyncio
async def test_determinism_byte_identical(deps: Deps, all_dbs) -> None:
    deps.adapter.list_databases.return_value = all_dbs  # type: ignore[attr-defined]
    a = json.dumps(await build_databases_payload(deps), sort_keys=True)
    b = json.dumps(await build_databases_payload(deps), sort_keys=True)
    assert a == b


@pytest.mark.asyncio
async def test_http_principal_filtered_by_consent(deps: Deps, all_dbs) -> None:
    deps.adapter.list_databases.return_value = all_dbs  # type: ignore[attr-defined]
    deps.consent.authorize("alice", "DB-B")
    ctx = RequestContext(principal_id="alice", granted_scopes=frozenset({Scope.READ}))
    token = set_request_context(ctx)
    try:
        payload = await build_databases_payload(deps)
    finally:
        reset_request_context(token)
    assert [d["uuid"] for d in payload["databases"]] == ["DB-B"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_resources_databases.py -q`
Expected: FAIL with `ImportError: cannot import name 'build_databases_payload'`

- [ ] **Step 3: Create `dt_resources.py` with the databases builder + register**

Create `apps/server/src/istefox_dt_mcp_server/resources/dt_resources.py`:

```python
"""DEVONthink MCP resources (0.5.0).

Pure async builders hold the logic (testable without FastMCP); thin
`@mcp.resource` wrappers delegate through `safe_resource`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from istefox_dt_mcp_schemas.tools import DatabaseListResource

from ..auth.scope import current_context
from ._common import safe_resource

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from ..deps import Deps


async def build_databases_payload(deps: Deps) -> dict[str, Any]:
    """Consent-filtered, uuid-sorted list of open databases."""
    all_dbs = await deps.adapter.list_databases()
    ctx = current_context()
    if ctx is None:
        visible = list(all_dbs)
    else:
        visible = deps.consent.filter_visible(ctx.principal_id, all_dbs)
    visible_sorted = sorted(visible, key=lambda d: d.uuid)
    model = DatabaseListResource(databases=visible_sorted, truncated=False)
    return model.model_dump(mode="json")


def register(mcp: FastMCP, deps: Deps) -> None:
    @mcp.resource(
        "dt://databases",
        name="dt-databases",
        mime_type="application/json",
        description=(
            "Open DEVONthink databases visible to the caller "
            "(consent-filtered). Deterministic, bounded, read-only."
        ),
    )
    async def dt_databases() -> str:
        return await safe_resource(
            uri="dt://databases",
            deps=deps,
            operation=lambda: build_databases_payload(deps),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_resources_databases.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Wire into `server.py`**

In `apps/server/src/istefox_dt_mcp_server/server.py`:

(a) After line 22 (`from .tools import summarize_topic as tool_summarize_topic`) add:

```python
from .resources import dt_resources as resource_dt
```

(b) Change line 28 from `SERVER_VERSION = "0.4.0"` to:

```python
SERVER_VERSION = "0.5.0"
```

(c) In `SERVER_INSTRUCTIONS` (the string starting line 31), append this sentence before the closing `"""` (after the existing last paragraph):

```
Read-only `dt://` resources expose databases and individual records as
referenceable context (bounded, consent-gated).
```

(d) After line 65 (`tool_summarize_topic.register(mcp, deps)`) add:

```python
    resource_dt.register(mcp, deps)
```

- [ ] **Step 6: Write the wiring test** (append to `tests/unit/test_resources_databases.py`)

```python
from fastmcp import FastMCP
from istefox_dt_mcp_server.resources.dt_resources import register


@pytest.mark.asyncio
async def test_resource_registered_and_readable(deps: Deps, all_dbs) -> None:
    deps.adapter.list_databases.return_value = all_dbs  # type: ignore[attr-defined]
    mcp: FastMCP = FastMCP(name="test")
    register(mcp, deps)
    result = await mcp.read_resource("dt://databases")
    body = result.contents[0].content
    parsed = json.loads(body)
    assert {d["uuid"] for d in parsed["databases"]} == {"DB-A", "DB-B", "DB-C"}
```

- [ ] **Step 7: Run full PR2 tests**

Run: `uv run pytest tests/unit/test_resources_common.py tests/unit/test_resources_databases.py -q`
Expected: PASS (11 passed)

- [ ] **Step 8: Gate + commit**

```bash
uv run ruff check apps tests/unit/test_resources_databases.py
uv run black apps tests/unit/test_resources_databases.py
uv run mypy apps libs
git add apps/server/src/istefox_dt_mcp_server/ tests/unit/test_resources_databases.py
git commit -m "feat(resources): dt://databases resource + server wiring + 0.5.0 bump"
```

---

# PR 3 — record resources (metadata + text)

Branch: `feat/0.5.0-resource-records` (off `feat/0.5.0-resource-databases`)

### Task 6: `_resolve_consented_record` + metadata resource

**Files:**
- Modify: `apps/server/src/istefox_dt_mcp_server/resources/dt_resources.py`
- Test: `tests/unit/test_resources_record.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_resources_record.py`:

```python
"""dt://record/{uuid}/{metadata,text} resource tests (0.5.0)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from istefox_dt_mcp_schemas.common import Record
from istefox_dt_mcp_server.auth.consent import ReconsentRequiredError
from istefox_dt_mcp_server.auth.scope import (
    RequestContext,
    Scope,
    reset_request_context,
    set_request_context,
)
from istefox_dt_mcp_server.resources._common import (
    MAX_TAGS,
    RESOURCE_JSON_BUDGET_CHARS,
    RESOURCE_MAX_CHARS,
)
from istefox_dt_mcp_server.resources.dt_resources import (
    build_record_metadata_payload,
    build_record_text_payload,
)

if TYPE_CHECKING:
    from istefox_dt_mcp_server.deps import Deps


def _record(uuid: str = "R-1", tags: list[str] | None = None) -> Record:
    return Record(
        uuid=uuid,
        name="Doc",
        kind="PDF",
        location="/Inbox",
        reference_url=f"x-devonthink-item://{uuid}",
        creation_date=datetime(2026, 1, 1, tzinfo=UTC),
        modification_date=datetime(2026, 1, 2, tzinfo=UTC),
        tags=tags if tags is not None else ["a", "b"],
        database_uuid="DB-1",
    )


@pytest.mark.asyncio
async def test_metadata_payload_stdio(deps: Deps) -> None:
    deps.adapter.get_record.return_value = _record()  # type: ignore[attr-defined]
    payload = await build_record_metadata_payload(deps, "R-1")
    assert payload["record"]["uuid"] == "R-1"
    assert payload["tags_truncated"] is False


@pytest.mark.asyncio
async def test_metadata_tags_capped(deps: Deps) -> None:
    deps.adapter.get_record.return_value = _record(  # type: ignore[attr-defined]
        tags=[f"t{i}" for i in range(MAX_TAGS + 50)]
    )
    payload = await build_record_metadata_payload(deps, "R-1")
    assert len(payload["record"]["tags"]) == MAX_TAGS
    assert payload["tags_truncated"] is True


@pytest.mark.asyncio
async def test_record_consent_denied_for_http_principal(deps: Deps) -> None:
    deps.adapter.get_record.return_value = _record()  # type: ignore[attr-defined]
    ctx = RequestContext(principal_id="bob", granted_scopes=frozenset({Scope.READ}))
    token = set_request_context(ctx)
    try:
        with pytest.raises(ReconsentRequiredError):
            await build_record_metadata_payload(deps, "R-1")
    finally:
        reset_request_context(token)


@pytest.mark.asyncio
async def test_record_missing_db_uuid_fails_closed_under_http(deps: Deps) -> None:
    rec = _record()
    rec = rec.model_copy(update={"database_uuid": None})
    deps.adapter.get_record.return_value = rec  # type: ignore[attr-defined]
    ctx = RequestContext(principal_id="bob", granted_scopes=frozenset({Scope.READ}))
    token = set_request_context(ctx)
    try:
        with pytest.raises(ReconsentRequiredError):
            await build_record_metadata_payload(deps, "R-1")
    finally:
        reset_request_context(token)


@pytest.mark.asyncio
async def test_text_payload_truncation_flag(deps: Deps) -> None:
    deps.adapter.get_record.return_value = _record()  # type: ignore[attr-defined]
    deps.adapter.get_record_text.return_value = (  # type: ignore[attr-defined]
        "y" * RESOURCE_MAX_CHARS
    )
    payload = await build_record_text_payload(deps, "R-1")
    assert payload["truncated"] is True
    assert payload["returned_chars"] == RESOURCE_MAX_CHARS


@pytest.mark.asyncio
async def test_text_payload_bounded(deps: Deps) -> None:
    from istefox_dt_mcp_server.resources._common import bound_json

    deps.adapter.get_record.return_value = _record()  # type: ignore[attr-defined]
    deps.adapter.get_record_text.return_value = (  # type: ignore[attr-defined]
        "z" * (RESOURCE_JSON_BUDGET_CHARS * 3)
    )
    payload = await build_record_text_payload(deps, "R-1")
    assert len(bound_json(payload)) <= RESOURCE_JSON_BUDGET_CHARS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_resources_record.py -q`
Expected: FAIL with `ImportError: cannot import name 'build_record_metadata_payload'`

- [ ] **Step 3: Add builders to `dt_resources.py`**

In `apps/server/src/istefox_dt_mcp_server/resources/dt_resources.py`, update imports and append builders.

Change the imports block to:

```python
from istefox_dt_mcp_schemas.tools import (
    DatabaseListResource,
    RecordMetadataResource,
    RecordTextResource,
)

from ..auth.consent import ReconsentRequiredError
from ..auth.scope import current_context
from ._common import MAX_TAGS, RESOURCE_MAX_CHARS, safe_resource
```

Append after `build_databases_payload`:

```python
async def _resolve_consented_record(deps: Deps, uuid: str):
    """Fetch a record and enforce the per-database consent gate.

    Stdio / local (no request context) bypasses consent. Under an HTTP
    principal: a record whose database is not authorized, OR whose
    `database_uuid` cannot be determined, is denied (fail-closed) — we
    must not leak content from a database we cannot verify.
    """
    record = await deps.adapter.get_record(uuid)
    ctx = current_context()
    if ctx is not None:
        db_uuid = record.database_uuid
        if not db_uuid:
            raise ReconsentRequiredError(
                principal_id=ctx.principal_id,
                database_uuid="(unknown)",
                database_name=record.name,
            )
        deps.consent.check_or_raise(
            ctx.principal_id, db_uuid, database_name=record.name
        )
    return record


async def build_record_metadata_payload(deps: Deps, uuid: str) -> dict[str, Any]:
    record = await _resolve_consented_record(deps, uuid)
    tags_truncated = len(record.tags) > MAX_TAGS
    if tags_truncated:
        record = record.model_copy(update={"tags": record.tags[:MAX_TAGS]})
    model = RecordMetadataResource(record=record, tags_truncated=tags_truncated)
    return model.model_dump(mode="json")


async def build_record_text_payload(deps: Deps, uuid: str) -> dict[str, Any]:
    record = await _resolve_consented_record(deps, uuid)
    text = await deps.adapter.get_record_text(uuid, max_chars=RESOURCE_MAX_CHARS)
    truncated = len(text) >= RESOURCE_MAX_CHARS
    model = RecordTextResource(
        uuid=record.uuid,
        text=text,
        truncated=truncated,
        returned_chars=len(text),
    )
    return model.model_dump(mode="json")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_resources_record.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git checkout -b feat/0.5.0-resource-records
git add apps/server/src/istefox_dt_mcp_server/resources/dt_resources.py tests/unit/test_resources_record.py
git commit -m "feat(resources): record metadata/text builders + consent gate"
```

### Task 7: Register the two record resources

**Files:**
- Modify: `apps/server/src/istefox_dt_mcp_server/resources/dt_resources.py` (`register`)
- Test: `tests/unit/test_resources_record.py` (append)

- [ ] **Step 1: Write the failing test** (append to `tests/unit/test_resources_record.py`)

```python
import json

from fastmcp import FastMCP
from istefox_dt_mcp_server.resources.dt_resources import register


@pytest.mark.asyncio
async def test_record_resources_registered(deps: Deps) -> None:
    deps.adapter.get_record.return_value = _record()  # type: ignore[attr-defined]
    deps.adapter.get_record_text.return_value = "hello"  # type: ignore[attr-defined]
    mcp: FastMCP = FastMCP(name="test")
    register(mcp, deps)

    meta = await mcp.read_resource("dt://record/R-1/metadata")
    assert json.loads(meta.contents[0].content)["record"]["uuid"] == "R-1"

    txt = await mcp.read_resource("dt://record/R-1/text")
    assert json.loads(txt.contents[0].content)["text"] == "hello"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_resources_record.py::test_record_resources_registered -q`
Expected: FAIL — only `dt://databases` is registered; `read_resource` raises "Unknown resource".

- [ ] **Step 3: Add the two `@mcp.resource` wrappers**

In `register()` in `dt_resources.py`, after the existing `dt_databases` resource, add:

```python
    @mcp.resource(
        "dt://record/{uuid}/metadata",
        name="dt-record-metadata",
        mime_type="application/json",
        description=(
            "Metadata card for one DEVONthink record (no document body). "
            "Consent-gated, deterministic, read-only."
        ),
    )
    async def dt_record_metadata(uuid: str) -> str:
        return await safe_resource(
            uri=f"dt://record/{uuid}/metadata",
            deps=deps,
            operation=lambda: build_record_metadata_payload(deps, uuid),
        )

    @mcp.resource(
        "dt://record/{uuid}/text",
        name="dt-record-text",
        mime_type="application/json",
        description=(
            "Plain text of one DEVONthink record, truncated to a fixed "
            "bound. Consent-gated, deterministic, read-only."
        ),
    )
    async def dt_record_text(uuid: str) -> str:
        return await safe_resource(
            uri=f"dt://record/{uuid}/text",
            deps=deps,
            operation=lambda: build_record_text_payload(deps, uuid),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_resources_record.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check apps tests/unit/test_resources_record.py
uv run black apps tests/unit/test_resources_record.py
uv run mypy apps libs
git add apps/server/src/istefox_dt_mcp_server/resources/dt_resources.py tests/unit/test_resources_record.py
git commit -m "feat(resources): register dt://record metadata + text resources"
```

---

# PR 4 — prompts

Branch: `feat/0.5.0-prompts` (off `feat/0.5.0-resources-schemas`; independent of PR2/PR3)

### Task 8: Prompt template functions + registration

**Files:**
- Create: `apps/server/src/istefox_dt_mcp_server/prompts/__init__.py`
- Create: `apps/server/src/istefox_dt_mcp_server/prompts/dt_prompts.py`
- Modify: `apps/server/src/istefox_dt_mcp_server/server.py` (import + register call)
- Test: `tests/unit/test_prompts.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_prompts.py`:

```python
"""MCP prompt tests (0.5.0)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastmcp import FastMCP
from istefox_dt_mcp_server.prompts.dt_prompts import (
    register,
    triage_inbox_text,
    weekly_review_text,
)

if TYPE_CHECKING:
    from istefox_dt_mcp_server.deps import Deps


def test_weekly_review_default_italian() -> None:
    t = weekly_review_text(None, "it")
    assert "review settimanale" in t
    assert "list_databases" in t
    assert "sola lettura" in t


def test_weekly_review_scopes_databases() -> None:
    t = weekly_review_text("Alpha,Beta", "it")
    assert "Alpha,Beta" in t


def test_weekly_review_english() -> None:
    t = weekly_review_text(None, "en")
    assert "weekly review" in t.lower()
    assert "read-only" in t.lower()


def test_triage_inbox_dry_run_only_by_default() -> None:
    t = triage_inbox_text("Inbox", "it", apply=False)
    assert "dry_run=true" in t
    assert "NON applicare" in t
    assert "dry_run=false" not in t


def test_triage_inbox_apply_explains_confirm_token() -> None:
    t = triage_inbox_text("Inbox", "it", apply=True)
    assert "dry_run=false" in t
    assert "confirm_token" in t


@pytest.mark.asyncio
async def test_prompts_registered(deps: Deps) -> None:
    mcp: FastMCP = FastMCP(name="test")
    register(mcp, deps)
    assert await mcp.get_prompt("weekly_review") is not None
    assert await mcp.get_prompt("triage_inbox") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_prompts.py -q`
Expected: FAIL with `ModuleNotFoundError: ... prompts.dt_prompts`

- [ ] **Step 3: Create the package marker**

Create `apps/server/src/istefox_dt_mcp_server/prompts/__init__.py`:

```python
"""MCP prompt registrations (0.5.0)."""
```

- [ ] **Step 4: Create `dt_prompts.py`**

Create `apps/server/src/istefox_dt_mcp_server/prompts/dt_prompts.py`:

```python
"""DEVONthink MCP prompts (0.5.0).

Template-only: no deps, no JXA, no adapter calls. They emit guidance
that orchestrates the existing tools. User-facing text is Italian by
default (`lang="it"`); `lang="en"` switches. Tool names stay English
because MCP clients select tools better in English.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from ..deps import Deps


def weekly_review_text(databases: str | None, lang: str) -> str:
    """Render the weekly-review prompt body."""
    if lang == "en":
        scope = f" (limit to: {databases})" if databases else ""
        return (
            "Run a weekly review of the DEVONthink databases.\n\n"
            "1. If I didn't name databases, call the `list_databases` tool "
            "and list the open ones.\n"
            f"2. For each database{scope}, use `search` (or `summarize_topic` "
            "if available) to find records added or modified in the last 7 "
            "days.\n"
            "3. Use `find_related` on the 2-3 most relevant records to "
            "surface thematic clusters.\n"
            "4. Produce a structured digest: per database, the main themes, "
            "key documents (with reference_url), and 3 suggested actions.\n"
            "This is read-only: do not modify anything."
        )
    scope = f" (limitati a: {databases})" if databases else ""
    return (
        "Esegui una review settimanale dei database DEVONthink.\n\n"
        "1. Se non ti ho indicato database, chiama il tool `list_databases` "
        "ed elenca quelli aperti.\n"
        f"2. Per ciascun database{scope}, usa `search` (o `summarize_topic` "
        "se disponibile) per individuare i record aggiunti o modificati "
        "negli ultimi 7 giorni.\n"
        "3. Usa `find_related` sui 2-3 record più rilevanti per scoprire "
        "cluster tematici.\n"
        "4. Produci un digest strutturato: per ogni database i temi "
        "principali, i documenti chiave (con reference_url) e 3 azioni "
        "suggerite.\n"
        "Questa è una review in sola lettura: non modificare nulla."
    )


def triage_inbox_text(inbox_database: str, lang: str, apply: bool) -> str:
    """Render the inbox-triage prompt body."""
    if lang == "en":
        tail = (
            "3. After I approve a preview, call `file_document` again with "
            "dry_run=false and confirm_token = the audit_id returned by the "
            "matching preview (the token is one-shot and expires in 5 "
            "minutes)."
            if apply
            else "3. Do NOT apply: stop at the preview and wait for my "
            "explicit confirmation."
        )
        return (
            f"Triage the '{inbox_database}' inbox in DEVONthink.\n\n"
            f"1. Use `search` with a broad query limited to the "
            f"'{inbox_database}' database to list unfiled records.\n"
            "2. For each record call `file_document` with dry_run=true and "
            "show me the proposed classification/tags preview, applying "
            "nothing.\n"
            f"{tail}"
        )
    tail = (
        "3. Dopo che ho approvato una preview, richiama `file_document` con "
        "dry_run=false e confirm_token = l'audit_id restituito dalla preview "
        "corrispondente (il token è monouso e scade in 5 minuti)."
        if apply
        else "3. NON applicare: fermati alla preview e aspetta una mia "
        "conferma esplicita."
    )
    return (
        f"Esegui il triage dell'inbox '{inbox_database}' di DEVONthink.\n\n"
        f"1. Usa `search` con una query ampia limitata al database "
        f"'{inbox_database}' per elencare i record non archiviati.\n"
        "2. Per ogni record chiama `file_document` con dry_run=true e "
        "mostrami la preview di classificazione/tag proposti, senza "
        "applicare nulla.\n"
        f"{tail}"
    )


def register(mcp: FastMCP, deps: Deps) -> None:
    del deps  # prompts are static templates; no deps needed

    @mcp.prompt(
        name="weekly_review",
        description="Guida una review settimanale dei documenti DEVONthink recenti.",
    )
    def weekly_review(databases: str | None = None, lang: str = "it") -> str:
        return weekly_review_text(databases, lang)

    @mcp.prompt(
        name="triage_inbox",
        description="Guida il triage dell'Inbox DEVONthink con file_document in dry-run.",
    )
    def triage_inbox(
        inbox_database: str = "Inbox",
        lang: str = "it",
        apply: bool = False,
    ) -> str:
        return triage_inbox_text(inbox_database, lang, apply)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_prompts.py -q`
Expected: PASS (6 passed)

- [ ] **Step 6: Wire into `server.py`**

In `apps/server/src/istefox_dt_mcp_server/server.py`:

(a) After the `from .resources import dt_resources as resource_dt` line add:

```python
from .prompts import dt_prompts as prompt_dt
```

(b) After the `resource_dt.register(mcp, deps)` line add:

```python
    prompt_dt.register(mcp, deps)
```

> If PR4 lands before PR2, instead add `from .prompts import dt_prompts as prompt_dt` after line 22 and `prompt_dt.register(mcp, deps)` after line 65; reconcile at merge.

- [ ] **Step 7: Gate + commit**

```bash
git checkout -b feat/0.5.0-prompts
uv run ruff check apps tests/unit/test_prompts.py
uv run black apps tests/unit/test_prompts.py
uv run mypy apps libs
git add apps/server/src/istefox_dt_mcp_server/ tests/unit/test_prompts.py
git commit -m "feat(prompts): weekly_review + triage_inbox prompts + wiring"
```

---

# PR 5 — integration, smoke, release

Branch: `chore/0.5.0-release` (off the integration branch where PR2-4 are merged)

### Task 9: Tier-3 integration test

**Files:**
- Create: `tests/integration/test_resources_live.py`

- [ ] **Step 1: Write the integration test**

Create `tests/integration/test_resources_live.py`:

```python
"""Tier-3: dt:// resources against a real DEVONthink (0.5.0).

Skipped by default. Run: `uv run pytest -m integration
tests/integration/test_resources_live.py`. Reuses the autouse
`dt_running` guard and `live_deps` fixture from
tests/integration/conftest.py.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from istefox_dt_mcp_server.resources._common import RESOURCE_JSON_BUDGET_CHARS
from istefox_dt_mcp_server.resources.dt_resources import (
    build_databases_payload,
    build_record_metadata_payload,
    build_record_text_payload,
)

if TYPE_CHECKING:
    from istefox_dt_mcp_server.deps import Deps

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_resource_roundtrip_live(live_deps: Deps) -> None:
    dbs = await build_databases_payload(live_deps)
    assert isinstance(dbs["databases"], list)
    if not dbs["databases"]:
        pytest.skip("No open databases")

    # Pick a real record via a broad search on the first database.
    db_name = dbs["databases"][0]["name"]
    hits = await live_deps.adapter.search("a", databases=[db_name], max_results=1)
    if not hits:
        pytest.skip(f"No records found in {db_name}")
    uuid = hits[0].uuid

    meta = await build_record_metadata_payload(live_deps, uuid)
    assert meta["record"]["uuid"] == uuid

    txt = await build_record_text_payload(live_deps, uuid)
    body = json.dumps(txt)
    assert len(body) <= RESOURCE_JSON_BUDGET_CHARS
    assert txt["returned_chars"] == len(txt["text"])
```

- [ ] **Step 2: Run (will skip without DT, that's expected in CI)**

Run: `uv run pytest -m integration tests/integration/test_resources_live.py -q`
Expected: SKIPPED (no DT) or PASS (DT running locally)

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_resources_live.py
git commit -m "test(integration): live dt:// resource roundtrip"
```

### Task 10: Smoke E2E step

**Files:**
- Modify: `scripts/smoke_e2e.py:135` (after the `find_related` block, before the `--- W2 GO/NO-GO summary ---` comment at line 136)

- [ ] **Step 1: Insert the resource smoke step**

In `scripts/smoke_e2e.py`, immediately after line 134 (the end of the `find_related` `except AdapterError` block) and before line 136 (`# --- W2 GO/NO-GO summary ---`), insert:

```python
    # --- dt:// resources (0.5.0) ---
    print("\n[resources]")
    try:
        from istefox_dt_mcp_server.deps import build_default_deps
        from istefox_dt_mcp_server.resources._common import (
            RESOURCE_JSON_BUDGET_CHARS,
        )
        from istefox_dt_mcp_server.resources.dt_resources import (
            build_databases_payload,
            build_record_metadata_payload,
            build_record_text_payload,
        )

        smoke_deps = build_default_deps(cache_enabled=False)
        seed_results = await adapter.search("the", max_results=1)
        if seed_results:
            seed_uuid = seed_results[0].uuid
            samples, _ = await _measure(
                "resource:databases",
                lambda: build_databases_payload(smoke_deps),
            )
            all_samples["resource:databases"] = samples
            samples, _ = await _measure(
                "resource:record/metadata",
                lambda: build_record_metadata_payload(smoke_deps, seed_uuid),
            )
            all_samples["resource:metadata"] = samples
            samples, txt = await _measure(
                "resource:record/text",
                lambda: build_record_text_payload(smoke_deps, seed_uuid),
            )
            all_samples["resource:text"] = samples
            body_len = len(json.dumps(txt))  # type: ignore[arg-type]
            assert body_len <= RESOURCE_JSON_BUDGET_CHARS, (
                f"resource text body {body_len} exceeds bound"
            )
            print(f"  text body bytes={body_len} (bound {RESOURCE_JSON_BUDGET_CHARS})")
        else:
            print("  no seed record available")
    except AdapterError as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
```

(Add `import json` is already present at module level via stdlib? It is not — verify line 17-24. The script imports `asyncio, statistics, sys, time`. Add `import json` to the import block at the top: change the stdlib import group to include `import json`.)

- [ ] **Step 2: Add the `json` import**

In `scripts/smoke_e2e.py`, in the import block (lines 17-20), add `import json` so the block reads:

```python
import asyncio
import json
import statistics
import sys
import time
```

- [ ] **Step 3: Run the smoke script (local, DT running)**

Run: `uv run python scripts/smoke_e2e.py`
Expected: prints a `[resources]` section with latency + `text body bytes=... (bound 80000)`, verdict `PASS ✓`. (If DT not available, this step is validated by the maintainer on their Mac before release.)

- [ ] **Step 4: Commit**

```bash
git add scripts/smoke_e2e.py
git commit -m "test(smoke): exercise dt:// resource code path"
```

### Task 11: Docs + release

**Files:**
- Modify: `CHANGELOG.md`, `README.md`, `docs/architecture.md`, `handoff.md`, `memory.md`, `manifest.json`
- (`SERVER_VERSION` already bumped to `0.5.0` in PR2 Task 5)

- [ ] **Step 1: CHANGELOG entry**

Add a dated `## [0.5.0] - 2026-05-17` section to `CHANGELOG.md` (Keep a Changelog format) under `### Added`:

```markdown
### Added
- MCP Resources: `dt://databases`, `dt://record/{uuid}/metadata`,
  `dt://record/{uuid}/text` — read-only, deterministic, bounded
  (≤25K token), consent-gated (ADR-0009).
- MCP Prompts: `weekly_review`, `triage_inbox` (template-only,
  orchestrate existing tools).
```

- [ ] **Step 2: Bump `manifest.json` to 0.5.0**

In `manifest.json`, change the `"version"` field to `"0.5.0"`.

- [ ] **Step 3: README + architecture**

In `README.md`, add the 3 resources and 2 prompts to the capability list/section that currently enumerates the 7 tools. In `docs/architecture.md`, add a short subsection "MCP Resources & Prompts (0.5.0)" referencing ADR-0009 and the `safe_resource` gate.

- [ ] **Step 4: Update handoff.md + memory.md**

In `handoff.md`, set the snapshot to 0.5.0 (resources+prompts shipped) and move the "Annuncio 0.5.0" / next-options forward. In `memory.md`, add a `## Log modifiche` entry dated 2026-05-17 noting the 0.5.0 protocol-completeness bundle.

- [ ] **Step 5: Full gate**

Run:
```bash
uv run ruff check apps libs
uv run black --check apps libs
uv run mypy apps libs
uv run pytest tests/unit tests/contract -q
```
Expected: all green; unit count = previous baseline + new resource/prompt tests.

- [ ] **Step 6: Commit + release**

```bash
git add CHANGELOG.md manifest.json README.md docs/architecture.md handoff.md memory.md
git commit -m "chore: release v0.5.0"
```

Then follow the established release runbook (memory `release_workflow.md`): merge the feature branches into `main` via PRs, then `gh workflow run release.yml -f version=0.5.0`, verify the tag + `publish-registry.yml` chain, confirm the `.mcpb` bundle + MCP Registry show v0.5.0.

---

## Self-Review

**1. Spec coverage:**
- Spec §2 G1 (3 resources) → Tasks 5, 7. G2 (determinism) → Task 5 Step 1 `test_determinism_byte_identical`. G3 (bound ≤25K) → Task 3 + Task 6 `test_text_payload_bounded`. G4 (scope+consent, raise, audit) → Task 4 + Task 6 consent tests. G5 (2 prompts, IT/EN) → Task 8. G6 (ADR) → Task 1. G7 (4-tier tests) → Tasks 2-10. G8 (zero deps / JXA / adapter) → no `pyproject.toml`/`contract.py`/`scripts/*.js` changes anywhere in the plan. ✓
- Spec §4.2 (`safe_resource` not `safe_call`) → Task 4. §4.4 (consent, fail-closed on missing `database_uuid`) → Task 6 `_resolve_consented_record` + `test_record_missing_db_uuid_fails_closed_under_http`. §4.5 (`bound_json`) → Task 3. §4.6 prompts → Task 8. §5 ADR → Task 1. §6 file list → matches File Structure table. §7 test tiers → Tasks 2/3/4/5/6/7/8 (unit), Task 9 (integration), Task 10 (smoke); contract intentionally none (justified). §8 build sequence → PR1-5 mapping. §9 no open questions. ✓

**2. Placeholder scan:** No "TBD/TODO/implement later". Every code step shows complete code. Release runbook (Task 11 Step 6) defers to the existing `release_workflow.md` memory — that is an existing documented procedure, not a placeholder.

**3. Type consistency:** `safe_resource(*, uri, deps, operation)` signature identical in Task 4 definition and Tasks 5/7 call sites. `build_databases_payload(deps)`, `build_record_metadata_payload(deps, uuid)`, `build_record_text_payload(deps, uuid)`, `_resolve_consented_record(deps, uuid)` consistent across Tasks 5/6/7/9/10. Schema names `DatabaseListResource`/`RecordMetadataResource`/`RecordTextResource` consistent (Task 2 def ↔ Tasks 5/6 use). Constants `RESOURCE_MAX_CHARS`/`RESOURCE_JSON_BUDGET_CHARS`/`MAX_TAGS` consistent (Task 3 def ↔ Tasks 4/6/9/10 use). `weekly_review_text(databases, lang)` / `triage_inbox_text(inbox_database, lang, apply)` consistent (Task 8 def ↔ test). `ResourceContent.content` attribute used consistently in wiring tests (verified against fastmcp 3.2.4 `resources/base.py`). ✓
