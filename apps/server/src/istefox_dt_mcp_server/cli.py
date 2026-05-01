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


@cli.command()
@click.argument("database")
def reconcile(database: str) -> None:
    """Reconcile vector store against a DEVONthink database.

    Computes the set-diff DT vs RAG: indexes new records, removes
    orphans. Idempotent — safe to run on a cron. Requires
    ISTEFOX_RAG_ENABLED=1.
    """
    from .reindex import reconcile_database

    deps = build_default_deps()

    async def run() -> dict[str, int]:
        return await reconcile_database(deps, database)

    counters = asyncio.run(run())
    click.echo(json.dumps(counters, indent=2))


@cli.command()
@click.argument("audit_id")
@click.option(
    "--apply",
    "apply_changes",
    is_flag=True,
    default=False,
    help="Actually apply the undo (default is dry-run preview).",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Bypass drift detection — overwrite intervening edits.",
)
def undo(audit_id: str, apply_changes: bool, force: bool) -> None:
    """Revert a previously applied write tool by audit_id.

    Looks up the audit log entry, reads its before_state snapshot,
    and reverses the write (move back + remove added tags).
    Currently only `file_document` audits are supported.
    """
    from .undo import undo_audit

    deps = build_default_deps()

    async def run() -> dict[str, object]:
        return await undo_audit(deps, audit_id, dry_run=not apply_changes, force=force)

    result = asyncio.run(run())
    click.echo(json.dumps(result, indent=2, default=str))
    if not result.get("reverted") and apply_changes:
        sys.exit(2)


@cli.command()
@click.option(
    "--port",
    type=int,
    default=27205,
    show_default=True,
    help="Webhook port (loopback only).",
)
@click.option(
    "--databases",
    "databases",
    multiple=True,
    help="Databases to reconcile periodically (repeat for many).",
)
@click.option(
    "--reconcile-interval-s",
    type=int,
    default=21600,  # 6h
    show_default=True,
    help="Seconds between reconciliation passes (0 = disabled).",
)
def watch(port: int, databases: tuple[str, ...], reconcile_interval_s: int) -> None:
    """Run the sync daemon: webhook listener + periodic reconciliation.

    Pair with a DEVONthink 4 smart rule that POSTs to
    http://127.0.0.1:<port>/sync-event on record create/modify/delete.
    See `docs/smart-rules/sync_rag.md` for the AppleScript template.

    Optional Bearer token: set ISTEFOX_WEBHOOK_TOKEN before launch.
    Requires ISTEFOX_RAG_ENABLED=1.
    """
    from .reindex import reconcile_database
    from .sync_handler import process_sync_event
    from .webhook import WebhookListener, consume_events

    deps = build_default_deps()

    listener = WebhookListener(port=port)
    listener.start()

    async def run() -> None:
        stop_event = asyncio.Event()

        async def reconcile_loop() -> None:
            if reconcile_interval_s <= 0 or not databases:
                return
            while not stop_event.is_set():
                for db in databases:
                    try:
                        c = await reconcile_database(deps, db)
                        click.echo(
                            f"[reconcile {db}] {json.dumps(c)}",
                            err=True,
                        )
                    except Exception as e:
                        click.echo(f"[reconcile {db}] ERROR: {e}", err=True)
                try:
                    await asyncio.wait_for(
                        stop_event.wait(), timeout=reconcile_interval_s
                    )
                except TimeoutError:
                    continue

        async def event_handler(event: dict[str, Any]) -> None:
            await process_sync_event(deps, event)

        consumer = asyncio.create_task(
            consume_events(listener, event_handler, stop_event=stop_event)
        )
        cron = asyncio.create_task(reconcile_loop())

        try:
            await asyncio.Event().wait()  # block forever, KeyboardInterrupt to stop
        except (KeyboardInterrupt, asyncio.CancelledError):
            stop_event.set()
            await asyncio.gather(consumer, cron, return_exceptions=True)

    try:
        asyncio.run(run())
    finally:
        listener.stop()


def main() -> None:
    cli(obj={})


if __name__ == "__main__":
    main()
