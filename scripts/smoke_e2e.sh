#!/usr/bin/env bash
# Smoke E2E for istefox-dt-mcp.
#
# Final pre-tag check: exercises the actually-installed binary
# (`uv run istefox-dt-mcp`) instead of the test suite. Owner runs
# this manually before each release tag — if anything blows up here,
# DO NOT tag.
#
# Prerequisites:
#   * DEVONthink 4 running with at least one open database
#   * AppleEvents permission granted to Terminal/iTerm
#   * `uv` available on PATH
#
# Usage:
#   scripts/smoke_e2e.sh

set -euo pipefail

# ---------------------------------------------------------------------------
# Bootstrap: locate project root, set up temp dir + cleanup trap.
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

TMP_DIR="$(mktemp -d -t istefox-smoke.XXXXXX)"
SERVER_PID=""

# Cleanup runs on any exit (success, failure, signal).
cleanup() {
    local exit_code=$?
    if [[ -n "${SERVER_PID}" ]] && kill -0 "${SERVER_PID}" 2>/dev/null; then
        kill -TERM "${SERVER_PID}" 2>/dev/null || true
        sleep 1
        kill -KILL "${SERVER_PID}" 2>/dev/null || true
    fi
    rm -rf "${TMP_DIR}"
    exit "${exit_code}"
}
trap cleanup EXIT INT TERM

# ---------------------------------------------------------------------------
# Header: version + git HEAD short SHA.
# ---------------------------------------------------------------------------

VERSION="$(uv run --directory "${PROJECT_ROOT}" istefox-dt-mcp --version 2>/dev/null \
    | awk '{print $NF}' | tr -d '[:space:]')"
GIT_SHA="$(git -C "${PROJECT_ROOT}" rev-parse --short HEAD 2>/dev/null || echo "unknown")"

echo "==============================================================="
echo " istefox-dt-mcp smoke E2E"
echo "   version : ${VERSION}"
echo "   git HEAD: ${GIT_SHA}"
echo "   project : ${PROJECT_ROOT}"
echo "==============================================================="

# ---------------------------------------------------------------------------
# Step 1 — Doctor: verify DT is running and bridge is ready.
# ---------------------------------------------------------------------------

echo ""
echo "=> Step 1 — Doctor (dt_running + bridge_ready)"

DOCTOR_OUT="${TMP_DIR}/doctor.json"
if ! uv run --directory "${PROJECT_ROOT}" istefox-dt-mcp doctor >"${DOCTOR_OUT}" 2>"${TMP_DIR}/doctor.err"; then
    echo "   FAIL: doctor command exited non-zero" >&2
    cat "${TMP_DIR}/doctor.err" >&2 || true
    echo "   recovery: ensure DEVONthink 4 is running and try again" >&2
    echo "[FAIL] smoke fail (step 1)"
    exit 1
fi

# Parse JSON via python3 — strict assertion on both flags.
if ! python3 - "${DOCTOR_OUT}" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as fh:
    data = json.load(fh)

dt_running = bool(data.get("dt_running"))
bridge_ready = bool(data.get("bridge_ready"))

if not dt_running:
    print("   assertion failed: dt_running != true", file=sys.stderr)
    sys.exit(1)
if not bridge_ready:
    print("   assertion failed: bridge_ready != true", file=sys.stderr)
    sys.exit(1)

print(f"   ok: dt_running={dt_running}, bridge_ready={bridge_ready}")
PY
then
    echo "   FAIL: DEVONthink not running or bridge not ready" >&2
    echo "[FAIL] smoke fail (step 1)"
    exit 1
fi

# ---------------------------------------------------------------------------
# Step 2 — list_databases via raw JXA (independent of MCP server).
# ---------------------------------------------------------------------------

echo ""
echo "=> Step 2 — Raw JXA: list_databases"

DB_COUNT="$(osascript -l JavaScript -e 'Application("DEVONthink").databases().length' 2>"${TMP_DIR}/jxa.err" || echo "ERR")"

