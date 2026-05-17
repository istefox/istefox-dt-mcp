# Architecture overview

Vista corrente dell'architettura, allineata agli ADR consolidati e
all'implementazione di 0.4.0 (HTTP transport + OAuth PKCE multi-device).
Riferimento storico: [`ARCH-BRIEF-DT-MCP.md`](../ARCH-BRIEF-DT-MCP.md), [`docs/adr/REVIEW_ADR.md`](adr/REVIEW_ADR.md).

---

## Vista a layer (0.4.0)

```
┌──────────────────────────────────────────────────────────────┐
│ Tier 1 — Client AI                                           │
│ Claude Desktop (stdio)  ─┐                                   │
│ Claude.ai Web/mobile    ─┤── via Cloudflare Tunnel + OAuth   │
│ httpx/curl scripts      ─┘                                   │
└────────────────────┬─────────────────────────────────────────┘
                     │
                     │  JSON-RPC 2.0 (stdio)
                     │  oppure HTTPS → Tunnel → HTTP /mcp/
┌────────────────────┴─────────────────────────────────────────┐
│ Tier 2 — Transport                                           │
│  stdio (FastMCP run)         — Claude Desktop default       │
│  streamable-http (uvicorn)   — multi-device (--transport http)│
│   ├─ /mcp/         JSON-RPC + SSE                            │
│   ├─ /oauth/authorize  GET  consent UI (Jinja2)              │
│   ├─ /oauth/consent    POST mint auth code + redirect        │
│   └─ /oauth/token      POST PKCE verify → JWT bearer         │
└────────────────────┬─────────────────────────────────────────┘
                     │
┌────────────────────┴─────────────────────────────────────────┐
│ Tier 3 — Auth (0.4.0)                                        │
│  ScopeMiddleware (FastMCP middleware)                        │
│   ├─ stdio:    principal=local-stdio, ALL_SCOPES             │
│   └─ HTTP:     Authorization: Bearer <jwt> → claims          │
│                fallback: X-Istefox-Scope CSV (testing)       │
│  JWTIssuer (HS256/joserfc, 32B HMAC, oauth_secret 0600)      │
│  AuthCodeStore (SQLite, one-shot, 10min TTL)                 │
│  ConsentStore (SQLite, per-DB authorization, ADR-006)        │
└────────────────────┬─────────────────────────────────────────┘
                     │
┌────────────────────┴─────────────────────────────────────────┐
│ Tier 4 — MCP Capabilities                                    │
│  Tools registrati (decorati con required_scope):             │
│   READ:  list_databases · search · find_related ·            │
│          ask_database · summarize_topic                      │
│   WRITE: file_document · bulk_apply                          │
└────────────────────┬─────────────────────────────────────────┘
                     │
┌────────────────────┴─────────────────────────────────────────┐
│ Tier 5 — Service layer (apps/server)                         │
│  - safe_call wrapper (scope gate + audit + i18n + envelope)  │
│  - structured logging (structlog → stderr JSON)              │
│  - audit log SQLite append-only                              │
│  - i18n (errori italiano via locales/it.toml)                │
└────────────────────┬─────────────────────────────────────────┘
                     │
┌────────────────────┴─────────────────────────────────────────┐
│ Tier 6 — Bridge adapter (libs/adapter)                       │
│  - DEVONthinkAdapter ABC (multi-bridge ready)                │
│  - JXAAdapter: pool semaphore + retry + timeout              │
│  - SQLite WAL cache con TTL per categoria                    │
│  - Tassonomia errori strutturati con recovery_hint           │
│  - Script JXA in scripts/*.js (param via argv positional)    │
└────────────────────┬─────────────────────────────────────────┘
                     │ osascript -l JavaScript
┌────────────────────┴─────────────────────────────────────────┐
│ Tier 7 — Target                                              │
│  DEVONthink 4 (macOS, locale, in esecuzione)                 │
└──────────────────────────────────────────────────────────────┘
```

---

