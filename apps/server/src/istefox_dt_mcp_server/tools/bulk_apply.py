"""bulk_apply tool — execute many small ops with preview-then-apply.

Same two-phase contract as `file_document`:
1. **Preview** (`dry_run=true`, default): validate each op, return a
   list of `BulkOpOutcome(status='planned')` plus a `preview_token`
   (the audit_id of this call). NO mutation happens.
2. **Apply** (`dry_run=false` + `confirm_token=<previous preview_token>`):
   execute the ops in order. On failure, behavior depends on
   `stop_on_first_error` (default true).

Failure model: DEVONthink has no transactions, so we cannot
auto-rollback already-applied ops. With `stop_on_first_error=true`
the batch halts at the first failure; outcomes report exactly which
ops applied. The user can selectively undo applied ops by audit_id
(future: chained undo via parent audit_id).

Op dispatch: `add_tag` / `remove_tag` / `move`. Unknown op types are
reported as `failed` with `INVALID_INPUT` and don't reach the adapter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from istefox_dt_mcp_adapter.errors import AdapterError
from istefox_dt_mcp_schemas.tools import (
    BulkApplyInput,
    BulkApplyOperation,
    BulkApplyOutput,
    BulkApplyResult,
    BulkOpOutcome,
)

from ._common import safe_call

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from ..deps import Deps


log = structlog.get_logger(__name__)

_VALID_OPS = frozenset({"add_tag", "remove_tag", "move"})


def register(mcp: FastMCP, deps: Deps) -> None:
    @mcp.tool()
    async def bulk_apply(
        input: BulkApplyInput,  # noqa: A002 — input shadow is intentional
    ) -> BulkApplyOutput:
        async def op() -> BulkApplyResult:
            outcomes: list[BulkOpOutcome] = []

            if input.dry_run:
                # Preview: just validate each op shape, no adapter calls
                for idx, bop in enumerate(input.operations):
                    outcomes.append(_validate_op(idx, bop))
                return BulkApplyResult(
                    operations_total=len(input.operations),
                    operations_applied=0,
                    failed_index=_first_failed_index(outcomes),
                    preview_token=None,  # filled by wrapper
                    outcomes=outcomes,
                )

            if not input.confirm_token:
                log.warning(
                    "bulk_apply_apply_without_confirm_token",
                    n_ops=len(input.operations),
                )

            # Apply phase: dispatch each op
            applied = 0
            failed_index: int | None = None
            for idx, bop in enumerate(input.operations):
                # Validate first; skip adapter call on bad input
                validation = _validate_op(idx, bop)
                if validation.status == "failed":
                    outcomes.append(validation)
                    if failed_index is None:
                        failed_index = idx
                    if input.stop_on_first_error:
                        break
                    continue

                try:
                    await _dispatch_op(deps, bop)
                except AdapterError as e:
                    outcomes.append(
                        BulkOpOutcome(
                            index=idx,
                            record_uuid=bop.record_uuid,
                            op=bop.op,
                            status="failed",
                            error_code=e.code.value,
                            error_message=str(e),
                        )
                    )
                    if failed_index is None:
                        failed_index = idx
                    if input.stop_on_first_error:
                        break
                    continue

                outcomes.append(
                    BulkOpOutcome(
                        index=idx,
                        record_uuid=bop.record_uuid,
                        op=bop.op,
                        status="applied",
                    )
                )
                applied += 1

            return BulkApplyResult(
                operations_total=len(input.operations),
                operations_applied=applied,
                failed_index=failed_index,
                preview_token=None,
                outcomes=outcomes,
            )

        # before_state for bulk: just the list of ops + record_uuids
        # (per-op snapshots would balloon the audit row; selective
        # undo per op is post-MVP)
        before_state = {
            "operations": [
                {"uuid": o.record_uuid, "op": o.op, "payload": o.payload}
                for o in input.operations
            ],
        }

        result: BulkApplyOutput = await safe_call(
            tool_name="bulk_apply",
            input_data=input.model_dump(),
            deps=deps,
            operation=op,
            output_factory=BulkApplyOutput,
            before_state=before_state,
        )
        if result.success and result.data is not None and result.audit_id is not None:
            result.data.preview_token = str(result.audit_id)
        return result


def _validate_op(idx: int, bop: BulkApplyOperation) -> BulkOpOutcome:
    """Check op type + required payload keys. Returns planned/failed."""
    if bop.op not in _VALID_OPS:
        return BulkOpOutcome(
            index=idx,
            record_uuid=bop.record_uuid,
            op=bop.op,
            status="failed",
            error_code="INVALID_INPUT",
            error_message=f"unknown op {bop.op!r}, expected one of {sorted(_VALID_OPS)}",
        )
    if bop.op in {"add_tag", "remove_tag"}:
        if not bop.payload.get("tag"):
            return BulkOpOutcome(
                index=idx,
                record_uuid=bop.record_uuid,
                op=bop.op,
                status="failed",
                error_code="INVALID_INPUT",
                error_message=f"{bop.op} requires payload.tag",
            )
    elif bop.op == "move" and not bop.payload.get("destination"):
        return BulkOpOutcome(
            index=idx,
            record_uuid=bop.record_uuid,
            op=bop.op,
            status="failed",
            error_code="INVALID_INPUT",
            error_message="move requires payload.destination",
        )
    return BulkOpOutcome(
        index=idx,
        record_uuid=bop.record_uuid,
        op=bop.op,
        status="planned",
    )


async def _dispatch_op(deps: Deps, bop: BulkApplyOperation) -> None:
    """Route op to the adapter. Caller has already validated shape."""
    if bop.op == "add_tag":
        await deps.adapter.apply_tag(bop.record_uuid, bop.payload["tag"], dry_run=False)
    elif bop.op == "remove_tag":
        await deps.adapter.remove_tag(
            bop.record_uuid, bop.payload["tag"], dry_run=False
        )
    elif bop.op == "move":
        await deps.adapter.move_record(
            bop.record_uuid, bop.payload["destination"], dry_run=False
        )


def _first_failed_index(outcomes: list[BulkOpOutcome]) -> int | None:
    for o in outcomes:
        if o.status == "failed":
            return o.index
    return None
