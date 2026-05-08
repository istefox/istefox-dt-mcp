# HTTP Transport + OAuth (multi-device) — Design Spec

- **Status**: proposed 2026-05-08
- **Target version**: 0.4.0
- **Owner**: istefox
- **Scope**: dual-transport server (stdio + streamable HTTP), OAuth 2.1 + PKCE auth, ConsentStore, scope middleware, consent UI, integration tests
- **Related**: ADR-006 (OAuth scope model — Accepted), brief §5.2, REVIEW_ADR §3 #12 (callback URL design open question)
- **Out of scope**: multi-tenant per-user ACL, rate limiting (deferred to ADR-014), telemetry export (ADR-011), OAuth dynamic client registration

---

## 1. Context

ADR-006 fixes the OAuth scope model: 3 scope (`dt:read`, `dt:write`, `dt:admin`) with database-scoping persisted server-side outside the token. Implementation was deferred to 0.4.0 alongside the actual HTTP transport. Today the server only runs `stdio`; the `--transport` flag in `cli.py` rejects anything else.

Driver for 0.4.0:
- **Multi-device**: enable Claude.ai Web / mobile clients to reach the server through Cloudflare Tunnel SATURNO without forcing local install.
- **Future-proofing**: streamable HTTP is the MCP-spec transport for hosted/remote servers; we already declared dual-transport in `__init__.py`, ship it.
- **OAuth foundation**: with HTTP we need real auth. The decision was made (ADR-006); now wire it.

Existing assets:
- `webhook.py`: a tiny `BaseHTTPRequestHandler` for DT smart-rule sync — unrelated to MCP transport, lives on its own port.
- FastMCP exposes `mcp.run_http_async()` and `mcp.http_app()` (uvicorn-friendly ASGI app). No custom transport code needed.

Nothing for OAuth yet: no `authlib` dep, no consent persistence, no scope enforcement.

## 2. Goals

- **G1**: `istefox-dt-mcp serve --transport http --host <h> --port <p>` starts a streamable-HTTP MCP server.
- **G2**: stdio transport remains the default and untouched (no regressions).
- **G3**: HTTP transport requires OAuth 2.1 + PKCE auth on every MCP request. Tokens carry one of `dt:read`/`dt:write`/`dt:admin`.
- **G4**: Tools enforce scope via a `@requires_scope(Scope.X)` decorator. Insufficient scope → structured `OAUTH_INSUFFICIENT_SCOPE` error envelope.
- **G5**: `ConsentStore` (SQLite) persists which databases each principal authorized. Tools filter visible databases automatically; new databases trigger `RECONSENT_REQUIRED`.
- **G6**: Consent UI: minimal HTML page rendered by the server at `/oauth/consent` with scope toggles and database checkboxes.
- **G7**: Integration tests exercise the HTTP path with a mock OAuth client + at least 2 scope-mismatch scenarios.
- **G8**: README + ADR-006 cross-references updated; new ADR if transport-specific decisions surface (callback URL design).

## 3. Non-goals

- **NG1**: Multi-user concurrent access to the same server. v1 = single principal at a time (single Stefano account, possibly from multiple devices). No per-user ACL.
- **NG2**: Cloudflare Tunnel automation. The user configures it manually; the server only needs to bind a localhost port.
- **NG3**: Token refresh / long-lived sessions. Initial v1 issues short-lived tokens (1h); user re-consents on expiry.
- **NG4**: Rate limiting per scope — out, ADR-014 territory.
- **NG5**: TLS termination — server stays HTTP behind Cloudflare Tunnel, which terminates TLS. Direct exposure not supported.

## 4. Architecture

### 4.1 High level

```
[Claude.ai / mobile]  --HTTPS-->  [Cloudflare Tunnel SATURNO]
                                          |
                                          v  (HTTP)
                              +------------------------+
                              | uvicorn :3000          |
                              |   /mcp/*  (streamable) |
                              |   /oauth/*  (consent)  |
                              |   /health              |
                              +------------------------+
                                          |
                              +------------------------+
                              | FastMCP server         |
                              |  + ScopeMiddleware     |
                              |  + ConsentMiddleware   |
                              +------------------------+
                                          |
                              +------------------------+
                              | Tools (scope-decorated)|
                              |   + Deps               |
                              |     - JXAAdapter       |
                              |     - AuditLog         |
                              |     - ConsentStore  ←──┐
                              +------------------------+
                                          ↑            │
                                          └── persists │
                                              consent  │
                                          (SQLite)  ───┘
```

