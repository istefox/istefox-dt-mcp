#!/usr/bin/env bash
# Bundle entry point for the .mcpb desktop extension.
#
# Why this wrapper exists: macOS GUI applications (Claude Desktop)
# don't inherit the user's shell PATH. They see only the system
# default `/usr/bin:/bin:/usr/sbin:/sbin`, which excludes Homebrew
# (`/opt/homebrew/bin`, `/usr/local/bin`), cargo (`~/.cargo/bin`),
# pipx (`~/.local/bin`) and other common uv installation locations.
#
# Pinning a single absolute path in `manifest.json` (as v0.0.15-0.0.17
# did with `/opt/homebrew/bin/uv`) works only on Apple Silicon with
# Homebrew. This wrapper probes the standard locations and falls
# back to PATH lookup, so the bundle is portable across:
#   - Apple Silicon Homebrew  → /opt/homebrew/bin/uv
#   - Intel Mac Homebrew      → /usr/local/bin/uv
#   - cargo install           → ~/.cargo/bin/uv
#   - pipx install            → ~/.local/bin/uv (or pipx venvs path)
#   - astral.sh installer     → ~/.local/bin/uv

set -euo pipefail

# Search order: most common first. Stop at the first executable hit.
CANDIDATES=(
    "/opt/homebrew/bin/uv"
    "/usr/local/bin/uv"
    "${HOME}/.cargo/bin/uv"
    "${HOME}/.local/bin/uv"
    "${HOME}/.local/share/pipx/venvs/uv/bin/uv"
)

UV_BIN=""
for candidate in "${CANDIDATES[@]}"; do
    if [ -x "${candidate}" ]; then
        UV_BIN="${candidate}"
        break
    fi
done

# Fallback to PATH (works if Claude Desktop was launched from a
# shell with a custom PATH, or if uv is in a non-standard location
# that happens to be on PATH).
if [ -z "${UV_BIN}" ]; then
    UV_BIN="$(command -v uv 2>/dev/null || true)"
fi

if [ -z "${UV_BIN}" ] || [ ! -x "${UV_BIN}" ]; then
    cat >&2 <<EOF
ERROR: uv binary not found.

Install uv with one of:
    brew install uv
    curl -LsSf https://astral.sh/uv/install.sh | sh
    cargo install --git https://github.com/astral-sh/uv uv

Then disable+re-enable the istefox-dt-mcp extension in Claude Desktop.
EOF
    exit 127
fi

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${UV_BIN}" run --directory "${DIR}" python "${DIR}/bundle_main.py" serve
