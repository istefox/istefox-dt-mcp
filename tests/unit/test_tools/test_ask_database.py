"""ask_database retrieval-only — server-side tool."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from istefox_dt_mcp_schemas.common import SearchResult
from istefox_dt_mcp_schemas.tools import (
    AskDatabaseInput,
    AskDatabaseOutput,
)
from istefox_dt_mcp_server.tools._common import safe_call
from istefox_dt_mcp_server.tools.ask_database import (
    RETRIEVAL_PLACEHOLDER_ANSWER,
    SNIPPET_CHARS,
)

if TYPE_CHECKING:
    from unittest.mock import AsyncMock

    from istefox_dt_mcp_server.deps import Deps


@pytest.mark.asyncio
async def test_ask_database_retrieval_returns_citations(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    mock_adapter.search.return_value = [
        SearchResult(
            uuid="u1", name="doc1", location="/A", reference_url="x-d://1"
        ),
        SearchResult(
            uuid="u2", name="doc2", location="/B", reference_url="x-d://2"
        ),
    ]
    mock_adapter.get_record_text.side_effect = ["text 1", "text 2"]

    async def op():
        from istefox_dt_mcp_schemas.tools import AskDatabaseAnswer, Citation

        hits = await mock_adapter.search("question?", max_results=8)
        cites = [
            Citation(
                uuid=h.uuid,
                name=h.name,
                snippet=await mock_adapter.get_record_text(
                    h.uuid, max_chars=SNIPPET_CHARS
                ),
                reference_url=h.reference_url,
            )
            for h in hits
        ]
        return AskDatabaseAnswer(
            answer=RETRIEVAL_PLACEHOLDER_ANSWER, citations=cites
        )

    out: AskDatabaseOutput = await safe_call(
        tool_name="ask_database",
        input_data=AskDatabaseInput(question="ciao?").model_dump(),
        deps=deps,
        operation=op,
        output_factory=AskDatabaseOutput,
    )

    assert out.success is True
    assert out.data is not None
    assert len(out.data.citations) == 2
    assert out.data.citations[0].snippet == "text 1"
    assert out.data.citations[1].snippet == "text 2"
    assert out.data.answer == RETRIEVAL_PLACEHOLDER_ANSWER


@pytest.mark.asyncio
async def test_ask_database_skip_citations_flag(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    mock_adapter.search.return_value = [
        SearchResult(uuid="u", name="n", location="/", reference_url="x-d://1")
    ]

    async def op():
        from istefox_dt_mcp_schemas.tools import AskDatabaseAnswer

        # include_citations=False: skip get_record_text calls
        await mock_adapter.search("question", max_results=8)
        return AskDatabaseAnswer(
            answer=RETRIEVAL_PLACEHOLDER_ANSWER, citations=[]
        )

    out: AskDatabaseOutput = await safe_call(
        tool_name="ask_database",
        input_data=AskDatabaseInput(
            question="question", include_citations=False
        ).model_dump(),
        deps=deps,
        operation=op,
        output_factory=AskDatabaseOutput,
    )
    assert out.success is True
    assert out.data is not None
    assert out.data.citations == []
    mock_adapter.get_record_text.assert_not_called()


@pytest.mark.asyncio
async def test_ask_database_empty_search(deps: Deps, mock_adapter: AsyncMock) -> None:
    mock_adapter.search.return_value = []

    async def op():
        from istefox_dt_mcp_schemas.tools import AskDatabaseAnswer

        await mock_adapter.search("question", max_results=8)
        return AskDatabaseAnswer(
            answer=RETRIEVAL_PLACEHOLDER_ANSWER, citations=[]
        )

    out = await safe_call(
        tool_name="ask_database",
        input_data=AskDatabaseInput(question="question").model_dump(),
        deps=deps,
        operation=op,
        output_factory=AskDatabaseOutput,
    )
    assert out.success is True
    assert out.data.citations == []
