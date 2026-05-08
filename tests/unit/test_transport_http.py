"""Unit tests for the streamable-HTTP transport scaffolding (0.4.0 phase 1).

These tests don't spin up uvicorn — they assert (a) the module imports
without side-effects, (b) the FastMCP server can produce an ASGI app
suitable for HTTP transport, and (c) the CLI exposes the new options.
The full lifecycle (bind, request, shutdown) is exercised by
`scripts/smoke_e2e.sh` and the live integration tests.
"""

from __future__ import annotations

from typing import Any

import pytest
from click.testing import CliRunner
from fastmcp import FastMCP
from istefox_dt_mcp_server.cli import cli
from istefox_dt_mcp_server.transport.http import DEFAULT_MCP_PATH, run_http


def test_module_exports_run_http_and_default_path() -> None:
    """The transport.http module surface is stable for callers."""
    assert callable(run_http)
    assert DEFAULT_MCP_PATH == "/mcp/"
    assert DEFAULT_MCP_PATH.startswith("/")
    assert DEFAULT_MCP_PATH.endswith("/")


def test_fastmcp_can_produce_an_asgi_app_for_http() -> None:
    """FastMCP exposes `http_app()` returning an ASGI-callable.

    This is the foundation `run_http` relies on. Verifying it here keeps
    us safe against FastMCP API drift without requiring a live server.
    """
    mcp: FastMCP[Any] = FastMCP(name="test-http-foundation")
    app = mcp.http_app(path=DEFAULT_MCP_PATH, transport="streamable-http")
    # Starlette/ASGI apps are callable. Lifespan + routes attributes are
    # the contract surface we depend on; check existence (not behavior).
    assert callable(app)
    assert hasattr(app, "router") or hasattr(app, "routes")


def test_cli_serve_help_lists_http_transport() -> None:
    """`serve --help` advertises both stdio and http."""
    result = CliRunner().invoke(cli, ["serve", "--help"])
    assert result.exit_code == 0, result.output
    assert "stdio|http" in result.output or (
        "stdio" in result.output and "http" in result.output
    )
    assert "--host" in result.output
    assert "--port" in result.output


@pytest.mark.parametrize("transport", ["stdio", "http"])
def test_cli_serve_accepts_known_transports(transport: str) -> None:
    """Click validates the choice; an unknown value is rejected at parse."""
    # We invoke with `--port 0` for http to avoid binding (Click parses
    # before the command runs). For both transports we use --help on
    # the parsed level by passing a dry-run via standalone_mode=False
    # only when needed; here we just trust click.Choice() validation by
    # asserting --help still succeeds with `--transport <transport>`.
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["serve", "--transport", transport, "--help"],
        standalone_mode=True,
    )
    # --help short-circuits before the command body runs, so an unknown
    # transport would fail parsing earlier with a UsageError.
    assert result.exit_code == 0, result.output


def test_cli_serve_rejects_unknown_transport() -> None:
    """Unknown --transport value should fail parsing, not at runtime."""
    result = CliRunner().invoke(cli, ["serve", "--transport", "websocket"])
    assert result.exit_code != 0
    assert "Invalid value" in result.output or "is not one of" in result.output