### 4.2 New components

| Component | Path | Responsibility |
|---|---|---|
| `transport/http.py` | `apps/server/src/istefox_dt_mcp_server/transport/http.py` | Build the ASGI app, mount FastMCP HTTP, mount OAuth routes, configure CORS |
| `auth/scope.py` | `apps/server/src/istefox_dt_mcp_server/auth/scope.py` | `Scope` enum + `requires_scope` decorator + `InsufficientScopeError` |
| `auth/consent.py` | `apps/server/src/istefox_dt_mcp_server/auth/consent.py` | `ConsentStore` SQLite + `ReconsentRequiredError` |
| `auth/oauth.py` | `apps/server/src/istefox_dt_mcp_server/auth/oauth.py` | authlib OAuth 2.1 + PKCE provider, token issuance/validation |
| `auth/middleware.py` | `apps/server/src/istefox_dt_mcp_server/auth/middleware.py` | FastMCP middleware: extract bearer token → resolve principal → attach context |
| `auth/consent_ui.py` | `apps/server/src/istefox_dt_mcp_server/auth/consent_ui.py` | Jinja2-rendered consent page; minimal HTML |
| `Deps.consent` | `apps/server/src/istefox_dt_mcp_server/deps.py` | New field on Deps |

### 4.3 Tool decoration pattern

```python
# tools/file_document.py
from ..auth.scope import Scope, requires_scope

def register(mcp: FastMCP, deps: Deps) -> None:
    @mcp.tool()
    @requires_scope(Scope.WRITE)
    async def file_document(input: FileDocumentInput) -> FileDocumentOutput:
        ...
```

