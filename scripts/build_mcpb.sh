#!/usr/bin/env bash
# Build a .mcpb desktop extension bundle from the workspace.
#
# Output: dist/istefox-dt-mcp-<version>.mcpb
#
# The bundle uses server.type=uv: the host (Claude Desktop) runs
# `uv sync` over the bundled pyproject.toml on first launch, then
# invokes `uv run python bundle_main.py serve`. We do NOT bundle a
# pre-built .venv — the host owns Python lifecycle.
#
# Excluded from the bundle: VCS metadata, virtual envs, caches,
# tests, docs, scripts, generated data (audit/vectors), CI config.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

# Pull the version from manifest.json without a JSON parser dep.
VERSION="$(grep -E '"version"[[:space:]]*:' manifest.json | head -1 | sed -E 's/.*"version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/')"
if [ -z "${VERSION}" ]; then
    echo "ERROR: could not read version from manifest.json" >&2
    exit 1
fi

DIST="${ROOT}/dist"
OUT="${DIST}/istefox-dt-mcp-${VERSION}.mcpb"
STAGING="${DIST}/staging"

echo "=> Building .mcpb v${VERSION}"
rm -rf "${STAGING}" "${OUT}"
mkdir -p "${STAGING}"

# Files/dirs we want INSIDE the bundle. Keeping the list explicit
# avoids accidentally shipping local secrets, datasets, or caches.
INCLUDE=(
    "manifest.json"
    "bundle_main.py"
    "pyproject.toml"
    "uv.lock"
    "README.md"
    "CHANGELOG.md"
    "apps"
    "libs"
)

for item in "${INCLUDE[@]}"; do
    if [ ! -e "${item}" ]; then
        echo "ERROR: required path missing: ${item}" >&2
        exit 1
    fi
    cp -R "${item}" "${STAGING}/"
done

# Strip artefacts that may have ridden along inside apps/ libs/.
find "${STAGING}" -type d \
    \( -name "__pycache__" -o -name ".pytest_cache" -o -name ".mypy_cache" \
       -o -name ".ruff_cache" -o -name ".venv" \) -prune -exec rm -rf {} +
find "${STAGING}" -type f \( -name "*.pyc" -o -name ".DS_Store" \) -delete

# Zip the staging dir into a .mcpb (zip with a custom extension).
( cd "${STAGING}" && zip -qr "${OUT}" . )

SIZE_KB="$(du -k "${OUT}" | cut -f1)"
FILE_COUNT="$(unzip -l "${OUT}" | tail -1 | awk '{print $2}')"

echo
echo "=> Bundle ready: ${OUT}"
echo "   Size:  ${SIZE_KB} KB"
echo "   Files: ${FILE_COUNT}"
echo
echo "Install:"
echo "   1. Open Claude Desktop"
echo "   2. Settings -> Developer -> Install Bundle"
echo "   3. Pick: ${OUT}"
echo
echo "Or manually drag the .mcpb onto the Claude Desktop window."
