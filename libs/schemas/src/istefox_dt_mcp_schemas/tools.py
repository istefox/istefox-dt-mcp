"""Pydantic v2 input/output models for every MVP tool.

Each tool exposes a docstring on its Input model that becomes the
MCP tool description (≤ 2KB). The docstring follows the structure:
- One-line summary
- "When to use:" guidelines
- "Don't use for:" anti-patterns
- "Examples:" 1-2 invocation samples

These descriptions are in english because MCP clients (Claude) tend
to perform tool selection better in english. User-facing error
messages are localized to italian in the server's i18n layer.
"""

from __future__ import annotations

from datetime import date  # noqa: TC003 — needed by Pydantic at runtime
from typing import Literal

from pydantic import Field, field_validator

from .common import (
    Database,
    Envelope,
    RecordKind,
    RelatedResult,
    SearchResult,
    StrictModel,
)

# ----------------------------------------------------------------------
# list_databases
# ----------------------------------------------------------------------


class ListDatabasesInput(StrictModel):
    """Enumerate all currently-open DEVONthink databases.

    When to use:
    - First call when you don't know what databases the user has open.
    - Before any other tool that takes a `databases` filter.

    Don't use for:
    - Counting records inside a database (use `search` with empty query).
    - Inspecting closed databases (DEVONthink does not expose them).

    Examples:
    - {} -> list all open databases.
    """

    pass


class ListDatabasesOutput(Envelope[list[Database]]):
    pass


# ----------------------------------------------------------------------
# search
# ----------------------------------------------------------------------


class SearchInput(StrictModel):
    """Search records across one or more DEVONthink databases.

    Mode "bm25" uses DEVONthink's native full-text search (lexical).
    Mode "semantic" and "hybrid" require the RAG sidecar (post-W6).

    When to use:
    - The user asks "find documents about X" or quotes specific terms.
    - You need a list of candidate records before drilling into one.

    Don't use for:
    - Asking a natural-language question about content -> use `ask_database`.
    - Finding documents similar to a known one -> use `find_related`.

    Examples:
    - {"query": "vibrazioni HVAC", "max_results": 10}
    - {"query": "report 2026", "databases": ["Business"], "kinds": ["PDF"]}
    """

    query: str = Field(..., min_length=1, max_length=500)
    databases: list[str] | None = Field(
        default=None,
        description="Database names to restrict search to. None = all open.",
    )
    max_results: int = Field(default=10, ge=1, le=100)
    kinds: list[RecordKind] | None = Field(
        default=None,
        description="Filter by record kind (PDF, rtf, markdown, ...).",
    )
    date_after: date | None = None
    mode: str = Field(default="bm25", description="bm25 | semantic | hybrid")


class SearchOutput(Envelope[list[SearchResult]]):
    pass


# ----------------------------------------------------------------------
# find_related
# ----------------------------------------------------------------------


class FindRelatedInput(StrictModel):
    """Find records similar to a given one (DEVONthink See Also / Compare).

    When to use:
    - The user wants "more like this".
    - Building topic clusters around a seed document.

    Don't use for:
    - Free-text search -> use `search`.
    - Finding documents matching a question -> use `ask_database`.

    Examples:
    - {"uuid": "ABCD-1234-...", "k": 10}
    """

    uuid: str = Field(..., description="UUID of the seed record")
    k: int = Field(default=10, ge=1, le=50)


class FindRelatedOutput(Envelope[list[RelatedResult]]):
    pass


# ----------------------------------------------------------------------
# ask_database
# ----------------------------------------------------------------------


class Citation(StrictModel):
    uuid: str
    name: str
    snippet: str
    reference_url: str


class AskDatabaseInput(StrictModel):
    """Ask a natural-language question, get an answer with citations.

    Retrieval over the user's DEVONthink databases. By default uses
    BM25-only (zero setup, no embedding model download). Vector
    retrieval is opt-in experimental in 0.1.0 (set
    `ISTEFOX_RAG_ENABLED=1` and run `istefox-dt-mcp reindex <db>` to
    populate the local vector index). See ADR-008 for the embedding
    model selection roadmap.

    When to use:
    - The user asks an open question whose answer is in their archive.
    - You need a synthesized answer, not just a list of documents.

    Don't use for:
    - Listing candidate documents -> use `search`.
    - Bulk operations -> use the dedicated write tools.

    Examples:
    - {"question": "Quali isolatori abbiamo proposto a Keraglass?"}
    """

    question: str = Field(..., min_length=3, max_length=2000)
    databases: list[str] | None = None
    max_chunks: int = Field(default=8, ge=1, le=20)
    include_citations: bool = True


