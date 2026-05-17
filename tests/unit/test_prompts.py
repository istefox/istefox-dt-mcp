"""MCP prompt tests (0.5.0)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastmcp import FastMCP
from istefox_dt_mcp_server.prompts.dt_prompts import (
    register,
    triage_inbox_text,
    weekly_review_text,
)

if TYPE_CHECKING:
    from istefox_dt_mcp_server.deps import Deps


def test_weekly_review_default_italian() -> None:
    t = weekly_review_text(None, "it")
    assert "review settimanale" in t
    assert "list_databases" in t
    assert "sola lettura" in t


def test_weekly_review_scopes_databases() -> None:
    t = weekly_review_text("Alpha,Beta", "it")
    assert "Alpha,Beta" in t


def test_weekly_review_english() -> None:
    t = weekly_review_text(None, "en")
    assert "weekly review" in t.lower()
    assert "read-only" in t.lower()


def test_triage_inbox_dry_run_only_by_default() -> None:
    t = triage_inbox_text("Inbox", "it", apply=False)
    assert "dry_run=true" in t
    assert "NON applicare" in t
    assert "dry_run=false" not in t


def test_triage_inbox_apply_explains_confirm_token() -> None:
    t = triage_inbox_text("Inbox", "it", apply=True)
    assert "dry_run=false" in t
    assert "confirm_token" in t


@pytest.mark.asyncio
async def test_prompts_registered(deps: Deps) -> None:
    mcp: FastMCP = FastMCP(name="test")
    register(mcp, deps)
    assert await mcp.get_prompt("weekly_review") is not None
    assert await mcp.get_prompt("triage_inbox") is not None
