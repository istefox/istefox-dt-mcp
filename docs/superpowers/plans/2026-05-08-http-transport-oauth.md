# HTTP Transport + OAuth — Implementation Plan

- **Spec**: [`2026-05-08-http-transport-oauth-design.md`](../specs/2026-05-08-http-transport-oauth-design.md)
- **Target**: 0.4.0 (alpha = phases 1-2, final = phases 3-5)
- **Status**: phase 1 in flight 2026-05-08

Each phase = one PR. Tasks within a phase are sequential. Phases are gated by review; no skipping.

---

## Phase 1 — HTTP transport foundation

**Goal**: `istefox-dt-mcp serve --transport http --host 127.0.0.1 --port 3000` runs the streamable-HTTP MCP server. stdio still default. No auth yet (anonymous read for now, deferred to phase 2).

| # | Task | File | Verify |
|---|---|---|---|
| 1.1 | Add `fastmcp[http]` (or equivalent) + `uvicorn>=0.30` to server pkg `pyproject.toml`; `uv sync`; check no breakage | `apps/server/pyproject.toml` | `uv run python -c "import uvicorn; from fastmcp import FastMCP"` |
| 1.2 | Implement `transport/http.py` with `run_http(deps, host, port)` wrapping `mcp.run_http_async()` | `apps/server/src/istefox_dt_mcp_server/transport/http.py` (new) + `transport/__init__.py` | unit `test_transport_http_starts_and_stops` (lifespan + healthz) |
| 1.3 | Update `cli.py`: extend `--transport` choice with `http`, add `--host`/`--port` flags, dispatch to `run_http` | `apps/server/src/istefox_dt_mcp_server/cli.py` | `uv run istefox-dt-mcp serve --transport http --port 3001 &` then `curl http://127.0.0.1:3001/mcp/` returns 200 or 405 (not connection-refused) |
| 1.4 | Extend `scripts/smoke_e2e.sh` with HTTP step — start server with `--transport http --port <random>`, send `initialize` over HTTP, assert response, kill | `scripts/smoke_e2e.sh` | `scripts/smoke_e2e.sh` PASS includes new "Step 6 — HTTP transport lifecycle" line |
| 1.5 | Update `__init__.py` module docstring to remove "v2" qualifier from HTTP transport mention | `apps/server/src/istefox_dt_mcp_server/__init__.py` | grep clean |
| 1.6 | Commit + PR `feat(transport): HTTP streamable transport (0.4.0-alpha)` | — | CI green |

**Phase 1 completion gate**: smoke E2E passes both stdio and HTTP. Server responds on HTTP. Default behavior (stdio) unchanged.

---

## Phase 2 — OAuth scope decorator (no real OAuth yet)

**Goal**: scope enforcement plumbing in place, exercised via header `X-Istefox-Scope` (testing-only stub) that the middleware reads. Real OAuth flow lands in phase 4.

| # | Task | File | Verify |
|---|---|---|---|
| 2.1 | Define `Scope` enum + `RequestContext` dataclass + `InsufficientScopeError` | `apps/server/src/istefox_dt_mcp_server/auth/scope.py` (new) | unit `test_scope_enum` |
| 2.2 | Implement `requires_scope(scope: Scope)` decorator that reads request context via contextvar | same file | unit `test_requires_scope_blocks_when_missing` + `test_requires_scope_allows_when_present` |
| 2.3 | Implement `ScopeMiddleware` (FastMCP middleware): for stdio inject `granted_scopes={ALL}`; for HTTP read `X-Istefox-Scope` header, set contextvar | `auth/middleware.py` (new) | unit + contract `test_http_scope_header_resolved` |
| 2.4 | Decorate write tools with `@requires_scope(Scope.WRITE)`: `file_document`, `bulk_apply`. Decorate read tools with `@requires_scope(Scope.READ)` | `tools/*.py` | unit ensures decoration; contract: HTTP call without scope header → 403 envelope |
| 2.5 | Add `error_code=OAUTH_INSUFFICIENT_SCOPE` constant + envelope wiring | `tools/_common.py`, `safe_call.py` | contract test_insufficient_scope_returns_envelope |
| 2.6 | Commit + PR `feat(auth): scope enforcement plumbing (0.4.0-alpha)` | — | CI green; existing 222 tests still pass; ≥6 new tests |

**Phase 2 completion gate**: HTTP requests with no scope header are rejected by write tools. stdio unchanged. Real OAuth still TODO; the header is a testing-only stub.

---

## Phase 3 — ConsentStore + database scoping

**Goal**: per-database authorization persisted server-side. `list_databases` filters; tool calls against unauthorized databases return `RECONSENT_REQUIRED`.

