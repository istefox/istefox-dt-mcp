"""FastMCP server bootstrap.

Owns the FastMCP instance, wires deps, registers all tools.
Transport is selected by the caller (cli.py).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import FastMCP

from .auth.middleware import ScopeMiddleware
from .auth.routes import register_oauth_routes
from .deps import build_default_deps
from .prompts import dt_prompts as prompt_dt
from .resources import dt_resources as resource_dt
from .tools import ask_database as tool_ask_database
from .tools import bulk_apply as tool_bulk_apply
from .tools import file_document as tool_file_document
from .tools import find_related as tool_find_related
from .tools import list_databases as tool_list_databases
from .tools import search as tool_search
from .tools import summarize_topic as tool_summarize_topic

if TYPE_CHECKING:
    from .deps import Deps

SERVER_NAME = "istefox-dt-mcp"
SERVER_VERSION = "0.5.1"


SERVER_INSTRUCTIONS = """\
DEVONthink 4 connector. Outcome-oriented tools, not a 1:1 wrapping
of the AppleScript dictionary.

Use `list_databases` first if you don't know what's open. Use
`search` for keyword/topic queries returning candidate records. Use
`find_related` to expand from a known seed record. Tools return a
uniform envelope: {success, data, warnings, audit_id, error_*}.

In v1 the server runs on the same machine as DEVONthink (stdio).
Write tools (added in later milestones) default to dry_run=true and
preview their effect; the LLM must explicitly set dry_run=false to
apply.

Read-only `dt://` resources expose databases and individual records as
referenceable context (bounded, consent-gated). Prebuilt prompts
(`weekly_review`, `triage_inbox`) bundle common multi-tool workflows.
"""


def build_server(deps: Deps | None = None) -> FastMCP:
    """Construct and configure the FastMCP server."""
    deps = deps or build_default_deps()

    mcp = FastMCP(name=SERVER_NAME, instructions=SERVER_INSTRUCTIONS)

    # Scope middleware (0.4.0 phase 2+4): populates the per-request
    # scope context. stdio → ALL_SCOPES for "local-stdio"; HTTP →
    # validates Authorization: Bearer <jwt> via JWTIssuer (with the
    # X-Istefox-Scope header as a testing-only fallback).
    mcp.add_middleware(ScopeMiddleware(jwt_issuer=deps.jwt_issuer))

    tool_list_databases.register(mcp, deps)
    tool_search.register(mcp, deps)
    tool_find_related.register(mcp, deps)
    tool_ask_database.register(mcp, deps)
    tool_file_document.register(mcp, deps)
    tool_bulk_apply.register(mcp, deps)
    tool_summarize_topic.register(mcp, deps)
    resource_dt.register(mcp, deps)
    prompt_dt.register(mcp, deps)

    # OAuth routes (0.4.0 phase 4): /oauth/authorize, /oauth/consent,
    # /oauth/token. Live alongside the MCP routes on the same ASGI app
    # so the same uvicorn process serves both. No-ops on stdio.
    register_oauth_routes(mcp, deps)

    return mcp
