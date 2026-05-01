# ADR 0005 — Test strategy 4-tier (unit / contract VCR / integration macOS / smoke)

- **Status**: Accepted (con spike di validazione su CI costs e fixture licensing)
- **Date**: 2026-04-30
- **Decisori**: Stefano Ferri
- **Fonte**: REVIEW_ADR §2 P4, §7 ADR-004

---

## Contesto

Il brief identificava il problema (testing di un sistema dipendente da app GUI macOS) come "aperto" (§12.5) e listava in §10 mitigazioni generiche ("Test suite con JXA mocking, smoke test su ogni release DT") senza strategia operativa. La review ha rifiutato la trattazione attuale come non-strategia e propone un'architettura a 4 tier che impatta scelte di codebase (interface contract, fixture format, CI runner).

## Decisione

Test strategy a **4 tier** con responsabilità e frequenze distinte.

### Tier 1 — Unit (offline, fast, ogni commit)

- **Coverage target**: service layer, schema Pydantic, cache layer, error handling, audit log
- **Bridge mocking**: `DEVONthinkAdapter` mockato via `unittest.mock.AsyncMock`
- **Fixture**: JSON `tests/fixtures/jxa_outputs/*.json` con output simulati delle dictionary calls
- **Runner**: linux GitHub Actions `ubuntu-latest` (gratuito)
- **Trigger**: ogni push, ogni PR
- **Tempo target**: < 30s suite completa
- **Coverage target**: ≥ 80% sui moduli `adapter`, `schemas`, `tools`. Audit + cache: 100%

### Tier 2 — Contract test (record/replay, fast, ogni PR)

- **Pattern**: VCR.py-style. Cassette JSON con tuple `(input_jxa_script, output_json)`
- **Cassette**: generate una tantum su Mac reale con DT, **committate in repo** in `tests/contract/cassettes/`
- **Replay**: in CI senza DT (linux runner)
- **Scopo**: forzare consistenza del bridge contract — se l'output JXA reale cambia (DT update), la cassette va rigenerata e il delta è visibile in PR
- **Runner**: linux (gratuito)
- **Trigger**: ogni PR
- **Aggiornamento**: comando `uv run istefox-dt-mcp test-record --tool=<name>` per rigenerazione manuale su Mac sviluppo

### Tier 3 — Integration test (slow, su PR su main + nightly)

- **Runner**: GitHub Actions `macos-14` (decisione condizionale a output spike costi)
- **Database fixture**: template minimale `tests/fixtures/dt_sample.dtBase2`, ~50 record sintetici (licenza DT da verificare)
- **Esecuzione**: spawn DT in background mode (o launch normale, accettando che la GUI appaia in headless runner)
- **Coverage**: end-to-end di ogni tool MVP, scenari di errore (DT not running, timeout, permission denied)
- **Trigger**: PR verso `main` + cron nightly
- **Tempo target**: < 5 min suite completa
- **Cleanup**: ogni run ricrea il DB fixture from-scratch per isolamento

### Tier 4 — Smoke test post-release (manuali o pipeline staging)

- Eseguiti via comando `istefox-dt-mcp doctor --extended`
- 5-10 chiamate reali a DT, validazione output schema
- **Trigger**: ogni release DT minor (4.x) prima di pubblicare nuova versione del connector
- **Trigger automatico**: cron settimanale via GitHub Actions per detection regressioni esterne
- **Output**: report markdown committato in `tests/smoke/reports/<date>.md`

## Razionale

- **Confidence in produzione**: 4 tier coprono unit logic, contract stability, integration end-to-end, regression detection esterna
- **Costi controllati**: tier 1-2 su linux gratuito, tier 3 su macOS solo dove necessario
- **Ripeibilità**: cassette VCR-style permettono debugging deterministico
- **Detection precoce**: smoke test settimanale intercetta breaking changes DT prima che impattino release del connector

## Costi CI (assunzioni da validare con spike)

- GitHub Actions `macos-14` ~10x del runner linux
- Mitigazione: integration test solo su PR verso `main` e nightly, non su feature branch
- Stima preliminare: ~$50-100/mese per progetto a basso volume di PR
- **Spike obbligatorio prima di Step 7**: misurare costo reale su 5 PR sintetici → decidere GHA macOS-14 vs Mac mini self-hosted SATURNO

## Decisioni rinviate (richiedono spike)

| Spike | Tempo | Output |
|---|---|---|
| Costi GHA macOS-14 | 1 giorno | Decisione runner integration test |
| Licenza DT per fixture committabile | ½ giorno | Decisione su `dt_sample.dtBase2` in repo o generato runtime |
| osascript stabile in CI runner non interattivo | 1 giorno | Decisione su modalità launch DT in CI |

Se uno degli spike rivela blocker, fallback a:
- Mac mini self-hosted (riuso infra SATURNO)
- Fixture generato a runtime via JXA (no committable .dtBase2)
- Integration test solo manuali (rischio regressione)

## Conseguenze

- ✅ Confidence in production
- ✅ Riproducibilità deterministica (Tier 2)
- ✅ Regression detection automatica (Tier 4)
- ⚠ Settimana di setup infrastrutturale in W2-W3
- ⚠ Costo CI macOS variabile (mitigato con frequency limiting)
- ⚠ Cassette manutenzione: ogni breaking change DT richiede rigenerazione

## Riferimenti

- REVIEW_ADR.md §2 P4, §7 ADR-004, §3 (gap #1, #2)
- Brief §10 (mitigazioni generiche), §12.5 (test strategy aperta)
