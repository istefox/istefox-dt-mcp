"""Entry point invoked by Claude Desktop when launching the .mcpb bundle.

The MCPB host runs this file via `uv run python bundle_main.py`. We
import the Click CLI from the bundled server package and default to
the `serve` sub-command (the only mode the desktop host needs).

Keep this file dependency-free at module load time; everything heavy
is lazy-imported through the CLI.
"""

from __future__ import annotations

import sys


def main() -> None:
    from istefox_dt_mcp_server.cli import cli

    # When the host invokes us without any sub-command, default to
    # `serve`. Power users can still pass alternatives via env or by
    # editing the launch command.
    if len(sys.argv) == 1:
        sys.argv.append("serve")
    cli(obj={})


if __name__ == "__main__":
    main()
