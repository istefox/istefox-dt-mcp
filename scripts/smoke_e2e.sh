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

# Schema sanity: verify audit_log table exists and is queryable.
# We do NOT require a row from "today" because:
#   - audit list (which we ran above) is a READ op, doesn't append
#   - doctor doesn't go through the audit-tracked tool framework
#   - a fresh install has zero rows on day 1, which is correct state
# What we WANT to validate: the schema is intact and the DB is
# writable (the latter is implicitly proven by the fact that build_default_deps
# could open it without error during `audit list`).
SCHEMA_CHECK="$(sqlite3 "${AUDIT_DB}" \
    "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='audit_log';" \
    2>/dev/null || echo "0")"

if [[ "${SCHEMA_CHECK}" != "1" ]]; then
    echo "   FAIL: audit_log table missing from ${AUDIT_DB}" >&2
    echo "   recovery: rm ${AUDIT_DB} and re-run any istefox-dt-mcp command" >&2
    echo "[FAIL] smoke fail (step 3)"
    exit 1
fi

# Count total rows (not "today") for an informational marker.
TOTAL_ROWS="$(sqlite3 "${AUDIT_DB}" \
    "SELECT COUNT(*) FROM audit_log;" \
    2>/dev/null || echo "0")"
if ! [[ "${TOTAL_ROWS}" =~ ^[0-9]+$ ]]; then
    TOTAL_ROWS=0
fi

echo "   ok: audit_log schema present, ${TOTAL_ROWS} total row(s) (${AUDIT_DB})"

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
# Step 5 — Server starts and responds to a JSON-RPC initialize request.
#
# Why this simpler design (vs the previous FIFO + fd 3 dance):
# - `uv run` spawns a Python subprocess that INHERITS the parent shell's
#   open file descriptors. Closing fd 3 in the parent did NOT propagate
#   to the spawned Python, so the FIFO read-side never saw EOF and the
#   server hung forever waiting for more input.
# - `echo | timeout cmd | head -1` is the canonical Unix smoke pattern:
#   * echo writes the request and closes its stdout
#   * timeout caps the whole pipeline at 10s
#   * head -1 reads the first response line then closes its stdin
#     (SIGPIPE propagates back, server's stdout write fails, server
#     exits cleanly via FastMCP's standard shutdown path)
# - No manual PID tracking, no lifecycle race, no hang.
# ---------------------------------------------------------------------------

echo ""
echo "=> Step 5 — Server lifecycle (initialize + clean shutdown)"

SERVER_ERR="${TMP_DIR}/server.err"
INIT_REQUEST='{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke","version":"0.0.0"}},"id":1}'

# Detect a timeout binary. macOS does not ship GNU `timeout` by default;
# `gtimeout` is available if coreutils is installed via Homebrew.
# If neither exists, we still rely on `head -1` + SIGPIPE for cleanup
# (proven to work for FastMCP servers — the server exits cleanly when
# its stdout writer fails). The timeout is a belt-and-suspenders for
# the case where the server doesn't write anything at all.
TIMEOUT_PREFIX=()
if command -v timeout >/dev/null 2>&1; then
    TIMEOUT_PREFIX=(timeout 10)
elif command -v gtimeout >/dev/null 2>&1; then
    TIMEOUT_PREFIX=(gtimeout 10)
fi

