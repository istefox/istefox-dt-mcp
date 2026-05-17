"""Tier-3: dt:// resources against a real DEVONthink (0.5.0).

Skipped by default. Run: `uv run pytest -m integration
tests/integration/test_resources_live.py`. Reuses the autouse
`dt_running` guard and `live_deps` fixture from
tests/integration/conftest.py.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from istefox_dt_mcp_server.resources._common import RESOURCE_JSON_BUDGET_CHARS
from istefox_dt_mcp_server.resources.dt_resources import (
    build_databases_payload,
    build_record_metadata_payload,
    build_record_text_payload,
)

if TYPE_CHECKING:
    from istefox_dt_mcp_server.deps import Deps

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_resource_roundtrip_live(live_deps: Deps) -> None:
    dbs = await build_databases_payload(live_deps)
    assert isinstance(dbs["databases"], list)
    if not dbs["databases"]:
        pytest.skip("No open databases")

    db_name = dbs["databases"][0]["name"]
    hits = await live_deps.adapter.search("a", databases=[db_name], max_results=1)
    if not hits:
        pytest.skip(f"No records found in {db_name}")
    uuid = hits[0].uuid

    meta = await build_record_metadata_payload(live_deps, uuid)
    assert meta["record"]["uuid"] == uuid

    txt = await build_record_text_payload(live_deps, uuid)
    body = json.dumps(txt)
    assert len(body) <= RESOURCE_JSON_BUDGET_CHARS
    assert txt["returned_chars"] == len(txt["text"])
