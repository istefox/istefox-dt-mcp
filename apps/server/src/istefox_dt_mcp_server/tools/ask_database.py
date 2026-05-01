"""ask_database tool — vector-first Q&A with BM25 fallback.

If the RAG provider is enabled (ChromaRAGProvider), retrieval uses
semantic similarity over the indexed corpus and citations come with
a relevance `score`. If RAG is disabled (NoopRAGProvider), the tool
falls back to BM25 retrieval — same shape, lower quality.

In both cases the server returns a placeholder `answer` and the
client (Claude) composes the actual response from the citations.
The optional generated `answer` via DT4 native AI is post-MVP.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from istefox_dt_mcp_adapter.rag import NoopRAGProvider
from istefox_dt_mcp_schemas.rag import RAGFilter
from istefox_dt_mcp_schemas.tools import (
    AskDatabaseAnswer,
    AskDatabaseInput,
    AskDatabaseOutput,
    Citation,
)

from ._common import safe_call

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from ..deps import Deps


log = structlog.get_logger(__name__)


SNIPPET_CHARS = 500
RETRIEVAL_PLACEHOLDER_ANSWER = (
    "Risposta non generata lato server (modalità retrieval-only v1). "
    "Usa le citazioni fornite come contesto per comporre la risposta."
)


def register(mcp: FastMCP, deps: Deps) -> None:
    @mcp.tool()
    async def ask_database(input: AskDatabaseInput) -> AskDatabaseOutput:  # noqa: A002
        rag_available = not isinstance(deps.rag, NoopRAGProvider)

        async def op() -> AskDatabaseAnswer:
            if rag_available:
                citations = await _vector_retrieve(deps, input)
                log.debug("ask_database_mode", mode="vector", n=len(citations))
            else:
                citations = await _bm25_retrieve(deps, input)
                log.debug("ask_database_mode", mode="bm25_fallback", n=len(citations))
            return AskDatabaseAnswer(
                answer=RETRIEVAL_PLACEHOLDER_ANSWER,
                citations=citations,
            )

        return await safe_call(
            tool_name="ask_database",
            input_data=input.model_dump(),
            deps=deps,
            operation=op,
            output_factory=AskDatabaseOutput,
        )


async def _vector_retrieve(
    deps: Deps,
    input: AskDatabaseInput,  # noqa: A002
) -> list[Citation]:
    rag_filter = RAGFilter(databases=input.databases)
    hits = await deps.rag.query(input.question, k=input.max_chunks, filters=rag_filter)
    if not input.include_citations:
        return []

    citations: list[Citation] = []
    for hit in hits:
        # Prefer the snippet ChromaDB already returned; fetch a longer
        # one from DT only when missing.
        snippet = hit.snippet
        if not snippet:
            try:
                snippet = await deps.adapter.get_record_text(
                    hit.uuid, max_chars=SNIPPET_CHARS
                )
            except Exception as e:
                log.debug("ask_database_snippet_failed", uuid=hit.uuid, error=str(e))
                snippet = ""

        name = str(hit.metadata.get("name", "")) or hit.uuid
        try:
            rec = await deps.adapter.get_record(hit.uuid)
            name = rec.name
            reference_url = rec.reference_url
        except Exception as e:
            log.debug("ask_database_meta_failed", uuid=hit.uuid, error=str(e))
            reference_url = f"x-devonthink-item://{hit.uuid}"

        citations.append(
            Citation(
                uuid=hit.uuid,
                name=name,
                snippet=snippet,
                reference_url=reference_url,
            )
        )
    return citations


async def _bm25_retrieve(
    deps: Deps,
    input: AskDatabaseInput,  # noqa: A002
) -> list[Citation]:
    hits = await deps.adapter.search(
        input.question,
        databases=input.databases,
        max_results=input.max_chunks,
    )
    if not input.include_citations:
        return []

    citations: list[Citation] = []
    for hit in hits:
        try:
            snippet = await deps.adapter.get_record_text(
                hit.uuid, max_chars=SNIPPET_CHARS
            )
        except Exception as e:
            log.debug("ask_database_snippet_failed", uuid=hit.uuid, error=str(e))
            snippet = ""
        citations.append(
            Citation(
                uuid=hit.uuid,
                name=hit.name,
                snippet=snippet,
                reference_url=hit.reference_url,
            )
        )
    return citations
