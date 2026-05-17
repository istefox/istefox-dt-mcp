"""DEVONthink MCP resources (0.5.0).

Pure async builders hold the logic (testable without FastMCP); thin
`@mcp.resource` wrappers delegate through `safe_resource`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from istefox_dt_mcp_schemas.tools import (
    DatabaseListResource,
    RecordMetadataResource,
    RecordTextResource,
)

from ..auth.consent import ReconsentRequiredError
from ..auth.scope import current_context
from ._common import MAX_TAGS, RESOURCE_MAX_CHARS, safe_resource

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from istefox_dt_mcp_schemas.common import Record

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


async def _resolve_consented_record(deps: Deps, uuid: str) -> Record:
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
            # Sentinel: DB unverifiable for this principal — not a real UUID.
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
    # Load-bearing: resolves the record AND enforces the per-DB consent
    # gate before any text is fetched. Do not inline get_record_text past it.
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
