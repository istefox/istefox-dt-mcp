"""file_document tool — auto-classify + tag a record (preview-then-apply).

Two-phase contract:
1. **Preview** (default, `dry_run=true`): server inspects the record,
   asks DT4's classifier for suggested destinations, and returns a
   `FileDocumentPreview` plus a `preview_token` (the audit_id of this
   call). NO mutation happens.
2. **Apply** (`dry_run=false`, `confirm_token=<previous preview_token>`):
   server applies the move + tag actions, persisting the original
   `before_state` in the audit log. Selective undo via the audit_id.

Why two phases: the LLM should NEVER apply a write op directly. The
client (Claude) shows the user what will change, the user confirms
out-of-band, then the second call commits with the token.

Since v0.0.9 the `confirm_token` is **hard-enforced**: apply calls
without a valid, non-expired (TTL 5min default), unconsumed token
that points back to a previous dry_run of *this* tool are rejected
with `INVALID_PREVIEW_TOKEN` / `EXPIRED_PREVIEW_TOKEN` /
`CONSUMED_PREVIEW_TOKEN`. Override TTL via `ISTEFOX_PREVIEW_TTL_S`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from istefox_dt_mcp_schemas.common import WriteOutcome
from istefox_dt_mcp_schemas.tools import (
    FileDocumentInput,
    FileDocumentOutput,
    FileDocumentPreview,
    FileDocumentResult,
)

from ._common import safe_call, validate_confirm_token

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from istefox_dt_mcp_schemas.common import Record

    from ..deps import Deps


log = structlog.get_logger(__name__)


def register(mcp: FastMCP, deps: Deps) -> None:
    @mcp.tool()
    async def file_document(
        input: FileDocumentInput,  # noqa: A002 — input shadow is intentional
    ) -> FileDocumentOutput:
        # We need the record snapshot before everything else: it
        # both feeds the preview (location_before, current tags) and
        # is the before_state for selective undo.
        try:
            record = await deps.adapter.get_record(input.record_uuid)
        except Exception:
            # Let safe_call's adapter-error path handle the audit + envelope
            async def fail_op() -> FileDocumentResult:
                # Re-raise inside the operation so safe_call captures it
                await deps.adapter.get_record(input.record_uuid)
                raise RuntimeError("unreachable")

            return await safe_call(
                tool_name="file_document",
                input_data=input.model_dump(),
                deps=deps,
                operation=fail_op,
                output_factory=FileDocumentOutput,
            )

        before_state = {
            "uuid": record.uuid,
            "location": record.location,
            "tags": list(record.tags),
            "name": record.name,
        }

        async def op() -> FileDocumentResult:
            preview = await _build_preview(deps, record, input)

            if input.dry_run:
                return FileDocumentResult(
                    record_uuid=input.record_uuid,
                    preview=preview,
                    would_apply=_preview_has_changes(preview),
                    applied=False,
                    preview_token=None,  # filled with audit_id by the wrapper
                )

            # Hard enforcement: apply requires a valid, non-expired,
            # unconsumed preview_token. Raises (caught by safe_call).
            validate_confirm_token(
                deps,
                tool_name="file_document",
                confirm_token=input.confirm_token,
            )

            # Apply move
            if preview.destination_group:
                await deps.adapter.move_record(
                    input.record_uuid,
                    preview.destination_group,
                    dry_run=False,
                )
            # Apply tag mutations
            for tag in preview.tags_to_add:
                await deps.adapter.apply_tag(input.record_uuid, tag, dry_run=False)
            for tag in preview.tags_to_remove:
                await deps.adapter.remove_tag(input.record_uuid, tag, dry_run=False)

            return FileDocumentResult(
                record_uuid=input.record_uuid,
                preview=preview,
                would_apply=True,
                applied=True,
                preview_token=None,
            )

        result: FileDocumentOutput = await safe_call(
            tool_name="file_document",
            input_data=input.model_dump(),
            deps=deps,
            operation=op,
            output_factory=FileDocumentOutput,
            before_state=before_state,
        )
        # Echo the audit_id back as preview_token so the client can
        # reuse it on the apply call.
        if result.success and result.data is not None and result.audit_id is not None:
            result.data.preview_token = str(result.audit_id)
            # Persist after_state for successful apply, so undo can do
            # precise drift detection. We REFETCH the record here
            # (rather than reconstructing from before_state + preview)
            # because DT exposes record.location relative to the
            # database (e.g. "/MCP-Test/"), while destination_hint is
            # absolute including the database prefix
            # ("/Inbox/MCP-Test"). Storing the input would mismatch
            # what undo sees on subsequent get_record calls and
            # trigger a false drift_detected. One extra get_record is
            # cheap (~150ms warm) and worth the precision.
            if result.data.applied:
                try:
                    record_after = await deps.adapter.get_record(input.record_uuid)
                    deps.audit.set_after_state(
                        result.audit_id,
                        {
                            "uuid": record_after.uuid,
                            "location": record_after.location,
                            "tags": sorted(record_after.tags),
                            "name": record_after.name,
                        },
                    )
                except Exception as e:
                    # Don't fail the whole call if the refetch errors;
                    # undo will fall back to the heuristic drift check.
                    log.debug(
                        "file_document_after_state_refetch_failed",
                        uuid=input.record_uuid,
                        error=str(e),
                    )
        return result


async def _build_preview(
    deps: Deps,
    record: Record,
    input: FileDocumentInput,  # noqa: A002
) -> FileDocumentPreview:
    """Compose a FileDocumentPreview from classify + tag heuristics."""
    destination: str | None = None

    if input.destination_hint:
        destination = input.destination_hint
    elif input.auto_classify:
        try:
            suggestions = await deps.adapter.classify_record(input.record_uuid, top_n=1)
        except Exception as e:
            log.debug("file_document_classify_failed", error=str(e))
            suggestions = []
        if suggestions:
            destination = suggestions[0].location

    # Don't propose a no-op move
    if destination and destination == record.location:
        destination = None

    tags_to_add: list[str] = []
    if input.auto_tag and destination:
        # Naive heuristic: last segment of the destination becomes a
        # tag candidate (skip if it's already on the record).
        leaf = destination.rstrip("/").rsplit("/", 1)[-1]
        if leaf and leaf not in record.tags:
            tags_to_add.append(leaf)

    return FileDocumentPreview(
        destination_group=destination,
        tags_to_add=tags_to_add,
        tags_to_remove=[],  # auto-suggested tag removal is post-MVP
        rename_to=None,  # auto-rename is post-MVP
    )


def _preview_has_changes(preview: FileDocumentPreview) -> bool:
    return bool(
        preview.destination_group
        or preview.tags_to_add
        or preview.tags_to_remove
        or preview.rename_to
    )


# Suppress the unused import warning for WriteOutcome — it's part of
# the schema contract and re-exported for callers that build custom
# previews.
_unused = WriteOutcome