The decorator no-ops on stdio (where there's no auth context). On HTTP, the middleware injects `principal_id` and `granted_scopes`; the decorator checks before invoking.

### 4.4 ConsentStore schema

```sql
CREATE TABLE IF NOT EXISTS consent (
    principal_id TEXT NOT NULL,
    database_uuid TEXT NOT NULL,
    granted_at INTEGER NOT NULL,  -- unix ts
    PRIMARY KEY (principal_id, database_uuid)
);

CREATE INDEX IF NOT EXISTS idx_consent_principal
    ON consent(principal_id);
```

Lookups are O(1) per database. `filter_visible(principal_id, all_dbs)` is a single `SELECT database_uuid FROM consent WHERE principal_id = ?` then a Python set difference.

### 4.5 OAuth flow (PKCE)

1. Client generates `code_verifier`, hashes to `code_challenge`.
2. Client redirects user to `GET /oauth/authorize?client_id=...&scope=dt:read+dt:write&code_challenge=...`.
3. Server renders consent UI: scope toggles + database checkboxes. User submits.
4. Server stores `(client_id, principal_id, granted_scopes, granted_dbs)` keyed by `auth_code`, redirects to client's `redirect_uri` with `?code=<auth_code>`.
5. Client `POST /oauth/token` with `code` + `code_verifier`. Server validates, issues bearer token (JWT signed with HMAC, key in `~/.local/share/istefox-dt-mcp/oauth_secret`), TTL 1h.
6. Client uses `Authorization: Bearer <token>` on every MCP request.
7. Token expiry → 401 → client repeats from step 2.

## 5. Phasing

Work split into 5 phases, each PR-able and shippable independently. Phases 1-2 may land in 0.4.0-alpha; 3-5 land in 0.4.0 final.

| Phase | Title | Key deliverable | LOC est. |
|---|---|---|---|
| **1** | HTTP transport foundation | `--transport http` works; uvicorn dep added; smoke test on stdio + HTTP | ~250 |
| **2** | OAuth scope decorator | `Scope` enum + `requires_scope` + middleware skeleton (no real OAuth yet, just header passthrough); unit + contract tests | ~350 |
| **3** | ConsentStore | SQLite store + `filter_visible` integration in `list_databases` + `RECONSENT_REQUIRED` error path | ~300 |
| **4** | OAuth flow + consent UI | authlib integration, PKCE, Jinja2 consent page, token issuance | ~600 |
| **5** | Integration tests + docs | Multi-client E2E test, README updates, optional ADR for callback URL design | ~300 |

Total ~1800 LOC across server + tests + docs. Realistic ~2 weeks calendar (one phase ≈ 2 days inc. review).

## 6. Open questions (resolve before phase 4)

- **Q1** (REVIEW_ADR §3 #12): callback URL design for Claude.ai Web client. Options: (a) loopback `localhost:N` requires user device exposure → not workable behind Cloudflare. (b) Cloudflare Tunnel domain `dt-mcp.istefox.dev/oauth/callback` → cleanest. (c) Custom URI scheme `istefox-dt-mcp://callback` → mobile-friendly but desktop OS-dependent. **Proposal**: (b) for HTTP transport, document Cloudflare Tunnel setup as prerequisite.
- **Q2**: token signing — HMAC (single-server) vs RSA (key rotation friendly). For single-user single-server, HMAC is fine; revisit for v2.
- **Q3**: should consent UI also offer a "deny all" / global-revoke button? Probably yes, behind `dt:admin` scope.
- **Q4**: how does stdio transport behave with scope decorators? **Proposal**: middleware injects `principal_id="local-stdio"` and `granted_scopes={ALL}` so the decorator no-ops. No regression for desktop installs.

## 7. Risks

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| FastMCP HTTP API API breaking-changes between minor releases | Medium | High | Pin `fastmcp` minor version; CI smoke on HTTP; ADR if API changes mid-implementation |
| Cloudflare Tunnel adds latency that breaks `read p95 < 500ms` SLO | Low | Medium | Measure during phase 5; bypass tunnel for benchmarks |
| ConsentStore corruption (SQLite WAL crash mid-write) | Low | High | WAL mode + `synchronous=FULL`; doctor command to verify integrity |
| OAuth secret leaked via logs | Medium | High | Redaction in structlog config; never log token bodies, only token IDs |
| Token replay across devices (single token used by 2 clients) | Medium | Low | v1 accepts: single-user. Document. v2 considers per-device binding. |

## 8. Test strategy

- **Tier 1 (unit)**: `test_scope_decorator.py`, `test_consent_store.py`, `test_oauth_provider.py`. Mocked deps. Run on every push.
- **Tier 2 (contract)**: HTTP transport contract test — `httpx.AsyncClient` against the in-process ASGI app; verify scope errors return correct envelope. Run on every push.
- **Tier 3 (integration)**: full PKCE flow → tool call → undo, against live DT4. Skipped by default. Run pre-tag.
- **Tier 4 (smoke)**: `scripts/smoke_e2e.sh` extended with `--transport http` step.

## 9. Success criteria for 0.4.0

- ✅ `istefox-dt-mcp serve --transport http` runs without errors
- ✅ Claude Desktop with mcp.json HTTP entry can call all 6 read tools end-to-end
- ✅ Write tools (`file_document`, `bulk_apply`) require `dt:write` scope; reject otherwise
- ✅ New database created in DT4 → `list_databases` filters it out → tool call against its UUID returns `RECONSENT_REQUIRED`
- ✅ All 222 existing tests still green; ≥10 new unit tests + 1 contract test pass
- ✅ Smoke E2E PASS on both stdio and HTTP
- ✅ README documents the 3-step setup (Cloudflare Tunnel + consent + first connection)

## 10. References

- ADR-006 (`docs/adr/0006-oauth-scope-model.md`) — Accepted decision basis
- REVIEW_ADR §P6, §3 #12 — original review notes
- FastMCP HTTP docs — https://github.com/jlowin/fastmcp (verify before phase 1)
- authlib OAuth 2.1 — https://docs.authlib.org/
- MCP spec streamable HTTP — https://modelcontextprotocol.io/specification/server/transports
