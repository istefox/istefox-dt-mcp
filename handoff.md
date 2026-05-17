# handoff.md — istefox-dt-mcp

> Documento di passaggio tra sessioni di lavoro. Aggiornato a fine sessione.

---

## Snapshot sessione corrente

- **Data fine**: 2026-05-17
- **Branch**: `main` @ `aad4361` (in sync con origin/main). Tag `v0.5.0` **e** `v0.5.1` pushati — **entrambe le release RILASCIATE end-to-end**.
- **Output principale**: **0.5.0 + 0.5.1 RILASCIATE.**
  - **0.5.0 — protocol-completeness** (PR #67, merge `05288e1`): MCP Resources + Prompts (ADR-0009): 3 resource read-only `dt://databases`, `dt://record/{uuid}/metadata`, `dt://record/{uuid}/text` (deterministiche, bounded ≤25K token, consent-gated via `safe_resource` che *solleva* `ResourceError` italiano, NON envelope) + 2 prompt template-only `weekly_review`, `triage_inbox`. **Zero nuove dipendenze, zero nuovi JXA**, `contract.py`/adapter intatti. Sviluppata subagent-driven in 5 slice (TDD + doppia review per slice + review whole-feature). Fix post-review inclusi: structlog parity in `safe_resource` + `ResourceError` localizzato; tag metadata ordinati (determinismo G2); §2.2 token-bound irrigidito (`RESOURCE_JSON_BUDGET_CHARS=60_000`).
  - **0.5.1 — patch** (PR #68, merge `aad4361`): `fix(packaging)` issue **#66 CLOSED**. Rimosso il `force-include` ridondante di `locales/it.toml` in `apps/server/pyproject.toml`: creava `site-packages/istefox_dt_mcp_server/` senza `__init__.py` (namespace-shadow PEP 420) che poteva oscurare il package editable `.pth`. `packages=["src/istefox_dt_mcp_server"]` spedisce già i locale nel wheel (verificato con build). + regression test `tests/unit/test_packaging.py`. Nota: su Py3.13 lo shadow era latente (shim bare funzionava); reporter su Py3.14 fallimento attivo.
  - Pipeline: `release.yml` → tag → `publish-registry.yml` **auto-chain via RELEASE_PAT** OK per entrambe. MCP Registry mostra 0.1.0 → **0.5.1**.
  - Test: **324 unit+contract green**, mypy + ruff + black clean; integration test live `test_resources_live.py` PASS su DT reale.
- **Cosa MANCA**: nessuna azione bloccante. Vedi "Cose da fare".

---

## Snapshot sessione precedente (0.4.0 release)

- **Data fine**: 2026-05-08
- **Branch**: `main` @ `3529cc4` (in sync con origin/main); **tag `v0.4.0` pushato — release 0.4.0 RILASCIATA end-to-end**
- **Output principale**: **0.4.0 RILASCIATA**: HTTP transport + OAuth 2.1 PKCE multi-device + scope enforcement + ConsentStore + integration tests live + release polish. Tutte 5 fasi del plan complete.
  - `fb5c028` — **ADR-006 OAuth scope model** (Accepted): 3 scope, database-scoping server-side, RECONSENT_REQUIRED.
  - `2c2eeea` + `6a0599c` — **Issue #63 CHIUSA**: integration test PASSED 10.85s live.
  - `c3e8e74` — **0.4.0 spec + plan** in `docs/superpowers/{specs,plans}/2026-05-08-http-transport-oauth*.md`. Lavoro fasato in 5 PR (~2 settimane).
  - `860225c` — **Phase 1**: HTTP streamable transport via uvicorn. CLI `--transport http --host --port`. Smoke E2E Step 6 verifica HTTP lifecycle. 6 nuovi unit test (228 totali).
  - `3dc3df9` — **Phase 2**: scope enforcement plumbing (Scope enum, RequestContext contextvar, ScopeMiddleware, safe_call gate). Tutti i 7 tool decorati con `required_scope` (READ/WRITE). HTTP usa header `X-Istefox-Scope` (testing stub fino a phase 4). 11 nuovi unit test (239 totali).
  - `b65c5a1` — **Phase 3**: ConsentStore SQLite + per-DB authorization. `get_record.js` ritorna `database_uuid`; `list_databases` filtrato; write tools (`file_document`/`bulk_apply`) fanno pre-flight consent check. Nuovo error code `RECONSENT_REQUIRED`. 20 nuovi unit test (259 totali).
  - `0c1364d` — **Phase 4** (sessione 2026-05-09): full OAuth 2.1 + PKCE flow. Nuovi `auth/oauth.py` (OAuthSecret 32B HMAC con perms 0600, JWTIssuer HS256 via joserfc, AuthCodeStore SQLite one-shot, verify_pkce_s256), `auth/consent_ui.py` (Jinja2 inline template), `auth/routes.py` (GET /oauth/authorize, POST /oauth/consent, POST /oauth/token montati via `mcp.custom_route`). `ScopeMiddleware` ora valida `Authorization: Bearer <jwt>` (con `X-Istefox-Scope` come fallback testing). Deps esteso con `jwt_issuer` + `auth_codes`. authlib + joserfc + jinja2 promosse a required deps. Verifica live: `/oauth/authorize` HTTP 200, `/oauth/token` rifiuta codici fasulli con OAuth-spec invalid_grant envelope. 35 nuovi unit/contract test (294 totali).
  - `90ab53d` — **Phase 5 tests**: 3 integration test live (`test_http_transport_oauth_live.py`) — full PKCE round-trip su uvicorn reale verificato PASS. Smoke E2E Step 7 (OAuth surface).
  - `3529cc4` — **chore: release v0.4.0**: bump `SERVER_VERSION` + `manifest.json` a 0.4.0; CHANGELOG + README + `architecture.md` aggiornati con HTTP/OAuth setup, layer diagram esteso (Tier 2-3 Auth), sequence diagram PKCE.
  - **Pipeline release end-to-end**: `gh workflow run release.yml -f version=0.4.0` → tag `v0.4.0` (44s) → auto-trigger `publish-registry.yml` (9s) → bundle `istefox-dt-mcp-0.4.0.mcpb` (332 KB, sha256 `a0c6f45e9448e98732d0003d075a4f88d8dcc4886e6cf2b9e4a84aa28d0b7ade`) live su GitHub Releases + MCP Registry mostra v0.4.0.
  - Smoke E2E PASS — 7/7 step (incluso HTTP + OAuth).
  - PR #41 (`docs/glama-listing-and-cross-link`) chiusa come superseded — il contenuto (Glama badge + cross-link `obsidian-mcp-connector`) era già in main via `7d78269` e `787033e`. Verificato in rebase: branch identico a main dopo conflict resolution.
  - Eliminati 5 stale branches locali; `feat/create-smart-rule` pushato su origin per preservare `ee9317f docs(jxa): empirical discovery of DT4 smart rule scripting` (riferimento per quando Issue #47 sarà sbloccata).
- **Sessione precedente (2026-05-06)**: **v0.3.0 RILASCIATA** — primo end-to-end test dell'auto-trigger (PR #62) riuscito.
  - **#62** (`ca0983c`): release.yml usa `RELEASE_PAT` per auto-triggerare `publish-registry.yml`
  - **#64** (`feac516`): per-op drift detection 3-state in `bulk_apply` undo, con `force` honoring
  - **#65** (`442ef06`): chore release v0.3.0 (bump + CHANGELOG)
  - Release workflow + publish-registry workflow eseguiti in chain in **44 secondi** totali (no manual dispatch). Bundle .mcpb 305 KB sha256 `b54ebeb9...`. Registry `io.github.istefox/dt-mcp` mostra tutte le 3 versioni.
  - Memory `release_workflow.md` + `project_status_v0_1_0.md` aggiornate
  - Spec + plan committati in `docs/superpowers/{specs,plans}/`

---

## Stato corrente del progetto

### Versione live
- **GitHub Releases**: `v0.5.1` (2026-05-17) — bundle `istefox-dt-mcp-0.5.1.mcpb` (~340 KB, sha256 `2914354d5568ea89c501f3987a34d6b64b4b1f82a39477733132d14932dc4d70`)
- **MCP Registry**: `io.github.istefox/dt-mcp` v0.5.1 (registry mostra 0.1.0 → 0.5.1)
- **Repo**: pubblico, MIT, solo `istefox` come contributor

### 0.2.0 — landed e rilasciata

PR mergiate da inizio 0.2.0 (ordine cronologico):

| PR | Topic |
|---|---|
| #43 | Drift detection 3-stati (no_drift/already_reverted/hostile_drift) per file_document undo |
| #45 | `summarize_topic` tool — server-side clustering retrieval (4 dimensioni) |
| #49 | Cassette VCR infrastructure (record-cassette CLI + sanitization + manifest + setup script + recording guide + invariant tests) |
| #50–#55 | fix `setup_test_database.py` + `record_cassette` (path, createDatabase null, createRecordWith, formatted note, parents off-by-one, _resolve_placeholder_uuids, move_record destination format) |
| #56 | fix record_cassette: cache_enabled=False (TTL SQLite cache short-circuita JXA) |
| #57 | fix sanitizer: split DB vs record name maps + manifest system_databases |
| #58 | fix sanitizer: trailing-slash path + UUID rewrite in reference_url |
| #59 | fix sanitizer: real_uuid_map per riscrivere argv + stdout text-level |
| #60 | feat(cassette-vcr): cassette reali da fixtures-dt-mcp + auto-reset recording + invariant relax + assertion rewrite |
| #61 | chore: release v0.2.0 (version bump + CHANGELOG dated) |

### 0.3.0 — landed e rilasciata

| PR | Topic |
|---|---|
| #62 | chore(ci): release.yml usa RELEASE_PAT per auto-triggerare publish-registry.yml |
| #64 | feat(undo): per-op drift detection 3-state in bulk_apply undo (12 commit, +722/-46) |
| #65 | chore: release v0.3.0 (version bump + CHANGELOG dated) |

Follow-up issues aperte: nessuna. (Issue #63 chiusa 2026-05-08 dopo run live verde.)

### 0.5.0 + 0.5.1 — landed e rilasciate (2026-05-17)

| PR | Topic |
|---|---|
| #67 | feat: MCP Resources + Prompts (0.5.0 protocol-completeness) — 3 `dt://` resource + 2 prompt, ADR-0009, `safe_resource`; subagent-driven 5-slice + fix post-review (structlog parity, ResourceError IT, tag determinism, §2.2 bound) — merge `05288e1` |
| #68 | fix(packaging): drop locales `force-include` shadowing editable package (#66) + `chore: release v0.5.1` + regression test `tests/unit/test_packaging.py` — merge `aad4361` |

Issue **#66 CLOSED** (via PR #68). Bundle 0.5.1 sha256 `2914354d5568ea89c501f3987a34d6b64b4b1f82a39477733132d14932dc4d70`. Suite a 324 unit+contract.

### Test status (0.4.0 phase 4 baseline)
- 286 unit + 8 contract test pass (294 totali) — era 222 a inizio 0.4.0
- 8 integration test (skip default); round-trip drift di #63 verificato live PASS in 10.85s
- mypy + ruff + black: clean (mypy gate `apps libs`)
- CI Ubuntu (lint + mypy + unit + contract) e macOS-14 (import-and-bundle): pass
- Smoke E2E pre-release PASS — 6/6 step (incluso nuovo Step 6 HTTP transport)
- OAuth flow live verificato manualmente: `/oauth/authorize` GET HTTP 200 (consent HTML), `/oauth/token` POST con bad code → invalid_grant JSON

---

## Roadmap 0.4.0+

| Item | Stato | Note |
|---|---|---|
| **RAG benchmark cross-corpus** | ⏸️ bloccato | Aspetta early adopter (3+ corpus diversi). Criterio per flippare default `bge-m3` (ADR-008). |
| **HTTP transport + OAuth multi-device (0.4.0)** | ✅ DONE | Tutte 5 fasi shipped. Tag `v0.4.0` live su GitHub + MCP Registry. |
| **`create_smart_rule`** | ⏸️ DEFERRED | Issue #47 — gap nello SDK DT4. Niente da fare lato nostro finché DT4 non aggiorna la dictionary. |
| **Integration test per `bulk_apply` undo drift** | ✅ DONE | Issue #63 chiusa 2026-05-08. Test PASS in 10.85s live. |
| **Fixture stability** | 🟡 noto | `Sample Second PDF` mancante in `fixtures-dt-mcp` (probabilmente da test residuo). Re-seed con `uv run python scripts/setup_test_database.py` quando necessario; il fixture `fixtures_db_inbox_records` skip se <3 record in /Inbox. |

---

## Cose da fare prossima sessione

0.5.0 + 0.5.1 rilasciate, #66 chiusa. Opzioni in ordine di valore:

1. **Annuncio 0.5.0** — release sostanziosa (MCP Resources + Prompts: il plugin diventa cittadino MCP completo). Vale un post: r/devonthink (reply/nuovo thread), forum DEVONtechnologies subforum "AI", eventualmente HN/Reddit MCP. Riusare il pattern stile community confermato (vedi auto-memory `feedback_community_post_style`). 0.5.1 è un patch — citarlo solo come nota.
2. **Smart rule (#47)** — ancora DEFERRED. Niente da fare lato nostro finché DT4 non aggiorna lo SDK; se DT4 5.0 esce con la dictionary completa, potrebbe sbloccarsi.
3. **RAG benchmark cross-corpus (ADR-008)** — bloccato in attesa di early adopter. Più probabile attirare adopter ora che HTTP+Resources abilitano l'uso remoto.
4. **Token refresh + key rotation** — gap noto: l'attuale modello richiede re-consent ogni ora e secret rotation manuale. Candidato 0.6.0.
5. **Multi-tenancy reale (post-v1)** — richiede un layer di login a monte; per ora `principal_id=oauth-user` hardcoded.

Note operative correnti:
- **Fixture**: prima di lanciare `test_undo_bulk_apply_drift_live.py` re-seed con `uv run python scripts/setup_test_database.py` (Sample Second PDF è mancante in fixtures-dt-mcp).
- **OAuth secret rotation**: cancella `~/.local/share/istefox-dt-mcp/oauth_secret` + restart → tutti i token in volo invalidi.
- **Consent revoca**: `deps.consent.revoke_all(principal_id)` o cancella `consent.sqlite`.

---

## Stato repo locale

```
~/Developer/Devonthink_MCP/
├── main branch in sync con origin/main, working tree pulito
├── tag v0.3.0 pushato (2026-05-06) — release attuale
├── secret RELEASE_PAT settato (90gg, expire ≈ 2026-08-04)
└── branch locali: main + feat/create-smart-rule (DEFERRED Issue #47, preservato su origin)
```

Branch cleanup (sessione 2026-05-08): chiusa PR #41 stale (Glama badge — superseded, contenuto già in main via `7d78269`); eliminati 5 stale branches locali (`docs/glama-listing-and-cross-link`, `spec/cassette-vcr-real-data`, `spec/summarize-topic`, `spec/create-smart-rule`, `spec/drift-detection-3-state`); `feat/create-smart-rule` pushato su origin per preservare doc empirical-discovery JXA (`ee9317f`).

Ultime PR (in ordine cronologico):
- `#62` — chore(ci): release.yml RELEASE_PAT (auto-trigger registry)
- `#64` — feat(undo): per-op drift detection in bulk_apply undo (3-state)
- `#65` — chore: release v0.3.0 (bump + CHANGELOG)

---

## Stato DT4 (Stefano's Mac)

- Database `fixtures-dt-mcp` aperto in `~/Databases/fixtures-dt-mcp.dtBase2` con 10 record + 3 group
- Database sistema `Inbox` aperto (always-on, gestito dal sanitizer come `system_databases`)
- `fixtures-dt-mcp` può essere lasciato in qualsiasi stato — `record-cassette --all` ora resetta automaticamente prima di catturare

---

## Per riprendere

```bash
cd ~/Developer/Devonthink_MCP
git status               # → working tree pulito
git log --oneline -5     # → ultimo merge PR #68 (aad4361)
uv run pytest tests/unit tests/contract -q  # → 324 pass, integration/benchmark deselected
```

Re-cattura cassette (se mai serve):
```bash
# Su Mac, DT4 + fixtures-dt-mcp aperto
uv run istefox-dt-mcp record-cassette --all
# Output: ↩ reset: moved=N retagged=N ... + 6× ✅ wrote ...
```

Spec + plan delle ultime due feature (per future reference):
- `docs/superpowers/specs/2026-05-06-publish-registry-pat-design.md` + plan omonimo
- `docs/superpowers/specs/2026-05-06-bulk-apply-drift-detection-design.md` + plan omonimo
