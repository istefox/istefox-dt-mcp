#!/usr/bin/env bash
# Bundle entry point for the .mcpb desktop extension.
#
# Why this wrapper exists: macOS GUI applications (Claude Desktop)
# don't inherit the user's shell PATH. They see only the system
# default `/usr/bin:/bin:/usr/sbin:/sbin`, which excludes Homebrew
# (`/opt/homebrew/bin`, `/usr/local/bin`), cargo (`~/.cargo/bin`),
# pipx (`~/.local/bin`), mise/asdf shims and other common uv
# installation locations.
#
# Pinning a single absolute path in `manifest.json` (as v0.0.15-0.0.17
# did with `/opt/homebrew/bin/uv`) works only on Apple Silicon with
# Homebrew. This wrapper probes the standard locations and falls
# back to PATH lookup, so the bundle is portable across:
#   - Apple Silicon Homebrew  -> /opt/homebrew/bin/uv
#   - Intel Mac Homebrew      -> /usr/local/bin/uv
#   - cargo install           -> ~/.cargo/bin/uv
#   - pipx install            -> ~/.local/bin/uv (or pipx venvs path)
#   - astral.sh installer     -> ~/.local/bin/uv
#   - mise shim               -> ~/.local/share/mise/shims/uv
#   - mise installed binary   -> ~/.local/share/mise/installs/uv/<v>/bin/uv
#   - asdf shim (legacy)      -> ~/.asdf/shims/uv
#
# Override: if ISTEFOX_UV_BIN is set, use it verbatim (no probing).
# Useful for non-standard installs or when debugging path issues.

set -euo pipefail

UV_BIN=""

# Explicit override wins over any auto-detection.
if [ -n "${ISTEFOX_UV_BIN:-}" ]; then
    if [ -x "${ISTEFOX_UV_BIN}" ]; then
        UV_BIN="${ISTEFOX_UV_BIN}"
    else
        echo "ERROR: ISTEFOX_UV_BIN='${ISTEFOX_UV_BIN}' is not executable." >&2
        exit 127
    fi
fi

# Search order: most common first. Stop at the first executable hit.
if [ -z "${UV_BIN}" ]; then
    CANDIDATES=(
        "/opt/homebrew/bin/uv"
        "/usr/local/bin/uv"
        "${HOME}/.cargo/bin/uv"
        "${HOME}/.local/bin/uv"
        "${HOME}/.local/share/pipx/venvs/uv/bin/uv"
        "${HOME}/.local/share/mise/shims/uv"
        "${HOME}/.asdf/shims/uv"
    )

    for candidate in "${CANDIDATES[@]}"; do
        if [ -x "${candidate}" ]; then
            UV_BIN="${candidate}"
            break
        fi
    done
fi

# mise installs uv under ~/.local/share/mise/installs/uv/<version>/bin/uv;
# the shim above is the canonical entry point but if the shim isn't
# present (mise activate not run), fall back to scanning the installs
# dir. The glob expands to a literal "*" if no matches; the -x check
# rejects it harmlessly.
if [ -z "${UV_BIN}" ]; then
    for candidate in "${HOME}"/.local/share/mise/installs/uv/*/bin/uv; do
        if [ -x "${candidate}" ]; then
            UV_BIN="${candidate}"
            break
        fi
    done
fi

# Fallback to PATH (works if Claude Desktop was launched from a
# shell with a custom PATH, or if uv is in a non-standard location
# that happens to be on PATH).
if [ -z "${UV_BIN}" ]; then
    UV_BIN="$(command -v uv 2>/dev/null || true)"
fi

if [ -z "${UV_BIN}" ] || [ ! -x "${UV_BIN}" ]; then
    cat >&2 <<'EOF'
ERROR: uv binary not found.

The istefox-dt-mcp bundle requires `uv` to manage its Python runtime.
Install with one of:

    # Recommended (macOS):
    brew install uv

    # Cross-platform installer:
    curl -LsSf https://astral.sh/uv/install.sh | sh

    # Via mise (if you use mise to manage tools):
    mise use -g uv

    # Via cargo (Rust toolchain):
    cargo install --git https://github.com/astral-sh/uv uv

After installing, disable and re-enable the istefox-dt-mcp extension
in Claude Desktop (Settings -> Extensions).

If uv is installed in a non-standard location, set the env var
ISTEFOX_UV_BIN=/full/path/to/uv in your shell profile or pass it
through the Claude Desktop extension config.

Searched paths:
    /opt/homebrew/bin/uv
    /usr/local/bin/uv
    ~/.cargo/bin/uv
    ~/.local/bin/uv
    ~/.local/share/pipx/venvs/uv/bin/uv
    ~/.local/share/mise/shims/uv
    ~/.local/share/mise/installs/uv/*/bin/uv
    ~/.asdf/shims/uv
    $PATH (via `command -v`)
EOF
    exit 127
fi

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${UV_BIN}" run --directory "${DIR}" python "${DIR}/bundle_main.py" serve