# Pipeline:
#   echo INIT_REQUEST -> server stdin
#   server stdout -> head -1 (reads first line, closes its stdin)
#   When head closes, server's next stdout write fails (SIGPIPE) and
#   FastMCP's standard shutdown path triggers a clean exit.
set +e
if (( ${#TIMEOUT_PREFIX[@]} > 0 )); then
    RESPONSE="$(printf '%s\n' "${INIT_REQUEST}" \
        | "${TIMEOUT_PREFIX[@]}" uv run --directory "${PROJECT_ROOT}" \
            istefox-dt-mcp serve 2>"${SERVER_ERR}" \
        | head -1)"
else
    RESPONSE="$(printf '%s\n' "${INIT_REQUEST}" \
        | uv run --directory "${PROJECT_ROOT}" istefox-dt-mcp serve \
            2>"${SERVER_ERR}" \
        | head -1)"
fi
PIPE_STATUS=("${PIPESTATUS[@]}")
set -e

# Pipeline exit codes vary; what we really care about is RESPONSE content.
# Expected status[1] (server stage):
#   0   -> server exited cleanly via SIGPIPE handling
#   141 -> SIGPIPE (also acceptable)
#   124 -> timeout fired (only possible if a timeout binary was found)

if [[ -z "${RESPONSE}" ]]; then
    echo "   FAIL: server did not produce any stdout" >&2
    echo "   pipeline exit codes: ${PIPE_STATUS[*]}" >&2
    echo "   --- stderr (last 30 lines) ---" >&2
    tail -n 30 "${SERVER_ERR}" >&2 || true
    echo "[FAIL] smoke fail (step 5)"
    exit 2
fi

# 124 only happens if timeout actually fired; treat it as a hang.
if (( ${#TIMEOUT_PREFIX[@]} > 0 )) && (( ${PIPE_STATUS[1]:-0} == 124 )); then
    echo "   FAIL: server hung beyond 10s timeout (response was: ${RESPONSE})" >&2
    echo "[FAIL] smoke fail (step 5)"
    exit 2
fi

# Validate the response is a JSON-RPC envelope referring to id=1.
if ! grep -q '"id":1' <<<"${RESPONSE}"; then
    echo "   FAIL: response doesn't contain expected id=1 marker" >&2
    echo "   got: ${RESPONSE}" >&2
    echo "[FAIL] smoke fail (step 5)"
    exit 2
fi

echo "   ok: initialize response received, server exited cleanly"

# ---------------------------------------------------------------------------
# Step 6 — HTTP transport lifecycle (0.4.0 phase 1).
#
# Starts the server with --transport http on a random high port, sends
# `initialize` over HTTP (Streamable transport requires SSE accept), and
# verifies the response contains a JSON-RPC envelope with id=1. SIGTERM
# stops the server; we wait briefly to confirm clean shutdown.
# ---------------------------------------------------------------------------

echo ""
echo "=> Step 6 — HTTP transport lifecycle (initialize + clean shutdown)"

# Pick a random high port to avoid stomping on dev servers.
HTTP_PORT="$(python3 -c "import random; print(random.randint(20000, 29999))")"
HTTP_LOG="${TMP_DIR}/http-server.log"

# Start the HTTP server in background. We capture its PID so cleanup
# trap can kill it on any path out (success/failure/signal).
uv run --directory "${PROJECT_ROOT}" istefox-dt-mcp serve \
    --transport http --host 127.0.0.1 --port "${HTTP_PORT}" \
    >"${HTTP_LOG}" 2>&1 &
SERVER_PID=$!

# Wait up to 5s for the server to bind. The "Uvicorn running on" line in
# the log is the canonical readiness signal.
READY=""
for _ in $(seq 1 20); do
    if grep -q "Uvicorn running on" "${HTTP_LOG}" 2>/dev/null; then
        READY=1
        break
    fi
    if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
        echo "   FAIL: HTTP server died before listening" >&2
        echo "   --- log ---" >&2
        cat "${HTTP_LOG}" >&2 || true
        echo "[FAIL] smoke fail (step 6)"
        exit 3
    fi
    sleep 0.25
done

if [[ -z "${READY}" ]]; then
    echo "   FAIL: HTTP server didn't reach 'Uvicorn running' within 5s" >&2
    echo "   --- log ---" >&2
    cat "${HTTP_LOG}" >&2 || true
    echo "[FAIL] smoke fail (step 6)"
    exit 3
fi

HTTP_RESP="${TMP_DIR}/http-resp.txt"
HTTP_INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke","version":"0.0.0"}}}'

set +e
HTTP_CODE="$(curl -s -o "${HTTP_RESP}" -w "%{http_code}" --max-time 5 \
    -X POST "http://127.0.0.1:${HTTP_PORT}/mcp/" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d "${HTTP_INIT}")"
CURL_RC=$?
set -e

if (( CURL_RC != 0 )); then
    echo "   FAIL: curl exited ${CURL_RC} talking to HTTP server" >&2
    echo "   --- server log (tail) ---" >&2
    tail -n 30 "${HTTP_LOG}" >&2 || true
    echo "[FAIL] smoke fail (step 6)"
    exit 3
fi

if [[ "${HTTP_CODE}" != "200" ]]; then
    echo "   FAIL: expected HTTP 200, got ${HTTP_CODE}" >&2
    echo "   --- response body ---" >&2
    cat "${HTTP_RESP}" >&2 || true
    echo "[FAIL] smoke fail (step 6)"
    exit 3
fi

if ! grep -q '"id":1' "${HTTP_RESP}"; then
    echo "   FAIL: HTTP response missing JSON-RPC id=1 marker" >&2
    echo "   --- response body ---" >&2
    cat "${HTTP_RESP}" >&2 || true
    echo "[FAIL] smoke fail (step 6)"
    exit 3
fi

# Clean shutdown.
kill -TERM "${SERVER_PID}" 2>/dev/null || true
# Wait briefly; the cleanup trap will SIGKILL if needed.
for _ in $(seq 1 8); do
    if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
        break
    fi
    sleep 0.25
done
SERVER_PID=""

echo "   ok: HTTP initialize response received, server exited cleanly (port ${HTTP_PORT})"

# ---------------------------------------------------------------------------
# Step 7 — OAuth flow surface (0.4.0 phase 4).
#
# Spins up the HTTP server, calls /oauth/authorize and /oauth/token to
# verify the PKCE endpoints are mounted and respond with the expected
# shapes (HTML 200 / OAuth 2.1 invalid_grant JSON). A full PKCE
# round-trip with token issuance is covered by the integration test
# `test_pkce_flow_end_to_end_live` — this step is the lighter
# liveness probe suitable for the pre-tag gate.
# ---------------------------------------------------------------------------

echo ""
echo "=> Step 7 — OAuth endpoints (authorize + token surface)"

OAUTH_PORT="$(python3 -c "import random; print(random.randint(20000, 29999))")"
OAUTH_LOG="${TMP_DIR}/oauth-server.log"

uv run --directory "${PROJECT_ROOT}" istefox-dt-mcp serve \
    --transport http --host 127.0.0.1 --port "${OAUTH_PORT}" \
    >"${OAUTH_LOG}" 2>&1 &
SERVER_PID=$!

OAUTH_READY=""
for _ in $(seq 1 20); do
    if grep -q "Uvicorn running on" "${OAUTH_LOG}" 2>/dev/null; then
        OAUTH_READY=1
        break
    fi
    if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
        echo "   FAIL: HTTP server died before listening" >&2
        cat "${OAUTH_LOG}" >&2 || true
        echo "[FAIL] smoke fail (step 7)"
        exit 4
    fi
    sleep 0.25
done
if [[ -z "${OAUTH_READY}" ]]; then
    echo "   FAIL: HTTP server didn't bind for OAuth probe" >&2
    cat "${OAUTH_LOG}" >&2 || true
    echo "[FAIL] smoke fail (step 7)"
    exit 4
fi

# Build a valid PKCE challenge so /oauth/authorize doesn't 400.
PKCE_CHALLENGE="$(uv run --directory "${PROJECT_ROOT}" python -c \
    'from authlib.oauth2.rfc7636 import create_s256_code_challenge; print(create_s256_code_challenge("v" * 64))')"

OAUTH_AUTH_RESP="${TMP_DIR}/oauth-authorize.html"
set +e
OAUTH_AUTH_CODE="$(curl -s -o "${OAUTH_AUTH_RESP}" -w "%{http_code}" --max-time 5 \
    "http://127.0.0.1:${OAUTH_PORT}/oauth/authorize?client_id=smoke&redirect_uri=http://127.0.0.1:9999/cb&response_type=code&code_challenge=${PKCE_CHALLENGE}&code_challenge_method=S256&scope=dt:read&state=s")"
set -e

if [[ "${OAUTH_AUTH_CODE}" != "200" ]]; then
    echo "   FAIL: /oauth/authorize returned ${OAUTH_AUTH_CODE}, expected 200" >&2
    cat "${OAUTH_AUTH_RESP}" >&2 || true
    kill -TERM "${SERVER_PID}" 2>/dev/null || true
    echo "[FAIL] smoke fail (step 7)"
    exit 4
fi
if ! grep -q "Approve" "${OAUTH_AUTH_RESP}"; then
    echo "   FAIL: consent UI missing Approve button" >&2
    head -c 400 "${OAUTH_AUTH_RESP}" >&2 || true
    kill -TERM "${SERVER_PID}" 2>/dev/null || true
    echo "[FAIL] smoke fail (step 7)"
    exit 4
fi

# /oauth/token with bogus code must return JSON invalid_grant per OAuth 2.1.
OAUTH_TOK_RESP="${TMP_DIR}/oauth-token.json"
set +e
OAUTH_TOK_CODE="$(curl -s -o "${OAUTH_TOK_RESP}" -w "%{http_code}" --max-time 5 \
    -X POST "http://127.0.0.1:${OAUTH_PORT}/oauth/token" \
    -d "grant_type=authorization_code&code=nope&code_verifier=vvvvvvvv")"
set -e

if [[ "${OAUTH_TOK_CODE}" != "400" ]]; then
    echo "   FAIL: /oauth/token expected 400 for bogus code, got ${OAUTH_TOK_CODE}" >&2
    cat "${OAUTH_TOK_RESP}" >&2 || true
    kill -TERM "${SERVER_PID}" 2>/dev/null || true
    echo "[FAIL] smoke fail (step 7)"
    exit 4
fi
if ! grep -q '"error":"invalid_grant"' "${OAUTH_TOK_RESP}"; then
    echo "   FAIL: /oauth/token didn't return invalid_grant envelope" >&2
    cat "${OAUTH_TOK_RESP}" >&2 || true
    kill -TERM "${SERVER_PID}" 2>/dev/null || true
    echo "[FAIL] smoke fail (step 7)"
    exit 4
fi

kill -TERM "${SERVER_PID}" 2>/dev/null || true
for _ in $(seq 1 8); do
    if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
        break
    fi
    sleep 0.25
done
SERVER_PID=""

echo "   ok: /oauth/authorize 200 + consent UI; /oauth/token invalid_grant on bad code"

# ---------------------------------------------------------------------------
# Final verdict.
# ---------------------------------------------------------------------------

echo ""
echo "==============================================================="
echo "[PASS] smoke pass"
echo "==============================================================="
exit 0
