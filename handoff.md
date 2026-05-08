# handoff.md — istefox-dt-mcp

> Documento di passaggio tra sessioni di lavoro. Aggiornato a fine sessione.

---

## Snapshot sessione corrente

- **Data fine**: 2026-05-08
- **Branch**: `main` @ `6a0599c` (in sync con origin/main); tag `v0.3.0` pushato
- **Output principale**: **ADR-006 finalizzato + Issue #63 chiusa (live run verde) + smoke pass + branch cleanup**.
  - `fb5c028` — **ADR-006 OAuth scope model** (Accepted): 3 scope (`dt:read`, `dt:write`, `dt:admin`) + database-scoping persistito server-side fuori dal token OAuth, errori `RECONSENT_REQUIRED` per database creati post-consent. Implementazione rinviata a 0.4.0 con HTTP transport.
  - `2c2eeea` + `6a0599c` — **Issue #63 CHIUSA**: integration test `test_bulk_apply_undo_drift_round_trip` PASSED in 10.85s live (DT4 + fixtures-dt-mcp). Nuove fixture `live_deps`/`mcp_server`/`fixtures_db_inbox_records`, round-trip end-to-end (3-op bulk_apply → 3 mutazioni esterne → undo dry-run con/senza force) + cleanup try/finally. Fix `6a0599c`: tolerance su trailing-slash (DT4 ritorna `/Inbox/`).
  - Smoke E2E (`scripts/smoke_e2e.sh`) PASS — 4/5 step ok, solo warn su `.mcpb` non rebuilded (atteso pre-tag).
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

### Test status
- 214 unit + 8 contract test pass (222 totali)
- 8 integration test (skip default); round-trip drift di #63 verificato live PASS in 10.85s
- mypy + ruff + black: clean
- CI Ubuntu (lint + mypy + unit + contract) e macOS-14 (import-and-bundle): pass
- Smoke E2E pre-release PASS (4/5 step ok, warn solo su `.mcpb` non rebuilded)

---

## Roadmap 0.4.0+

| Item | Stato | Note |
|---|---|---|
| **RAG benchmark cross-corpus** | ⏸️ bloccato | Aspetta early adopter (3+ corpus diversi). Criterio per flippare default `bge-m3` (ADR-008). |
| **HTTP transport + OAuth multi-device** | 🟢 ADR-006 Accepted | Decisione OAuth scope formalizzata in `0006-oauth-scope-model.md`. Implementazione (~2 settimane) target 0.4.0 — apre lavoro su transport, callback URL, consent UI, ConsentStore. |
| **`create_smart_rule`** | ⏸️ DEFERRED | Issue #47 — gap nello SDK DT4. Niente da fare lato nostro finché DT4 non aggiorna la dictionary. |
| **Integration test per `bulk_apply` undo drift** | ✅ DONE | Issue #63 chiusa 2026-05-08. Test PASS in 10.85s live. |

---

## Cose da fare prossima sessione

Opzioni in ordine di pragmaticità:

1. **Postare l'annuncio v0.3.0** — bozza completa già in `docs/announcements/0.3.0.md`. Per r/devonthink: **reply** al thread 0.2.0 esistente (variant ~80 parole, è una release additiva). Per forum DEVONtechnologies: standalone post (~190 parole).
2. **HTTP transport (target 0.4.0)** — ora che ADR-006 è Accepted: scaffold del transport (uvicorn + streamable-http), middleware di consent/scope check, OAuth callback design (loopback localhost vs Cloudflare Tunnel — open question da REVIEW_ADR §3 #12), `ConsentStore` SQLite, integration test multi-client. ~2 settimane.
3. **Note follow-up** sulla session 2026-05-08: nessun test integration in più richiesto sul write path (round-trip già coperto). Eventuale estensione: test analogo per `file_document` undo (3-state già coperto via unit, ma round-trip live mancante).

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
