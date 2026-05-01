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

from pydantic import Field

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
# ask_database (post-W4 — placeholder schema)
# ----------------------------------------------------------------------


class Citation(StrictModel):
    uuid: str
    name: str
    snippet: str
    reference_url: str


class AskDatabaseInput(StrictModel):
    """Ask a natural-language question, get an answer with citations.

    Uses retrieval-augmented generation (RAG) over the user's DEVONthink
    databases. In v1 BM25-only retrieval; vector retrieval added in W6.

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
# file_document (post-W6 — write tool with dry_run)
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
    - Bulk reorganization across many records -> use `bulk_apply` (post-MVP).
    - Manual override of destination -> set `destination_hint`.

    Safety:
    - `dry_run` defaults to true. Always preview before applying.
    - Audit log records before-state for selective undo.

    Examples:
    - {"record_uuid": "ABCD-...", "dry_run": true}
    """

    record_uuid: str
    dry_run: bool = True
    auto_classify: bool = True
    auto_tag: bool = True
    destination_hint: str | None = None


class FileDocumentResult(StrictModel):
    record_uuid: str
    preview: FileDocumentPreview
    would_apply: bool
    applied: bool = False


class FileDocumentOutput(Envelope[FileDocumentResult]):
    pass
