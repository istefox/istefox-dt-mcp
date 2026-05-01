"""End-to-end of the tool wrapper (`safe_call`) with mocked adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from istefox_dt_mcp_adapter.errors import DTNotRunningError, RecordNotFoundError
from istefox_dt_mcp_schemas.common import Database, RelatedResult, SearchResult
from istefox_dt_mcp_schemas.tools import (
    FindRelatedInput,
    FindRelatedOutput,
    ListDatabasesInput,
    ListDatabasesOutput,
    SearchInput,
    SearchOutput,
)
from istefox_dt_mcp_server.tools._common import safe_call

if TYPE_CHECKING:
    from unittest.mock import AsyncMock

    from istefox_dt_mcp_server.deps import Deps


@pytest.mark.asyncio
async def test_list_databases_success(deps: Deps, mock_adapter: AsyncMock) -> None:
    mock_adapter.list_databases.return_value = [
        Database(uuid="u1", name="Business", path="/p", is_open=True)
    ]
    result: ListDatabasesOutput = await safe_call(
        tool_name="list_databases",
        input_data=ListDatabasesInput().model_dump(),
        deps=deps,
        operation=mock_adapter.list_databases,
        output_factory=ListDatabasesOutput,
    )
    assert result.success is True
    assert result.audit_id is not None
    assert len(result.data) == 1


@pytest.mark.asyncio
async def test_search_dt_not_running_returns_failure(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    mock_adapter.search.side_effect = DTNotRunningError()

    async def op():
        return await mock_adapter.search("x")

    result: SearchOutput = await safe_call(
        tool_name="search",
        input_data=SearchInput(query="x").model_dump(mode="json"),
        deps=deps,
        operation=op,
        output_factory=SearchOutput,
    )
    assert result.success is False
    assert result.error_code == "DT_NOT_RUNNING"
    assert "DEVONthink" in result.error_message
    assert "Avvia" in result.recovery_hint
    assert result.audit_id is not None


@pytest.mark.asyncio
async def test_find_related_record_not_found(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    mock_adapter.find_related.side_effect = RecordNotFoundError("ABC")

    async def op():
        return await mock_adapter.find_related("ABC", k=10)

    result: FindRelatedOutput = await safe_call(
        tool_name="find_related",
        input_data=FindRelatedInput(uuid="ABC").model_dump(),
        deps=deps,
        operation=op,
        output_factory=FindRelatedOutput,
    )
    assert result.success is False
    assert result.error_code == "RECORD_NOT_FOUND"


@pytest.mark.asyncio
async def test_audit_log_persists_on_success(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    mock_adapter.search.return_value = [
        SearchResult(uuid="u", name="n", location="/", reference_url="x-d://1")
    ]

    async def op():
        return await mock_adapter.search("x")

    out = await safe_call(
        tool_name="search",
        input_data={"query": "x"},
        deps=deps,
        operation=op,
        output_factory=SearchOutput,
    )
    entry = deps.audit.get(out.audit_id)
    assert entry is not None
    assert entry.tool_name == "search"
    assert entry.error_code is None


@pytest.mark.asyncio
async def test_audit_log_persists_on_failure(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    mock_adapter.find_related.side_effect = RecordNotFoundError("X")

    async def op():
        return await mock_adapter.find_related("X")

    out = await safe_call(
        tool_name="find_related",
        input_data={"uuid": "X"},
        deps=deps,
        operation=op,
        output_factory=FindRelatedOutput,
    )
    entry = deps.audit.get(out.audit_id)
    assert entry is not None
    assert entry.error_code == "RECORD_NOT_FOUND"


@pytest.mark.asyncio
async def test_envelope_for_related_results(
    deps: Deps, mock_adapter: AsyncMock
) -> None:
    mock_adapter.find_related.return_value = [
        RelatedResult(uuid="u", name="n", location="/", reference_url="x-d://1")
    ]

    async def op():
        return await mock_adapter.find_related("X")

    out: FindRelatedOutput = await safe_call(
        tool_name="find_related",
        input_data={"uuid": "X"},
        deps=deps,
        operation=op,
        output_factory=FindRelatedOutput,
    )
    assert out.success is True
    assert len(out.data) == 1
    assert out.data[0].uuid == "u"
