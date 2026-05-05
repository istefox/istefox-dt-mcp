# handoff.md — istefox-dt-mcp

> Documento di passaggio tra sessioni di lavoro. Aggiornato a fine sessione.

---

## Snapshot sessione corrente

- **Data fine**: 2026-05-05 sera
- **Branch**: `main` @ `4792529` (in sync con origin/main)
- **Output principale**: milestone "cassette VCR real-data" CHIUSA con PR #60. 0.2.0 entra in fase di stabilizzazione (3 item rimanenti, tutti opzionali/lunghi).

---

## Stato corrente del progetto

### Versione live
- **GitHub Releases**: `v0.1.0` (2026-05-02, ancora attuale)
- **MCP Registry**: `io.github.istefox/dt-mcp` v0.1.0
- **Repo**: pubblico, MIT, solo `istefox` come contributor

### 0.2.0 in corso — landed in main

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

### Test status
- 202 unit + 8 contract test pass (210 totali)
- 7 integration test (skip default, richiedono DT live)
- CI Ubuntu (lint + mypy + unit + contract) e macOS-14 (import-and-bundle): pass

---

## 0.2.0 roadmap rimanente

Tutto opzionale o pesante. Nessuno è blocker per release.

| Item | Stato | Note |
|---|---|---|
| **RAG benchmark cross-corpus** | ⏸️ bloccato | Aspetta early adopter (3+ corpus diversi). Criterio per flippare default `bge-m3` (ADR-008). |
| **HTTP transport + OAuth multi-device** | ⏸️ ADR-006 da finalizzare | Lavoro sostanziale (~2 settimane). Differibile a 0.3.0. |
| **`create_smart_rule`** | ⏸️ DEFERRED | Issue #47 — gap nello SDK DT4. Niente da fare lato nostro finché DT4 non aggiorna la dictionary. |
| **Per-op drift detection per `bulk_apply` undo** | ⏸️ schema upgrade | Audit log schema bump. Differibile a 0.3.0. |

**Possibilità per chiudere 0.2.0 ora**: rilasciare `v0.2.0` con quello che già c'è (summarize_topic + drift 3-state + cassette VCR real-data) e spostare gli item rimanenti a 0.3.0. Da decidere.

---

## Cose da fare prossima sessione

Tre opzioni in ordine di pragmaticità:

1. **Tag e release `v0.2.0`** con quello che è in main. Prep release notes da CHANGELOG `[Unreleased]`, `gh workflow run release.yml`, publish-registry auto-triggera. Tempo: ~30 min. Vedi `release_workflow.md` in memory.
2. **Annuncio progresso 0.2.0** via GitHub Discussion / issue / Reddit post (vedi `feedback_community_post_style.md` in memory per lo stile).
3. **Picking up un item della roadmap** — il più trattabile è probabilmente l'HTTP transport, ma è ~2 settimane.

---

## Stato repo locale

```
~/Developer/Devonthink_MCP/
├── main branch @ 4792529 (in sync con origin/main, working tree pulito)
└── 0 stale branches (cleanup automatico post-merge)
```

`git log --oneline -5`:
```
4792529 feat(cassette-vcr): land real-data cassettes + auto-reset recording (#60)
f64d86a docs: handoff.md aggiornato — cassette VCR real-data progress
4dbc983 fix(sanitizer): rewrite real DT UUIDs in argv via real_uuid_map (#59)
db04074 fix(sanitizer): match trailing-slash paths + rewrite UUIDs in reference_url (#58)
f4b9b08 fix(sanitizer): split DB and record name maps to handle DT4 system Inbox (#57)
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
