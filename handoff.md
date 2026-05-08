# handoff.md — istefox-dt-mcp

> Documento di passaggio tra sessioni di lavoro. Aggiornato a fine sessione.

---

## Snapshot sessione corrente

- **Data fine**: 2026-05-08
- **Branch**: `main` @ `3dc3df9` (in sync con origin/main); tag `v0.3.0` pushato; **0.4.0 phase 1+2 in flight**
- **Output principale**: **ADR-006 finalizzato + Issue #63 chiusa + 0.4.0 phases 1-2 shipped (HTTP transport + scope plumbing) + smoke esteso a HTTP**.
  - `fb5c028` — **ADR-006 OAuth scope model** (Accepted): 3 scope, database-scoping server-side, RECONSENT_REQUIRED.
  - `2c2eeea` + `6a0599c` — **Issue #63 CHIUSA**: integration test PASSED 10.85s live.
  - `c3e8e74` — **0.4.0 spec + plan** in `docs/superpowers/{specs,plans}/2026-05-08-http-transport-oauth*.md`. Lavoro fasato in 5 PR (~2 settimane).
  - `860225c` — **Phase 1**: HTTP streamable transport via uvicorn. CLI `--transport http --host --port`. Smoke E2E Step 6 verifica HTTP lifecycle. 6 nuovi unit test (228 totali).
  - `3dc3df9` — **Phase 2**: scope enforcement plumbing (Scope enum, RequestContext contextvar, ScopeMiddleware, safe_call gate). Tutti i 7 tool decorati con `required_scope` (READ/WRITE). HTTP usa header `X-Istefox-Scope` (testing stub fino a phase 4). 11 nuovi unit test (239 totali).
  - Smoke E2E PASS — 6/6 step (era 5/5), incluso HTTP transport.
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
- **GitHub Releases**: `v0.3.0` (2026-05-06) — bundle .mcpb 305 KB, sha256 `b54ebeb96dd198cbf60638e25ceac2a3efc6cbe8f8cc665a879f94983ad571f3`
- **MCP Registry**: `io.github.istefox/dt-mcp` v0.3.0 (registry mostra tutte 0.1.0 + 0.2.0 + 0.3.0)
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

### Test status (0.4.0 phase 2 baseline)
- 231 unit + 8 contract test pass (239 totali) — era 222
- 8 integration test (skip default); round-trip drift di #63 verificato live PASS in 10.85s
- mypy + ruff + black: clean (mypy gate `apps libs`)
- CI Ubuntu (lint + mypy + unit + contract) e macOS-14 (import-and-bundle): pass
- Smoke E2E pre-release PASS — 6/6 step (incluso nuovo Step 6 HTTP transport)

---

## Roadmap 0.4.0+

| Item | Stato | Note |
|---|---|---|
| **RAG benchmark cross-corpus** | ⏸️ bloccato | Aspetta early adopter (3+ corpus diversi). Criterio per flippare default `bge-m3` (ADR-008). |
| **HTTP transport + OAuth multi-device (0.4.0)** | 🟡 in flight 2/5 phases | Spec+plan in `docs/superpowers/`. Phase 1 (HTTP transport) ✅ `860225c`. Phase 2 (scope plumbing) ✅ `3dc3df9`. Resta phase 3 (ConsentStore), 4 (OAuth flow + consent UI), 5 (integration tests + release). |
| **`create_smart_rule`** | ⏸️ DEFERRED | Issue #47 — gap nello SDK DT4. Niente da fare lato nostro finché DT4 non aggiorna la dictionary. |
| **Integration test per `bulk_apply` undo drift** | ✅ DONE | Issue #63 chiusa 2026-05-08. Test PASS in 10.85s live. |
| **Fixture stability** | 🟡 noto | `Sample Second PDF` mancante in `fixtures-dt-mcp` (probabilmente da test residuo). Re-seed con `uv run python scripts/setup_test_database.py` quando necessario; il fixture `fixtures_db_inbox_records` skip se <3 record in /Inbox. |

---

## Cose da fare prossima sessione

Opzioni in ordine di pragmaticità (allineate alla roadmap 0.4.0):

1. **Phase 3 — ConsentStore** (più tractable, ~300 LOC): SQLite `consent` table (principal_id, database_uuid, granted_at), `Deps.consent` field, `filter_visible` integrato in `list_databases`, pre-flight `check_or_raise` in `safe_call` per write tools, errore `RECONSENT_REQUIRED`. Plan task 3.1-3.6 in `docs/superpowers/plans/2026-05-08-http-transport-oauth.md`.
2. **Phase 4 — OAuth flow + consent UI** (~600 LOC, più sostanziosa): authlib + jinja2 → `auth/oauth.py` (PKCE, JWT signing), `auth/consent_ui.py` (template HTML), routes `/oauth/authorize` + `/oauth/token`, sostituire header stub con bearer token validation. Aggiungere deps `authlib>=1.3` + `jinja2>=3.1` (già nell'extra `[http-oauth]`). Eventuale ADR-015 per callback URL design (Cloudflare Tunnel vs loopback).
3. **Phase 5 — Integration tests + release** (~300 LOC): test E2E del flow PKCE live, smoke esteso con auth header, README + CHANGELOG, bump 0.4.0, release workflow.
4. **Postare l'annuncio v0.3.0** se si vuole interrompere la roadmap 0.4.0 — bozza in `docs/announcements/0.3.0.md`.

Nota fixture: prima di lanciare `tests/integration/test_undo_bulk_apply_drift_live.py` re-seed con `uv run python scripts/setup_test_database.py` per ripristinare i 4 record /Inbox di `fixtures-dt-mcp` (Sample Second PDF è mancante).

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
git log --oneline -5     # → ultimo commit PR #64
uv run pytest tests/ -q  # → 222 pass (214 unit + 8 contract), 8 deselected
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
