"""Command-line entrypoint.

`istefox-dt-mcp serve` starts the MCP server (stdio in v1).
`istefox-dt-mcp doctor` runs a health check and prints diagnostics.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import click

from .deps import build_default_deps
from .logging import configure_logging
from .server import SERVER_NAME, SERVER_VERSION, build_server


@click.group()
@click.version_option(SERVER_VERSION, prog_name=SERVER_NAME)
@click.option(
    "--log-level",
    default="info",
    type=click.Choice(["debug", "info", "warning", "error"]),
    show_default=True,
)
@click.pass_context
def cli(ctx: click.Context, log_level: str) -> None:
    configure_logging(level=log_level)
    ctx.ensure_object(dict)


@cli.command()
@click.option(
    "--transport",
    default="stdio",
    type=click.Choice(["stdio"]),
    show_default=True,
    help="Transport mode. HTTP transport ships in v2.",
)
def serve(transport: str) -> None:
    """Start the MCP server."""
    server = build_server()
    if transport == "stdio":
        server.run()
    else:  # pragma: no cover — only stdio in v1
        raise click.UsageError(f"transport {transport} not supported in v1")


@cli.command()
def doctor() -> None:
    """Run a health check and print diagnostics."""
    deps = build_default_deps()

    async def run() -> dict[str, Any]:
        health = await deps.adapter.health_check()
        rag_stats = await deps.rag.stats()
        out = health.model_dump()
        out["rag"] = rag_stats.model_dump()
        return out

    result = asyncio.run(run())
    click.echo(json.dumps(result, indent=2, default=str))
    sys.exit(0 if result.get("dt_running") else 1)


@cli.command()
@click.argument("database")
@click.option(
    "--limit",
    type=int,
    default=None,
    help="Cap the number of records (None = all). Useful for incremental tests.",
)
@click.option(
    "--batch-size",
    type=int,
    default=64,
    show_default=True,
    help="How many records per embedding batch.",
)
def reindex(database: str, limit: int | None, batch_size: int) -> None:
    """Index a DEVONthink database into the RAG provider (manual one-shot).

    Requires ISTEFOX_RAG_ENABLED=1. Smart-rule-driven incremental sync
    will land in W6.
    """
    from .reindex import reindex_database

    deps = build_default_deps()

    async def run() -> dict[str, int]:
        return await reindex_database(
            deps, database, limit=limit, batch_size=batch_size
        )

    counters = asyncio.run(run())
    click.echo(json.dumps(counters, indent=2))


def main() -> None:
    cli(obj={})


if __name__ == "__main__":
    main()