## OAuth 2.1 + PKCE flow (0.4.0)

```
   Client                     istefox-dt-mcp HTTP                 User-agent
   ──────                     ────────────────────                 ──────────
     │                                  │                              │
     │ 1. compute code_verifier         │                              │
     │    + code_challenge (S256)       │                              │
     │                                  │                              │
     │ 2. redirect to                   │                              │
     │    /oauth/authorize ─────────────┤                              │
     │    ?client_id=...                │                              │
     │    &redirect_uri=...             │                              │
     │    &code_challenge=...           │                              │
     │    &code_challenge_method=S256   │                              │
     │    &scope=dt:read+dt:write       │                              │
     │    &state=xyz                    │ 3. GET → render consent_ui   │
     │                                  ├─────────────────────────────►│
     │                                  │                              │
     │                                  │ 4. user ticks scopes + DBs,  │
     │                                  │    submits POST /oauth/consent│
     │                                  ◄──────────────────────────────┤
     │                                  │                              │
     │                                  │ 5. ConsentStore.authorize    │
     │                                  │    AuthCodeStore.issue       │
     │                                  │                              │
     │ 6. ◄──── 302 redirect ───────────┤                              │
     │      ?code=<auth_code>&state=xyz │                              │
     │                                  │                              │
     │ 7. POST /oauth/token ────────────┤                              │
     │    grant_type=authorization_code │                              │
     │    code=<auth_code>              │ 8. AuthCodeStore.consume     │
     │    code_verifier=<...>           │    verify_pkce_s256          │
     │                                  │    JWTIssuer.issue           │
     │ 9. ◄──── 200 JSON ───────────────┤                              │
     │      {access_token: <jwt>, ...}  │                              │
     │                                  │                              │
     │ 10. POST /mcp/                   │                              │
     │     Authorization: Bearer <jwt> ─┤                              │
     │                                  │ 11. ScopeMiddleware verify   │
     │                                  │     RequestContext set       │
     │                                  │     Tool runs scope-gated    │
     │ 12. ◄── MCP envelope ────────────┤                              │
```

The token bakes in the granted scopes (`dt:read`/`dt:write`/`dt:admin`).
Database-scoping is **outside the token** (in ConsentStore) so newly
created databases trigger `RECONSENT_REQUIRED` instead of getting a
free pass — see ADR-006.

---

## Flusso di una chiamata `search`

1. Client (Claude Desktop) invia JSON-RPC `tools/call` con name=`search`.
2. FastMCP valida l'input contro `SearchInput` (Pydantic v2).
3. Il tool wrapper (`safe_call`) avvia il timer, invoca il bridge.
4. `JXAAdapter.search(...)` acquisisce il semaphore, spawn `osascript`, attende output JSON con timeout.
5. Output JXA parseato, validato contro `SearchResult`.
6. `safe_call` registra l'entry nell'`audit_log` (success o failure), ritorna `SearchOutput` envelope al client.
7. Logging strutturato emesso su stderr (mai stdout — corromperebbe stdio).

In caso di errore: `AdapterError` catturato, tradotto via `Translator` (it.toml), persistito nell'audit log con `error_code`, ritornato al client come envelope `success=False` con `recovery_hint` italiano.

---

## MCP Resources & Prompts (0.5.0)

Completamento di protocollo: oltre ai 7 tool, il server espone tre
**resource** read-only e due **prompt** template-only.

- **Resource** (`apps/server/resources/`):
  - `dt://databases` — database aperti, consent-filtered, uuid-sorted
  - `dt://record/{uuid}/metadata` — scheda metadati (no body documento)
  - `dt://record/{uuid}/text` — testo del record, troncato a un bound fisso
- **Prompt** (`apps/server/prompts/`):
  - `weekly_review`, `triage_inbox` — solo template, orchestrano i tool
    esistenti (nessuna logica nuova lato server)

