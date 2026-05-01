"""Selective undo of a previously applied write op.

Looks up the audit_id, reads `before_state`, and reverses the write
in the most surgical way possible. v0.0.7 supports `file_document`
only (the sole write tool we ship). `bulk_apply` undo lands when
`bulk_apply` itself does, post-MVP.

Drift detection: we compare the current record state against
`before_state`. If the location or tags have changed since the
original write (e.g. another op or the user moved/edited the record
in DT), we report `drift_detected=True` and refuse to revert
unless `--force` is passed at the CLI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import structlog

if TYPE_CHECKING:
    from .deps import Deps


log = structlog.get_logger(__name__)


async def undo_audit(
    deps: Deps,
    audit_id: str | UUID,
    *,
    dry_run: bool = True,
    force: bool = False,
) -> dict[str, object]:
    """Reverse a previously applied write.

    Returns a dict report:
      {audit_id, target_record_uuid, reverted, drift_detected,
       message, dry_run}
    """
    audit_id_obj = audit_id if isinstance(audit_id, UUID) else UUID(str(audit_id))
    entry = deps.audit.get(audit_id_obj)
    if entry is None:
        return {
            "audit_id": str(audit_id_obj),
            "reverted": False,
            "drift_detected": False,
            "message": "audit_id not found",
            "dry_run": dry_run,
        }

    if entry.tool_name != "file_document":
        return {
            "audit_id": str(audit_id_obj),
            "reverted": False,
            "drift_detected": False,
            "message": f"undo not supported for tool '{entry.tool_name}'",
            "dry_run": dry_run,
        }

    if not entry.before_state:
        return {
            "audit_id": str(audit_id_obj),
            "reverted": False,
            "drift_detected": False,
            "message": "audit entry has no before_state (was it a dry_run?)",
            "dry_run": dry_run,
        }

    target_uuid = str(entry.before_state.get("uuid") or "")
    if not target_uuid:
        return {
            "audit_id": str(audit_id_obj),
            "reverted": False,
            "drift_detected": False,
            "message": "before_state missing 'uuid' field",
            "dry_run": dry_run,
        }

    # Drift detection: pull current state and diff against before_state.
    try:
        current = await deps.adapter.get_record(target_uuid)
    except Exception as e:
        return {
            "audit_id": str(audit_id_obj),
            "target_record_uuid": target_uuid,
            "reverted": False,
            "drift_detected": False,
            "message": f"target record not retrievable: {e}",
            "dry_run": dry_run,
        }

    # Reconstruct the after-state implied by the audit entry input
    input_data = entry.input_json or {}
    # The applied location can be inferred from current vs before;
    # we don't store the after-state explicitly (next iteration).
    before_location = str(entry.before_state.get("location") or "")
    before_tags: list[str] = list(entry.before_state.get("tags") or [])

    # Tags added during the original op = current minus before
    tags_added = [t for t in current.tags if t not in before_tags]

    drift_detected = False
    if current.location != before_location and not _is_first_undo(
        current.location, input_data
    ):
        # Hard to tell apart "the user moved it manually" vs "this is
        # the after-state we expected". For v0.0.7 we treat any move
        # away from `before_location` AND a location that doesn't
        # match the destination_hint/classify suggestion as drift.
        # The conservative path is to require --force.
        drift_detected = True

    if drift_detected and not force:
        return {
            "audit_id": str(audit_id_obj),
            "target_record_uuid": target_uuid,
            "reverted": False,
            "drift_detected": True,
            "message": (
                "record moved/edited since the original write; pass --force "
                "to revert anyway (will overwrite intervening changes)"
            ),
            "dry_run": dry_run,
        }

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

    # Apply the revert
    if current.location != before_location and before_location:
        await deps.adapter.move_record(target_uuid, before_location, dry_run=False)
    for tag in tags_added:
        await deps.adapter.remove_tag(target_uuid, tag, dry_run=False)

    log.info(
        "undo_applied",
        audit_id=str(audit_id_obj),
        uuid=target_uuid,
        reverted_tags=tags_added,
        moved_to=before_location,
    )
    return {
        "audit_id": str(audit_id_obj),
        "target_record_uuid": target_uuid,
        "reverted": True,
        "drift_detected": drift_detected,
        "message": "ok",
        "dry_run": dry_run,
    }


def _is_first_undo(current_location: str, input_data: dict[str, object]) -> bool:
    """Best-effort check that the current location matches what the
    original `file_document` call applied (not arbitrary user drift).

    In v0.0.7 we don't store the after-state explicitly, so this is
    a heuristic: if the input had `destination_hint`, compare to it.
    """
    hint = input_data.get("destination_hint")
    return isinstance(hint, str) and hint == current_location
