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
from typing import Any

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
