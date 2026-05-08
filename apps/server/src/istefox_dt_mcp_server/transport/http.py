"""HTTP (streamable) transport runner.

Wraps `FastMCP.run_http_async()` with the project's logging defaults
and a deterministic mount path (`/mcp/`). Until phase 4 lands the OAuth
flow, this transport is **anonymous** — bind only to trusted hosts
(localhost or behind Cloudflare Tunnel with auth at the edge).

stdio remains the default in `cli.py serve`. HTTP is opt-in via
`--transport http` and is provisioned by `run_http()` below.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from fastmcp import FastMCP

log = structlog.get_logger(__name__)

# Default mount path for the MCP HTTP endpoints. Stable across versions.
DEFAULT_MCP_PATH = "/mcp/"


def run_http(
    server: FastMCP,
    *,
    host: str = "127.0.0.1",
    port: int = 3000,
    path: str = DEFAULT_MCP_PATH,
) -> None:
    """Run the MCP server over streamable HTTP.

    Args:
        server: A built FastMCP instance (with tools registered).
        host: Bind address. Defaults to loopback; do NOT expose without
            a reverse proxy or tunnel terminating TLS + auth at the edge.
        port: TCP port to listen on.
        path: Mount path for the MCP endpoints (defaults to `/mcp/`).

    Blocks until the server stops. Auth lands in phase 2+; today this
    is anonymous, so localhost-only deployments are the only safe
    configuration.
    """
    log.info(
        "http_transport_starting",
        host=host,
        port=port,
        path=path,
        auth="anonymous",
    )
    asyncio.run(
        server.run_http_async(
            host=host,
            port=port,
            path=path,
            transport="streamable-http",
            show_banner=False,
        )
    )