class AskDatabaseAnswer(StrictModel):
    answer: str
    citations: list[Citation]


class AskDatabaseOutput(Envelope[AskDatabaseAnswer]):
    pass


# ----------------------------------------------------------------------
# file_document (W7 — write tool with dry_run)
# ----------------------------------------------------------------------


class FileDocumentPreview(StrictModel):
    destination_group: str | None = None
    tags_to_add: list[str] = Field(default_factory=list)
    tags_to_remove: list[str] = Field(default_factory=list)
    rename_to: str | None = None


class FileDocumentInput(StrictModel):
    """Auto-classify, place and tag a record. Dry-run by default.

    When to use:
    - Inbox triage: a new record needs to be filed.
    - The user trusts DEVONthink's AI classifier and wants it applied.

    Don't use for:
    - Bulk reorganization across many records -> use `bulk_apply`.
    - Manual override of destination -> set `destination_hint`.

    Path format for `destination_hint`:
    - The first segment of the path MUST be the name of an open
      DEVONthink database. Example: `/Inbox/MyGroup`, NOT `/MyGroup`.
    - Use `list_databases` first to discover open database names.
    - Missing groups along the path are auto-created.

    Safety:
    - `dry_run` defaults to true. Always preview before applying.
    - Audit log records before-state for selective undo.
    - To apply, run twice: first with dry_run=true to get a
      preview_token in the audit_id, then with dry_run=false +
      confirm_token=<the audit_id> to commit.

    Examples:
    - {"record_uuid": "ABCD-...", "dry_run": true}
    - {"record_uuid": "ABCD-...", "dry_run": false, "confirm_token": "..."}
    - {"record_uuid": "ABCD-...", "dry_run": true, "destination_hint": "/Inbox/Triage"}
    """

    record_uuid: str
    dry_run: bool = True
    auto_classify: bool = True
    auto_tag: bool = True
    destination_hint: str | None = Field(
        default=None,
        description=(
            "Optional destination group path. **Format: "
            "`/<database>/<group>/<subgroup>...`** — the FIRST path "
            "segment MUST be the name of an open DEVONthink database "
            "(call `list_databases` to enumerate). Examples: "
            "`/Inbox/Triage`, `/privato/Fatture/2026`. Passing just "
            "`/Triage` will fail with DATABASE_NOT_FOUND because "
            "`Triage` is interpreted as a database name. If the "
            "leading group doesn't exist it's auto-created via "
            "DT.createLocation."
        ),
    )
    confirm_token: str | None = Field(
        default=None,
        description=(
            "audit_id of the previous dry_run preview. Required when "
            "dry_run=false and the server enforces preview-then-apply."
        ),
    )


class FileDocumentResult(StrictModel):
    record_uuid: str
    preview: FileDocumentPreview
    would_apply: bool
    applied: bool = False
    preview_token: str | None = Field(
        default=None,
        description="audit_id of this dry_run; pass back as confirm_token to apply",
    )


class FileDocumentOutput(Envelope[FileDocumentResult]):
    pass


# ----------------------------------------------------------------------
# bulk_apply (v0.0.8 — batch many small ops with preview-then-apply)
# ----------------------------------------------------------------------


class BulkApplyOperation(StrictModel):
    """One operation inside a bulk apply batch.

    Supported `op` values:
    - `add_tag` — payload: `{"tag": "<name>"}`
    - `remove_tag` — payload: `{"tag": "<name>"}`
    - `move` — payload: `{"destination": "/<database>/<group>/..."}`
      The first path segment MUST be the name of an open DEVONthink
      database. Use `list_databases` to discover names. Example:
      `/Inbox/Triage` (correct), `/Triage` (DATABASE_NOT_FOUND).
    """

    record_uuid: str
    op: str = Field(..., description="add_tag | remove_tag | move")
    payload: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Op-specific args. add_tag/remove_tag: {'tag': 'x'}. "
            "move: {'destination': '/<database>/<group>/...'} — first "
            "segment MUST be an open database name."
        ),
    )


class BulkApplyInput(StrictModel):
    """Apply many small ops in one call. Dry-run by default.

    Same preview-then-apply contract as `file_document`: call once
    with `dry_run=true` to inspect the planned operations and receive
    a `preview_token` (audit_id), then call again with `dry_run=false`
    + `confirm_token=<previous preview_token>` to commit.

    Failure semantics: DEVONthink has no transactions, so we cannot
    automatically roll back already-applied ops. Default is
    `stop_on_first_error=true` — the batch halts at the first failure
    and `failed_index` reports the offending op. The audit log records
    the partial state; the user can selectively undo applied ops by
    audit_id.

    Limits: max 500 ops per call.

    When to use:
    - Tag many records with the same tag.
    - Move a curated set of records to a single destination group.
    - Combine a few tag/move ops on the same set of records.

    Don't use for:
    - Single-record tagging/move — use `apply_tag`/`move_record` flows
      via `file_document` for richer audit (before_state).
    - Auto-classification — use `file_document` (calls DT classifier).
    """

    operations: list[BulkApplyOperation] = Field(..., min_length=1, max_length=500)
    dry_run: bool = True
    confirm_token: str | None = None
    stop_on_first_error: bool = True


