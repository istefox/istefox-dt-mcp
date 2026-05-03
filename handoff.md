# handoff.md — istefox-dt-mcp

> Documento di passaggio tra sessioni di lavoro. Aggiornato a fine sessione.

---

## Snapshot sessione corrente

- **Data fine**: 2026-05-02
- **Output principale**: **release pubblica 0.1.0** + presenza su MCP Registry + repo public + contributors history pulita

---

## Stato corrente del progetto (2026-05-02)

**Versione live**: `v0.1.0` (rilasciata 2026-05-02 07:06 UTC)

### Distribuzione

- **GitHub Releases**: https://github.com/istefox/istefox-dt-mcp/releases/tag/v0.1.0
- **Bundle .mcpb**: `istefox-dt-mcp-0.1.0.mcpb` (293 KB, sha256 `ec0947840987071b6cf6ec445dcd8aeac62b5aba45530863fb1cbd9131a92bbb`)
- **MCP Registry**: `io.github.istefox/dt-mcp` v0.1.0 (LIVE su `registry.modelcontextprotocol.io`)
- **Repo**: https://github.com/istefox/istefox-dt-mcp — **PUBLIC**, MIT, 0 star/0 fork (appena pubblicato)

### Contributors

- **Solo `istefox`** (49 commit). Storia git ripulita 2026-05-02 con `git filter-repo` per rimuovere `Co-authored-by: Claude` da tutti i commit (case-insensitive — gotcha GitHub squash-merge usa lowercase).

### Test status

- 163 unit + contract test pass (157 unit + 6 contract)
- 7 integration test (skip default, `-m integration` per runarli, richiedono DT running + AppleEvents)
- macOS-14 GHA integration: 7 run total, mean 31.7s/run, costo budget = 0€ (public repo)

### CI/CD attivi

- `ci.yml` — ubuntu, lint+mypy+unit+contract on PR (success)
- `integration.yml` — macos-14, on-PR-of-relevant-paths + nightly cron (success, 7/7 skip clean senza DT)
- `release.yml` — workflow_dispatch, build .mcpb + tag + Release
- `publish-registry.yml` — push tag `v*` + workflow_dispatch, publish to MCP Registry via OIDC

---

## Cosa è stato fatto in questa sessione (2026-05-01 → 2026-05-02)

Sessione lunga ~10 ore divisa in 3 fasi.

### Fase 1 — Pre-0.1.0 polish (0.0.20 → 0.0.28)

15 PR di polish emersi da E2E testing reale (Stefano testava in Terminal.app vero su DT4 vero):

| PR | Cosa |
|---|---|
| #13 | Relicense MIT + housekeeping pre-0.1.0 |
| #14 | ADR-008 Deferred to 0.2.0 (RAG benchmark deferral) |
| #15 | `destination_hint` server-side validation |
| #16 | `list_databases` fast mode (`ISTEFOX_FAST_LIST_DATABASES`) |
| #17 | Bundle uv detection esteso (mise/asdf + `ISTEFOX_UV_BIN`) |
| #18 | Bump 0.0.21 + CHANGELOG |
| #19 | `user_config` MCPB → 4 env var configurabili da Claude Desktop UI |
| #20 | CLI `audit list --recent N` (recovery path per audit_id) |
| #21 | Undo `drift_details` per debug visibile |
| #22 | Tier 2-4 testing (cassettes + integration + smoke E2E) |
| #23 | README user-facing (rewrite italiano) |
| #24 | CI Step 3 — macOS integration workflow + real release pipeline |
| #25 | CI fix: black formatting + integration grep regex |
| #26 | Doctor 2-stage probe (-1743 detection) |
| #27 | `search_bm25` reference_url fallback + bench skip when disabled |
| #28 | `get_record` reference_url fallback + smoke step 3 audit query |
| #29 | Smoke step 5 hang fix (FIFO+fd3 → echo|server|head pipe) |

### Fase 2 — Release 0.1.0 (Step 8 del piano)

- PR #30: bump 0.0.28 → 0.1.0 + CHANGELOG entry "First public release"
- Trigger `gh workflow run release.yml -f version=0.1.0` → tag `v0.1.0` creato + GitHub Release pubblicata con `.mcpb` attached
- PR #31: `server.json` + `publish-registry.yml` workflow per MCP Registry
- PR #32: README tradotto in inglese + post-0.1.0 corrections
- PR #33: `server.json` description trim (≤100 chars per validation registry)
- Trigger `publish-registry.yml` → entry live su MCP Registry come `io.github.istefox/dt-mcp`

### Fase 3 — Cleanup post-release (2026-05-02)

- **Git history rewrite** con `git filter-repo` (case-insensitive!) per rimuovere `Co-authored-by: Claude` da TUTTI gli 82 commit. 2 round di force-push (primo round mancava i lowercase di GitHub squash-merge).
- Verify: contributors API ritorna solo `istefox` (49 commit).
- PR #34: `docs/assets/architecture.svg` + embed in README
- PR #35: SVG fix — sfondo bianco (era trasparente) + RAG label position no-overlap con Audit Log
- Cleanup: 32 branch locali stale eliminati, 18 bundle pre-0.1.0 rimossi da `dist/`, `.coverage` + `.DS_Store` puliti, backup branch eliminato
- Spike #9 "Costi CI macOS GHA" risolto: repo public → free unlimited, mean 31.7s/run

