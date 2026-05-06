# handoff.md — istefox-dt-mcp

> Documento di passaggio tra sessioni di lavoro. Aggiornato a fine sessione.

---

## Snapshot sessione corrente

- **Data fine**: 2026-05-06
- **Branch**: `main` @ `ac65c60` (in sync con origin/main)
- **Output principale**: housekeeping post-release — fix avviso `SessionStart` hook del plugin `remember` (creata `.remember/{logs/autonomous,tmp}/` + ignorata in `.gitignore`). Sessione precedente: **v0.2.0 RILASCIATA** (GitHub Release + MCP Registry).

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

### Test status
- 202 unit + 8 contract test pass (210 totali)
- 7 integration test (skip default, richiedono DT live)
- CI Ubuntu (lint + mypy + unit + contract) e macOS-14 (import-and-bundle): pass

---

## Roadmap 0.3.0+

Tutti spostati da 0.2.0 in attesa di trigger esterni o cicli dedicati.

| Item | Stato | Note |
|---|---|---|
| **RAG benchmark cross-corpus** | ⏸️ bloccato | Aspetta early adopter (3+ corpus diversi). Criterio per flippare default `bge-m3` (ADR-008). |
| **HTTP transport + OAuth multi-device** | ⏸️ ADR-006 da finalizzare | Lavoro sostanziale (~2 settimane). Probabile target 0.3.0. |
| **`create_smart_rule`** | ⏸️ DEFERRED | Issue #47 — gap nello SDK DT4. Niente da fare lato nostro finché DT4 non aggiorna la dictionary. |
| **Per-op drift detection per `bulk_apply` undo** | ⏸️ schema upgrade | Audit log schema bump. Probabile target 0.3.0. |

---

## Cose da fare prossima sessione

Opzioni in ordine di pragmaticità:

1. **Annuncio v0.2.0** via Reddit / forum DEVONthink / HN (vedi `feedback_community_post_style.md` in memory per lo stile asciutto).
2. **Bug fix gotcha publish-registry**: il workflow non auto-triggera sul tag pushato da release.yml (GH Actions GITHUB_TOKEN limit). Fix: usare PAT in release.yml. Workaround attuale: trigger manuale documentato in `release_workflow.md`.
3. **Picking up un item della roadmap 0.3.0** — più trattabile probabilmente HTTP transport, ma è ~2 settimane.

---

## Stato repo locale

```
~/Developer/Devonthink_MCP/
├── main branch @ ac65c60 (in sync con origin/main, working tree pulito)
├── tag v0.2.0 pushato (2026-05-05)
└── 0 stale branches (cleanup automatico post-merge)
```

`git log --oneline -5`:
```
ac65c60 chore: ignore .remember/ plugin state directory
33f8994 docs: handoff.md post-release v0.2.0 + memory note publish-registry manual
14883d6 chore: release v0.2.0 (#61)
7d78269 docs: refresh README + CHANGELOG + handoff post-cassette-VCR milestone
4792529 feat(cassette-vcr): land real-data cassettes + auto-reset recording (#60)
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
git log --oneline -5     # → ultimo commit PR #60
uv run pytest tests/ -q  # → 210 pass, 7 deselected
```

Re-cattura cassette (se mai serve):
```bash
# Su Mac, DT4 + fixtures-dt-mcp aperto
uv run istefox-dt-mcp record-cassette --all
# Output: ↩ reset: moved=N retagged=N ... + 6× ✅ wrote ...
```