| # | Task | File | Verify |
|---|---|---|---|
| 3.1 | Implement `ConsentStore` SQLite class with WAL + `synchronous=FULL` | `auth/consent.py` (new) | unit `test_consent_store_authorize_and_query` |
| 3.2 | Add `consent: ConsentStore` field to `Deps`; wire in `build_default_deps`; for stdio default to "all DBs authorized for local-stdio" | `deps.py` | unit + integration |
| 3.3 | Wire `consent.filter_visible` into `list_databases` | `tools/list_databases.py` | contract `test_list_databases_filters_unauthorized` |
| 3.4 | Add pre-flight `consent.check_or_raise` in `_common.safe_call` for write tools (database UUID extracted from input or record metadata) | `tools/_common.py` | contract `test_write_tool_against_unauthorized_db_returns_reconsent` |
| 3.5 | Add `RECONSENT_REQUIRED` error code + envelope path | schemas + safe_call | unit |
| 3.6 | Commit + PR `feat(auth): ConsentStore + per-DB authorization` | — | CI green |

**Phase 3 completion gate**: external mutation in DT4 (new DB) → `list_databases` over HTTP doesn't see it → call against its UUID returns `RECONSENT_REQUIRED`.

---

## Phase 4 — OAuth flow + consent UI

**Goal**: real PKCE flow ends in a bearer token. Consent UI lets user pick scopes and databases.

| # | Task | File | Verify |
|---|---|---|---|
| 4.1 | Add `authlib>=1.3` + `jinja2>=3.1` to server deps | `apps/server/pyproject.toml` | `uv sync` clean |
| 4.2 | Implement `OAuthProvider` (authlib-backed): authorize endpoint, token endpoint, JWT signing | `auth/oauth.py` (new) | unit (mock client + verifier) |
| 4.3 | Implement `consent_ui.py`: Jinja2 template for `/oauth/authorize`, form post to `/oauth/consent` | `auth/consent_ui.py` + `templates/consent.html` (new) | manual: open `/oauth/authorize` in browser |
| 4.4 | Mount OAuth routes in `transport/http.py` | same file | curl flow scriptable |
| 4.5 | Update middleware: validate JWT on requests, populate `RequestContext` from token claims | `auth/middleware.py` | contract `test_http_jwt_required` |
| 4.6 | Persist OAuth secret in `~/.local/share/istefox-dt-mcp/oauth_secret`; generate on first run with strict permissions | `auth/oauth.py` | unit |
| 4.7 | Document Cloudflare Tunnel setup as prerequisite in README | `README.md` | docs reviewable |
| 4.8 | Optional: write ADR-015 if callback URL design needs ratification | `docs/adr/0015-*.md` | review |
| 4.9 | Commit + PR `feat(auth): OAuth 2.1 + PKCE consent flow (0.4.0)` | — | CI green |

**Phase 4 completion gate**: full PKCE flow demoable end-to-end; tokens validated; tools enforce both scope and database.

---

## Phase 5 — Integration tests + release polish

**Goal**: 0.4.0 ready to tag.

| # | Task | File | Verify |
|---|---|---|---|
| 5.1 | Integration test: PKCE flow + tool call + scope rejection + reconsent path, against live DT4 | `tests/integration/test_http_transport_oauth_live.py` (new) | live PASS |
| 5.2 | Smoke E2E HTTP step extended with auth header | `scripts/smoke_e2e.sh` | smoke PASS on HTTP+OAuth |
| 5.3 | README: 3-step setup (Cloudflare Tunnel + consent + first connection) + screenshots optional | `README.md` | docs review |
| 5.4 | CHANGELOG entry for 0.4.0 | `CHANGELOG.md` | review |
| 5.5 | `architecture.md` updated: HTTP transport diagram + OAuth flow | `docs/architecture.md` | review |
| 5.6 | Bump version to 0.4.0 in manifest + SERVER_VERSION; release workflow | `apps/server/pyproject.toml`, `__init__.py`, manifest | tag pushed |
| 5.7 | Commit + PR `chore: release v0.4.0` | — | release workflow green; registry updated |

**Phase 5 completion gate**: 0.4.0 tagged, registry shows 0.4.0, smoke PASS on both transports.

---

## Tracking

- [x] Phase 1 — HTTP transport foundation (`860225c`, 2026-05-08, smoke 6/6 PASS)
- [x] Phase 2 — Scope enforcement plumbing (`3dc3df9`, 2026-05-08, 239 tests pass)
- [x] Phase 3 — ConsentStore + per-DB authorization (`b65c5a1`, 2026-05-08, 259 tests pass)
- [ ] Phase 4 — OAuth flow + consent UI
- [ ] Phase 5 — Integration tests + release

Update `handoff.md` at end of each phase. Each PR closes its phase tracking item here.
