"""ask_database tool — BM25 retrieval-only Q&A (vector RAG comes in W5-6).

In v1 this tool does NOT generate an answer server-side. It runs a
BM25 search on the question, fetches plain-text snippets from the
top-N hits, and returns them as citations. The MCP client (Claude)
uses the citations as grounded context to compose the answer.

This keeps the server LLM-agnostic and privacy-first (no question or
content ever leaves the user's machine through this tool). When the
RAG sidecar lands in W5-6, this tool gains semantic retrieval and an
optional generated `answer` field powered by DT4 native AI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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


SNIPPET_CHARS = 500
RETRIEVAL_PLACEHOLDER_ANSWER = (
    "Risposta non generata lato server (modalità retrieval-only v1). "
    "Usa le citazioni fornite come contesto per comporre la risposta."
)


def register(mcp: FastMCP, deps: Deps) -> None:
    @mcp.tool()
    async def ask_database(input: AskDatabaseInput) -> AskDatabaseOutput:  # noqa: A002
        async def op() -> AskDatabaseAnswer:
            hits = await deps.adapter.search(
                input.question,
                databases=input.databases,
                max_results=input.max_chunks,
            )
            citations: list[Citation] = []
            if input.include_citations:
                for hit in hits:
                    snippet = await deps.adapter.get_record_text(
                        hit.uuid, max_chars=SNIPPET_CHARS
                    )
                    citations.append(
                        Citation(
                            uuid=hit.uuid,
                            name=hit.name,
                            snippet=snippet,
                            reference_url=hit.reference_url,
                        )
                    )
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