if [[ "${DB_COUNT}" == "ERR" ]] || ! [[ "${DB_COUNT}" =~ ^[0-9]+$ ]]; then
    # Detect the most common cause: AppleEvents permission denied (-1743).
    # Surface a precise recovery hint instead of dumping the cryptic error.
    if grep -q -- "-1743" "${TMP_DIR}/jxa.err" 2>/dev/null; then
        cat >&2 <<'EOF'
   FAIL: AppleEvents permission denied (-1743).

   The terminal/script needs explicit permission to control DEVONthink.
   Fix (3 options, in order of brutality):

   1. System Settings -> Privacy & Security -> Automation
      Find your terminal app (Warp/iTerm/Terminal/Ghostty) -> expand
      -> enable the DEVONthink toggle.

   2. If your terminal is NOT in the Automation list at all, the TCC
      cache may be stale. Reset it:
        tccutil reset AppleEvents <bundle-id>
      Common bundle IDs:
        Warp     -> dev.warp.Warp-Stable
        iTerm    -> com.googlecode.iterm2
        Terminal -> com.apple.Terminal
        Ghostty  -> com.mitchellh.ghostty
      Then re-run: osascript -l JavaScript -e 'Application("DEVONthink").databases().length'
      macOS will re-prompt with the consent dialog. Click "Allow".

   3. Try a different terminal app that may have a clean TCC slate
      (Terminal.app is always present on macOS).
EOF
    else
        echo "   FAIL: JXA returned non-numeric output: '${DB_COUNT}'" >&2
        cat "${TMP_DIR}/jxa.err" >&2 || true
    fi
    echo "[FAIL] smoke fail (step 2)"
    exit 1
fi

if (( DB_COUNT < 1 )); then
    echo "   FAIL: expected >=1 open database, got ${DB_COUNT}" >&2
    echo "[FAIL] smoke fail (step 2)"
    exit 1
fi

echo "   ok: ${DB_COUNT} open database(s)"

# ---------------------------------------------------------------------------
# Step 3 — Audit log writability: trigger an audit-touching CLI op and
# verify the SQLite db has at least one entry created today.
# ---------------------------------------------------------------------------

echo ""
echo "=> Step 3 — Audit log writability"

AUDIT_DB="${HOME}/.local/share/istefox-dt-mcp/audit.sqlite"

# Run a low-impact CLI op that exercises audit init/write. If `audit list`
# is not supported on this binary, treat as a soft warning rather than fail.
if ! uv run --directory "${PROJECT_ROOT}" istefox-dt-mcp audit list --recent 1 \
        >"${TMP_DIR}/audit.out" 2>"${TMP_DIR}/audit.err"; then
    echo "   WARN: audit list returned non-zero (may be expected if no rows yet)"
    cat "${TMP_DIR}/audit.err" >&2 || true
fi

if [[ ! -f "${AUDIT_DB}" ]]; then
    echo "   FAIL: audit DB not found at ${AUDIT_DB}" >&2
    echo "   recovery: run any write op once to initialize the audit store" >&2
    echo "[FAIL] smoke fail (step 3)"
    exit 1
fi

# Count rows created today across any audit table.
TODAY_ROWS="$(sqlite3 "${AUDIT_DB}" \
    "SELECT COUNT(*) FROM audit WHERE DATE(timestamp) = DATE('now', 'localtime');" \
    2>/dev/null || echo "0")"

if ! [[ "${TODAY_ROWS}" =~ ^[0-9]+$ ]]; then
    TODAY_ROWS=0
fi

if (( TODAY_ROWS < 1 )); then
    echo "   FAIL: audit DB exists but has no rows for today" >&2
    echo "   path: ${AUDIT_DB}" >&2
    echo "[FAIL] smoke fail (step 3)"
    exit 1
fi

