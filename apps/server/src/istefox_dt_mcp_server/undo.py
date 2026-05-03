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

from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

import structlog

from istefox_dt_mcp_schemas.common import Record  # noqa: TC001 — runtime use in compute_drift_state

if TYPE_CHECKING:
    from istefox_dt_mcp_schemas.audit import AuditEntry

    from .deps import Deps


log = structlog.get_logger(__name__)

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

    if entry.tool_name == "bulk_apply":
        return await _undo_bulk_apply(deps, entry, dry_run=dry_run, force=force)

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


async def _undo_bulk_apply(
    deps: Deps,
    entry: AuditEntry,
    *,
    dry_run: bool,
    force: bool,
) -> dict[str, object]:
    """Multi-step undo of a bulk_apply call.

    Reads `after_state.applied` (the list of ops that succeeded with
    their original payloads) and computes the inverse of each:
    - `add_tag`     → `remove_tag` with the same tag
    - `remove_tag`  → `add_tag` with the same tag
    - `move`        → `move` back to `pre_move_snapshots[uuid]`

    Reverts in reverse order (LIFO) so that any local interaction
    between ops is undone in the opposite sequence.

    `force` is currently a no-op for bulk undo (per-op drift detection
    is post-MVP — the audit_after_state doesn't have per-op
    after-snapshots). The flag is accepted for CLI symmetry with
    file_document undo.
    """
    audit_id_str = str(entry.audit_id)
    after = entry.after_state or {}
    applied: list[dict[str, Any]] = after.get("applied") or []
    snapshots: dict[str, str] = after.get("pre_move_snapshots") or {}

    if not applied:
        return {
            "audit_id": audit_id_str,
            "tool_name": "bulk_apply",
            "reverted": False,
            "drift_detected": False,
            "message": "no applied ops recorded — nothing to undo",
            "dry_run": dry_run,
        }

    # Compute inverse ops in LIFO order
    inverse_plan: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for op in reversed(applied):
        uuid = op.get("uuid")
        op_type = op.get("op")
        payload = op.get("payload") or {}
        if not uuid or not op_type:
            continue

        if op_type == "add_tag":
            tag = payload.get("tag")
            if tag:
                inverse_plan.append({"uuid": uuid, "op": "remove_tag", "tag": tag})
        elif op_type == "remove_tag":
            tag = payload.get("tag")
            if tag:
                inverse_plan.append({"uuid": uuid, "op": "add_tag", "tag": tag})
        elif op_type == "move":
            original_location = snapshots.get(uuid)
            if original_location:
                inverse_plan.append(
                    {
                        "uuid": uuid,
                        "op": "move",
                        "destination": original_location,
                    }
                )
            else:
                # No snapshot → can't safely undo; skip with reason
                skipped.append({"uuid": uuid, "reason": "no pre-move snapshot"})
        else:
            skipped.append({"uuid": uuid, "reason": f"unknown op {op_type}"})

    if dry_run:
        return {
            "audit_id": audit_id_str,
            "tool_name": "bulk_apply",
            "reverted": False,
            "drift_detected": False,
            "would_revert": inverse_plan,
            "skipped": skipped,
            "n_ops_to_revert": len(inverse_plan),
            "force_acknowledged": force,
            "dry_run": True,
            "message": "dry_run preview",
        }

    # Apply phase: execute the inverse ops in order. Best-effort —
    # one failure does not abort the rest, but is reported.
    reverted_count = 0
    failures: list[dict[str, str]] = []
    for inv in inverse_plan:
        try:
            if inv["op"] == "remove_tag":
                await deps.adapter.remove_tag(inv["uuid"], inv["tag"], dry_run=False)
            elif inv["op"] == "add_tag":
                await deps.adapter.apply_tag(inv["uuid"], inv["tag"], dry_run=False)
            elif inv["op"] == "move":
                await deps.adapter.move_record(
                    inv["uuid"], inv["destination"], dry_run=False
                )
            reverted_count += 1
        except Exception as e:
            failures.append(
                {"uuid": inv["uuid"], "op": inv["op"], "error": str(e)[:200]}
            )

    log.info(
        "undo_bulk_apply_completed",
        audit_id=audit_id_str,
        reverted=reverted_count,
        failed=len(failures),
        skipped=len(skipped),
    )
    return {
        "audit_id": audit_id_str,
        "tool_name": "bulk_apply",
        "reverted": reverted_count > 0 and not failures,
        "reverted_count": reverted_count,
        "failures": failures,
        "skipped": skipped,
        "drift_detected": False,
        "dry_run": False,
        "message": (
            "ok"
            if not failures
            else f"{reverted_count} reverted, {len(failures)} failed"
        ),
    }