---

## Cose pendenti al riavvio

### Annunci pubblicati (2026-05-03)

1. **r/devonthink** — LIVE come `u/stefferri`, draft asciutto v2 (~200 parole, single-level bullets, **bold** invece di `##`). Monitorare commenti/feedback nelle 24-48h.
2. **discourse.devontechnologies.com** — LIVE in sub-categoria `DEVONthink → Artificial Intelligence` (NB: non `Automation`, scelta consapevole — l'audience AI è auto-selezionata sul tema MCP/LLM). Variante tecnica ~450 parole con 4 punti specifici di feedback richiesto (JXA edge cases, smart-rule patterns, mixed-language DBs, DT3 backcompat).
3. **`punkpeye/awesome-mcp-servers#5784`** — PR upstream OPEN + bot-validated (`check-submission: pass`, `mergeStateStatus: CLEAN`), in attesa di review del maintainer. Posizione alfabetica corretta in `🧠 Knowledge & Memory` tra `IgorGanapolsky` e `JamesANZ`. **Glama badge live + Glama release pubblicata** (build success in 14s su cache hit, instance logs confermano introspection completa: tools/list, prompts/list, resources/list).
4. **Glama directory** — LIVE su `glama.ai/mcp/servers/istefox/istefox-dt-mcp`, server claimed (badge "Official"), Dockerfile config validato (debian:trixie-slim + Python 3.12 + uv + mcp-proxy stdio). Score iniziale `A-B`.
5. **Repo Dockerfile** (`a2b8af2`) — non strettamente necessario per Glama (loro generano il proprio), ma utile collateralmente per CI futuri / sviluppo isolato. Lasciato in repo.

### Annunci ancora da fare (opzionali)

- **Bluesky / X** — versione 280 char con link repo + 1 GIF. Hashtag `#mcp #devonthink #claudeai`. Boost low-medium.
- **LinkedIn** — taglio "lessons learned tecnici" (clean-room, packaging `.mcpb`, JXA gotchas). Brand professionale, opzionale.

### Cose da monitorare

- Risposte Reddit + forum DT nelle 12-48h → triage in issue/feature request se pertinenti
- PR #5784 `awesome-mcp-servers` → potrebbe richiedere giorni-settimana, niente da fare oltre rispondere a eventuali commenti di review

### 0.2.0 roadmap (vedi CHANGELOG sezione Unreleased)

- ✅ **Drift detection 3-stati** (`no_drift` / `already_reverted` / `hostile_drift`) per ridurre falsi positivi `--force` — landed in PR #43 (commit `247141e`, 2026-05-03). Spec + plan sotto `docs/superpowers/specs/` e `docs/superpowers/plans/`. Scope: `file_document` undo. Bulk_apply lasciato a 0.3.0+.
- RAG benchmark cross-corpus (≥3 corpus, ≥2 early adopter) + flip default modello (ADR-008)
- HTTP transport + OAuth multi-device (ADR-006)
- Tool aggiuntivi: `summarize_topic`, `create_smart_rule`
- Cassette VCR catturate da DT vivo (oggi sintetiche ma matching shape)
- Per-op drift detection per `bulk_apply` undo (richiede schema upgrade audit log per per-op after-snapshots)

---

## Stato repo locale al riavvio

```
~/Developer/Devonthink_MCP/
├── main branch (in sync con origin/main)
├── 0 stale branches (cleanup fatto)
├── dist/istefox-dt-mcp-0.1.0.mcpb (1 file, 293 KB)
└── working tree clean
```

`git status` → clean. `git log --oneline -3`:
```
PR #35 fix(architecture.svg): white background + RAG label no longer overlaps Audit Log
PR #34 docs: add architecture.svg + embed in README
PR #33 fix(registry): trim server.json description to ≤100 chars
```

---

## Riferimenti per il prossimo pickup

- **CHANGELOG.md** — full history versione per versione, sezione `[Unreleased]` lista i pending per 0.2.0
- **README.md** — aggiornato in inglese, badge v0.1.0, troubleshooting top 5
- **server.json** + **manifest.json** — both at version 0.1.0, license MIT
- **scripts/smoke_e2e.sh** — Tier 4 smoke pre-tag, 5 step verdi su 5 (validato 2026-05-02 in Terminal.app)
- **tests/integration/README.md** — istruzioni run integration su DT vivo
- **docs/adr/0008-embedding-model-selection.md** — status Deferred to 0.2.0, criteri sblocco
- **memoria persistente Claude** in `~/.claude/projects/-Users-stefanoferri-Developer-Devonthink-MCP/memory/` — 8 file con stato + pattern + reference

---

## Per riprendere

Da terminale (Terminal.app raccomandato per AppleEvents):

```bash
cd ~/Developer/Devonthink_MCP
git status                    # → clean
git log --oneline -5          # → ultimo PR #35
gh release view v0.1.0        # → release LIVE con .mcpb asset
```

Verifica MCP Registry:
```bash
curl -sL "https://registry.modelcontextprotocol.io/v0/servers?search=istefox" | python3 -m json.tool | head -20
```

Verifica integration tests (DT running + TCC OK):
```bash
uv run pytest tests/integration -m integration --benchmark-enable -v
# Atteso: 7 PASS
```