Le resource **riusano l'infra esistente** (adapter JXA, ConsentStore,
audit log, scope OAuth): **zero nuove dipendenze, zero nuovi script
JXA**. Le letture passano dal gate `safe_resource` (scope + consent):
a differenza di `safe_call`, un fallo **solleva** (`ReconsentRequiredError`
/ scope insufficiente) invece di ritornare un envelope `success=False` —
una resource MCP non ha forma envelope, quindi fail-closed via eccezione.
Output deterministico, bounded ≤25K token. Vedi ADR-0009.

---

## Componenti cross-cutting

### Audit log (`apps/server/audit.py`)

- SQLite append-only, location `~/.local/share/istefox-dt-mcp/audit.sqlite`
- Trigger SQL `BEFORE UPDATE` e `BEFORE DELETE` impediscono modifiche ex-post
- Schema: `audit_id, ts, principal, tool_name, input_json, output_hash, duration_ms, before_state, error_code`
- Hash output via SHA-256 su JSON sortato (deterministic)
- Retention configurabile (default 90 giorni — non ancora implementato)

### Cache (`libs/adapter/cache.py`)

- SQLite WAL, location `~/.local/share/istefox-dt-mcp/cache.sqlite`
- TTL per chiave (default 60s, override per categoria)
- `invalidate(key)`, `invalidate_prefix(prefix)`, `purge_expired()`
- Categorie attuali: `list_databases` (300s), `record:<uuid>` (invalidate on write)

### i18n (`apps/server/i18n.py`)

- Tool description, field doc, error code: **inglese** (LLM tool selection ottimizzata in EN)
- Messaggi user-facing (error_message + recovery_hint nell'envelope): **italiano** (locales/it.toml)
- Trigger: ogni `safe_call` failure → `Translator.message_it(code)` + `recovery_hint_it(code)`

### Logging (`apps/server/logging.py`)

- structlog → JSON su stderr (mai stdout)
- Schema: `{ts, level, event, tool, duration_ms, audit_id, error?}`
- Configurabile via `--log-level` (debug/info/warning/error)

---

## Decisioni rinviate (post-W2)

- **W3-W4**: Pydantic schemas extension, `ask_database` (BM25), structured logging refinement
- **W5-W6**: RAG same-process (ChromaDB + bge-m3), hybrid search, smart rule sync
- **W7**: `file_document` con dry_run, audit con before_state, undo
- **W8**: HTTP transport + OAuth (rinviato a v2 secondo decisione utente)
- **W9-W11**: Test strategy completa (Tier 2-3-4), OTel tracing, performance benchmark, packaging
- **W12**: `.mcpb` packaging, hardening, documentazione utente

Vedi [`docs/adr/REVIEW_ADR.md` §6](adr/REVIEW_ADR.md) per la roadmap revised.

---

## ADR consolidati (W1-W2)

| # | Titolo | Status |
|---|---|---|
| [0001](adr/0001-stack-python-fastmcp-chromadb.md) | Stack tecnologico | Accepted |
| [0002](adr/0002-bridge-architecture-jxa-only.md) | Bridge JXA-only v1 | Accepted |
| [0003](adr/0003-rag-same-process.md) | RAG same-process | Accepted (con spike) |
| [0004](adr/0004-mvp-tool-scope.md) | MVP 5 tool | Accepted |
| [0005](adr/0005-test-strategy-4-tier.md) | Test strategy 4-tier | Accepted (con spike) |
| [0006](adr/0006-oauth-scope-model.md) | OAuth scope model (3 scope + db-scoping in params) | Accepted |
| [0007](adr/0007-dt4-only.md) | DT4-only, drop DT3 | Accepted |
| [0008](adr/0008-embedding-model-selection.md) | Embedding model selection | Deferred (0.2.0) |

ADR-009 (vector DB migration), ADR-010 (distribution), ADR-011 (telemetry), ADR-012 (i18n), ADR-013 (concurrency), ADR-014 (rate limiting) → da scrivere alle settimane indicate in REVIEW_ADR §7.
