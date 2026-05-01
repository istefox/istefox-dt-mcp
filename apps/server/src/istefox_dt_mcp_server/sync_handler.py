"""Apply a single sync event from the webhook to the RAG provider."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from .deps import Deps


log = structlog.get_logger(__name__)

SNIPPET_CHARS = 4000


async def process_sync_event(deps: Deps, event: dict[str, Any]) -> None:
    """Index, re-index, or remove based on the smart-rule action."""
    action = event.get("action")
    uuid = event.get("uuid")
    database = event.get("database") or ""
    if not uuid:
        return

    if action == "deleted":
        await deps.rag.remove(uuid)
        log.info("sync_event_removed", uuid=uuid)
        return

    if action in {"created", "modified"}:
        try:
            text = await deps.adapter.get_record_text(uuid, max_chars=SNIPPET_CHARS)
        except Exception as e:
            log.warning("sync_event_fetch_failed", uuid=uuid, error=str(e))
            return
        if not text.strip():
            log.debug("sync_event_empty_text", uuid=uuid)
            return
        try:
            rec = await deps.adapter.get_record(uuid)
            metadata = {
                "database": database,
                "kind": str(rec.kind),
                "name": rec.name,
                "location": rec.location,
            }
        except Exception as e:
            log.debug("sync_event_meta_fallback", uuid=uuid, error=str(e))
            metadata = {"database": database}
        await deps.rag.index(uuid, text, metadata)
        log.info("sync_event_indexed", action=action, uuid=uuid)
        return

    log.debug("sync_event_unknown_action", action=action, uuid=uuid)