echo "   ok: audit DB present with ${TODAY_ROWS} row(s) today (${AUDIT_DB})"

# ---------------------------------------------------------------------------
# Step 4 — Bundle build artifact check (warning only, not failure).
# ---------------------------------------------------------------------------

echo ""
echo "=> Step 4 — Bundle artifact check"

# The packaged bundle uses the server-package version, not the workspace root.
# Owner can override with BUNDLE_VERSION if it differs from VERSION.
BUNDLE_VERSION="${BUNDLE_VERSION:-${VERSION}}"
BUNDLE_PATH="${PROJECT_ROOT}/dist/istefox-dt-mcp-${BUNDLE_VERSION}.mcpb"

if [[ -f "${BUNDLE_PATH}" ]]; then
    BUNDLE_SIZE="$(wc -c <"${BUNDLE_PATH}" | tr -d '[:space:]')"
    echo "   ok: ${BUNDLE_PATH} (${BUNDLE_SIZE} bytes)"
else
    echo "   WARN: bundle not found at ${BUNDLE_PATH}"
    echo "   suggestion: run ./scripts/build_mcpb.sh before tagging"
    # Soft warning — do not fail the smoke.
fi

# ---------------------------------------------------------------------------
# Step 5 — Server starts, responds to initialize, exits cleanly on stdin EOF.
# ---------------------------------------------------------------------------

echo ""
echo "=> Step 5 — Server lifecycle (initialize + clean shutdown)"

SERVER_IN="${TMP_DIR}/server.in"
SERVER_OUT="${TMP_DIR}/server.out"
SERVER_ERR="${TMP_DIR}/server.err"
mkfifo "${SERVER_IN}"

# Spawn the server with stdin attached to a FIFO so we can close it later
# by simply removing the writer end (file descriptor 3 below).
exec 3>"${SERVER_IN}"
uv run --directory "${PROJECT_ROOT}" istefox-dt-mcp serve \
    <"${SERVER_IN}" >"${SERVER_OUT}" 2>"${SERVER_ERR}" &
SERVER_PID=$!

# Send initialize request.
printf '%s\n' '{"jsonrpc":"2.0","method":"initialize","params":{},"id":1}' >&3

# Wait up to 5s for a JSON-RPC response on stdout.
RESPONSE_OK=0
for _ in $(seq 1 50); do
    if [[ -s "${SERVER_OUT}" ]] && grep -q '"id":1' "${SERVER_OUT}" 2>/dev/null; then
        RESPONSE_OK=1
        break
    fi
    sleep 0.1
done

if (( RESPONSE_OK == 0 )); then
    echo "   FAIL: no initialize response within 5s" >&2
    echo "   --- stderr (last 20 lines) ---" >&2
    tail -n 20 "${SERVER_ERR}" >&2 || true
    kill -KILL "${SERVER_PID}" 2>/dev/null || true
    SERVER_PID=""
    echo "[FAIL] smoke fail (step 5)"
    exit 2
fi

echo "   ok: initialize response received"

# Close stdin (EOF) by closing fd 3 — server should exit on its own.
exec 3>&-

EXIT_OK=0
for _ in $(seq 1 30); do
    if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
        EXIT_OK=1
        break
    fi
    sleep 0.1
done

if (( EXIT_OK == 0 )); then
    echo "   FAIL: server did not exit within 3s after stdin EOF" >&2
    kill -KILL "${SERVER_PID}" 2>/dev/null || true
    SERVER_PID=""
    echo "[FAIL] smoke fail (step 5)"
    exit 2
fi

# Reap and clear so the cleanup trap does not double-kill.
wait "${SERVER_PID}" 2>/dev/null || true
SERVER_PID=""

echo "   ok: server exited cleanly on stdin EOF"

# ---------------------------------------------------------------------------
# Final verdict.
# ---------------------------------------------------------------------------

echo ""
echo "==============================================================="
echo "[PASS] smoke pass"
echo "==============================================================="
exit 0
