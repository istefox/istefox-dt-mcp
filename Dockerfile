# syntax=docker/dockerfile:1.7
#
# Container image for Glama / awesome-mcp-servers introspection.
#
# DEVONthink 4 is macOS-only, so this image cannot exercise tool calls
# (every tool call routes through a JXA bridge that requires DT running
# on macOS). It is built ONLY so that MCP catalog services can perform
# protocol introspection (initialize, tools/list, resources/list) — the
# server boots cleanly without DT and answers introspection requests
# correctly. Real usage requires the .mcpb bundle in Claude Desktop or
# `uv run istefox-dt-mcp serve` on a Mac with DEVONthink 4.

FROM python:3.12-slim AS base

# Astral's uv package manager (multi-stage copy, no installer script).
COPY --from=ghcr.io/astral-sh/uv:0.4 /uv /uvx /usr/local/bin/

# build-essential is a safety net in case any transitive dep lacks a
# prebuilt wheel for linux/amd64; chromadb and sentence-transformers
# normally do, but pinning that assumption is fragile.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY apps apps
COPY libs libs
COPY README.md LICENSE ./

RUN uv sync --all-packages --frozen --no-dev

ENV PYTHONUNBUFFERED=1
ENV ISTEFOX_RAG_ENABLED=0

ENTRYPOINT ["uv", "run", "--no-sync", "istefox-dt-mcp"]
CMD ["serve"]