class BulkOpOutcome(StrictModel):
    """Result of a single op inside a bulk_apply batch."""

    index: int
    record_uuid: str
    op: str
    status: str = Field(..., description="planned | applied | skipped | failed")
    error_code: str | None = None
    error_message: str | None = None


class BulkApplyResult(StrictModel):
    operations_total: int
    operations_applied: int
    failed_index: int | None = None
    preview_token: str | None = None
    outcomes: list[BulkOpOutcome] = Field(default_factory=list)


class BulkApplyOutput(Envelope[BulkApplyResult]):
    pass


# ----------------------------------------------------------------------
# undo (W7+ — selective undo of a previously applied write op)
# ----------------------------------------------------------------------


class UndoInput(StrictModel):
    """Undo a previously applied write op given its audit_id.

    The audit log must contain a `before_state` for the target entry
    (set automatically by write tools that opt-in to undo support).
    Read ops cannot be undone.

    Safety:
    - `dry_run` defaults to true.
    - Undo is idempotent only if the target record hasn't been
      modified by other ops since the original write.

    NOTE: schema only in v1. Implementation post-W7.
    """

    audit_id: str
    dry_run: bool = True
    confirm_token: str | None = None


class UndoResult(StrictModel):
    audit_id: str
    target_record_uuid: str
    reverted: bool
    preview_token: str | None = None
    drift_detected: bool = Field(
        default=False,
        description=(
            "True if the record state changed since the original write — "
            "undo may not restore the exact prior state."
        ),
    )


class UndoOutput(Envelope[UndoResult]):
    pass


# ----------------------------------------------------------------------
# summarize_topic (0.2.0 — read tool with server-side clustering)
# ----------------------------------------------------------------------


def _default_cluster_by() -> list[Literal["date", "tags", "kind", "location"]]:
    return ["date", "tags"]


class SummarizeTopicInput(StrictModel):
    """Retrieve records related to a topic and group them by dimension.

    Default dimensions are date and tags. The retrieval layer mirrors
    ``ask_database``: vector if RAG is enabled, BM25 fallback otherwise.

    When to use:
    - The user wants a panorama / overview of a topic across many records.
    - You need data already grouped by category (date, tag, kind, location)
      so you can narrate the structure without doing the grouping yourself.

    Don't use for:
    - Direct questions with a single answer -> use ``ask_database``.
    - Listing candidate documents to drill into -> use ``search``.

    Examples:
    - {"topic": "bollette 2025", "cluster_by": ["date", "tags"]}
    - {"topic": "Keraglass", "cluster_by": ["kind", "location"]}
    """

    topic: str = Field(..., min_length=3, max_length=2000)
    databases: list[str] | None = None
    cluster_by: list[Literal["date", "tags", "kind", "location"]] = Field(
        default_factory=_default_cluster_by,
        min_length=1,
        max_length=4,
    )
    max_records: int = Field(default=50, ge=1, le=200)
    max_per_cluster: int = Field(default=10, ge=1, le=50)
    max_clusters: int = Field(default=10, ge=1, le=50)

    @field_validator("cluster_by")
    @classmethod
    def _dedupe_cluster_by(
        cls, v: list[Literal["date", "tags", "kind", "location"]]
    ) -> list[Literal["date", "tags", "kind", "location"]]:
        # Preserve first-occurrence order; drop duplicates.
        seen: set[str] = set()
        deduped: list[Literal["date", "tags", "kind", "location"]] = []
        for item in v:
            if item not in seen:
                seen.add(item)
                deduped.append(item)
        return deduped


class Cluster(StrictModel):
    """One group of records along a single clustering dimension."""

    dimension: Literal["date", "tags", "kind", "location"]
    label: str
    count: int
    records: list[Citation]


class SummarizeTopicResult(StrictModel):
    """Topic panorama: clusters across requested dimensions."""

    topic: str
    clusters: list[Cluster]
    total_records_retrieved: int
    retrieval_mode: Literal["vector", "bm25"]


class SummarizeTopicOutput(Envelope[SummarizeTopicResult]):
    pass
