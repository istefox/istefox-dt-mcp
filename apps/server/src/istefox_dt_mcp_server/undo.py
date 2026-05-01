"""Selective undo of a previously applied write op.

Looks up the audit_id, reads `before_state` (the original record
snapshot) and `after_state` (the snapshot we expected immediately
after the write), and reverses the write surgically. v0.0.7 supports
`file_document` only.

Drift detection (v0.0.10+):
- If `after_state` is present in the audit entry, drift = the current
  DT state diverges from after_state. This is the precise check.
- If `after_state` is missing (legacy entries pre-W10), fall back to
  the heuristic that compares current.location against the original
  destination_hint.

`drift_detected=True` blocks the revert unless `force=True`.
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
