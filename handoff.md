# handoff.md — istefox-dt-mcp

> Documento di passaggio tra sessioni di lavoro. Aggiornato a fine sessione.

---

## Snapshot sessione corrente

- **Data fine**: 2026-05-06
- **Branch**: `main` @ `feac516` (in sync con origin/main)
- **Output principale**: due PR landed via subagent-driven-development —
  - **#62** (`ca0983c`): release.yml usa `RELEASE_PAT` per auto-triggerare `publish-registry.yml` (eliminato manual second-dispatch)
  - **#64** (`feac516`): per-op drift detection 3-state in `bulk_apply` undo, con `force` honoring per `hostile_drift`. 12 commit, ~600 righe diff, 12 nuovi unit test (214 totali)
  - Memory `release_workflow.md` aggiornato per riflettere auto-trigger + sezione PAT lifecycle
  - Spec + plan committati in `docs/superpowers/{specs,plans}/`

---

## Stato corrente del progetto

### Versione live
- **GitHub Releases**: `v0.2.0` (2026-05-05) — bundle .mcpb 311 KB, sha256 `a6084cce...`
- **MCP Registry**: `io.github.istefox/dt-mcp` v0.2.0 (registry mostra entrambe 0.1.0 + 0.2.0)
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

### Post-0.2.0 (Unreleased — destinato a 0.3.0)

| PR | Topic |
|---|---|
| #62 | chore(ci): release.yml usa RELEASE_PAT per auto-triggerare publish-registry.yml (eliminato manual second-dispatch) |
| #64 | feat(undo): per-op drift detection 3-state in bulk_apply undo (no_drift / already_reverted / hostile_drift + force) — 12 commit, +722/-46 righe, 12 nuovi unit test |

Follow-up issues aperte:
- **#63**: flesh out integration test per `bulk_apply` undo drift (stub committato in #64)

### Test status
- 214 unit + 8 contract test pass (222 totali) — era 210
- 7+1 integration test (skip default; +1 stub da #64)
- mypy + ruff + black: clean
- CI Ubuntu (lint + mypy + unit + contract) e macOS-14 (import-and-bundle): pass

---

## Roadmap 0.3.0+

| Item | Stato | Note |
|---|---|---|
| **Per-op drift detection per `bulk_apply` undo** | ✅ landed (#64) | Mergiato 2026-05-06. Schema additivo (`per_op_snapshots`), backward compat. |
| **RAG benchmark cross-corpus** | ⏸️ bloccato | Aspetta early adopter (3+ corpus diversi). Criterio per flippare default `bge-m3` (ADR-008). |
| **HTTP transport + OAuth multi-device** | ⏸️ ADR-006 da finalizzare | Lavoro sostanziale (~2 settimane). Probabile target 0.3.0. |
| **`create_smart_rule`** | ⏸️ DEFERRED | Issue #47 — gap nello SDK DT4. Niente da fare lato nostro finché DT4 non aggiorna la dictionary. |
| **Integration test per `bulk_apply` undo drift** | ⏸️ stub committato | Issue #63 — serve wiring `integration_deps` + tool-call helper + DT live setup. |

---

## Cose da fare prossima sessione

Opzioni in ordine di pragmaticità:

1. **Release 0.3.0** — la sezione `[Unreleased]` di `CHANGELOG.md` ha contenuto sostanziale (drift detection bulk_apply). Procedura standard via `release_workflow.md`. Ora con auto-trigger publish-registry funzionante (PR #62), basta `gh workflow run release.yml`. PAT scade ≈ 2026-08-04 (90gg).
2. **Annuncio v0.2.0/0.3.0** via Reddit / forum DEVONthink / HN (vedi `feedback_community_post_style.md` in memory per lo stile asciutto).
3. **Picking up un item della roadmap 0.3.0+** — più trattabile probabilmente HTTP transport (ADR-006), ma è ~2 settimane.

---

## Stato repo locale

```
~/Developer/Devonthink_MCP/
├── main branch @ feac516 (in sync con origin/main, working tree pulito)
├── tag v0.2.0 pushato (2026-05-05) — release attuale
├── secret RELEASE_PAT settato (90gg, expire ≈ 2026-08-04)
└── stale branches locali da pulire: docs/glama-listing-and-cross-link, feat/create-smart-rule, spec/cassette-vcr-real-data, spec/create-smart-rule, spec/drift-detection-3-state [gone], spec/summarize-topic
```

`git log --oneline -5`:
```
feac516 feat(undo): per-op drift detection in bulk_apply undo (3-state) (#64)
ca0983c chore(ci): release.yml uses RELEASE_PAT for auto-trigger of publish-registry (#62)
428d1d9 docs: implementation plans — publish-registry PAT + bulk_apply drift detection
da32c58 docs: spec — publish-registry PAT + bulk_apply per-op drift detection
af231cd docs: handoff.md aggiornato — fix .remember/ hook log dir
```

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

Cleanup stale branches locali (opzionale):
```bash
git branch -d docs/glama-listing-and-cross-link feat/create-smart-rule \
              spec/cassette-vcr-real-data spec/create-smart-rule \
              spec/drift-detection-3-state spec/summarize-topic
git fetch -p
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
