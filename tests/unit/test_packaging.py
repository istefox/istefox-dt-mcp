"""Regression guard for issue #66.

The ``apps/server`` wheel must NOT use a ``force-include`` that maps a
file *into* the importable ``istefox_dt_mcp_server/`` package path.

Doing so makes the editable install materialize a
``site-packages/istefox_dt_mcp_server/`` directory with no
``__init__.py``. Under PEP 420 that is a namespace-package portion which
can shadow the editable ``.pth`` regular package, breaking
``from istefox_dt_mcp_server.cli import main`` (the console-script shim
used by ``claude mcp add ... -- uv ... run istefox-dt-mcp serve``).

``packages = ["src/istefox_dt_mcp_server"]`` already ships the locale
files in the wheel (verified by build), so the force-include is
redundant — its only effect is the shadow.
"""

from __future__ import annotations

import tomllib
from pathlib import Path


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "apps" / "server" / "pyproject.toml").is_file():
            return parent
    raise AssertionError("repo root containing apps/server/pyproject.toml not found")


def test_server_wheel_has_no_package_shadowing_force_include() -> None:
    cfg = tomllib.loads(
        (_repo_root() / "apps" / "server" / "pyproject.toml").read_text()
    )
    wheel = (
        cfg.get("tool", {})
        .get("hatch", {})
        .get("build", {})
        .get("targets", {})
        .get("wheel", {})
    )
    force_include = wheel.get("force-include", {})
    shadowing = [
        dest
        for dest in force_include.values()
        if str(dest).startswith("istefox_dt_mcp_server/")
    ]
    assert not shadowing, (
        f"force-include maps into the importable package ({shadowing}); "
        "this recreates the issue #66 editable namespace shadow. "
        "packages=['src/istefox_dt_mcp_server'] already ships package "
        "data — drop the force-include."
    )
