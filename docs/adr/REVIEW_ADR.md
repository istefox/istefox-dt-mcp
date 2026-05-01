# Architecture Review — MCP Connector per DEVONthink 4

**Documento**: REVIEW_ADR.md
**Versione**: 1.0
**Data**: 30 aprile 2026
**Reviewer**: Claude (skill: engineering:architecture + engineering:system-design)
**Input**: ARCH-BRIEF-DT-MCP v0.1
**Scopo**: validazione architetturale del brief preliminare, gap analysis, definizione MVP scope e candidate ADR

---

## 1. Executive Summary

Il brief è **architettonicamente solido e ben informato sulle best practice MCP 2026**, ma presenta tre tendenze sistemiche da correggere: (1) **over-engineering del bridge layer** giustificato da scenari fuori scope v1; (2) **MVP eccessivamente conservativo** che rinvia la validazione del pattern critico (dry-run + audit) a fase 2; (3) **gap su test strategy e operations** che oggi sono trattati come "aperti" ma sono blocker per produzione.

**Verdetto generale**: APPROVO con modifiche. La struttura a 6 layer e la scelta dello stack Python+FastMCP+ChromaDB sono confermate. Le modifiche proposte riducono lo scope di ~2 settimane e spostano valore in MVP.

**Top 5 raccomandazioni P0/P1**:

1. **P0 — Solo JXA bridge in v1**, mantenere astrazione `DEVONthinkAdapter` ma drop di x-callback-url e DT Server bridge come implementazioni v1. Recovery: -1.5 settimane.
2. **P0 — RAG sidecar same-process** (threading isolation) anziché processo separato con IPC. Riduce complessità deployment. Reversibile in v2 se profiling lo richiede.
3. **P1 — MVP a 4 tool** includendo `file_document` con `dry_run` mandatory: valida il pattern audit + dry-run dal day 1, non dalla settimana 8.
4. **P1 — Test strategy a 4 tier** (unit/contract-fixture/integration/smoke) da definire come ADR prima di W3, non a fine roadmap.
5. **P1 — OAuth scope ridotti a 3** (`dt:read`, `dt:write`, `dt:admin`) con database-scoping spostato nei parametri dei tool, non nello scope OAuth.

**Confidence complessiva del review**: 80% — alta su gap analysis, MVP scope, drop DT3, bridge layer; media su tool versioning (pattern non consolidato in MCP community) e su test strategy CI (richiede spike per validare costi macOS runner).

---

## 2. Validazione punto per punto delle 8 aree

### P1 — Bridge multi-channel (JXA + x-callback-url + DT Server)

**Posizione**: ⚠ MODIFICARE

**Razionale**: per il caso d'uso single-user macOS dichiarato come target v1 (§2.3, §4.3), il multi-bridge è over-engineering. JXA copre il superset funzionale. x-callback-url ha latenza inferiore solo su una manciata di operazioni (open record, create-from-clipboard) e duplica la matrice di test. DT Server bridge è giustificato solo da scenari multi-host che il brief stesso classifica come "v2+" (§5.5). Mantenere astrazione e drop implementazioni concrete.

**Alternativa proposta**:
- v1: interfaccia `DEVONthinkAdapter` astratta + **una sola implementazione `JXAAdapter`**
- v1: ADR esplicito che fissa il contratto (input/output, error semantics, idempotency) senza implementare le altre fonti
- v1.5: aggiungere `XCallbackAdapter` solo se profiling identifica bottleneck specifici (criterio quantitativo: >30 % delle chiamate su un set di 3-5 operazioni candidabili)
- v2+: `DTServerAdapter` solo se emerge requirement multi-host concreto

**Trade-off esplicito**:
- *Si guadagna*: ~1.5 settimane di delivery, matrice di test ridotta, meno superficie di bug
- *Si perde*: failover automatico (mitigato con retry exponential backoff su JXA), e una "comodità d'astrazione" per l'apertura di item che è già coperta da JXA con latenza accettabile

**Confidence**: alta. Assunzione: il single-user con DT in esecuzione locale resta lo scenario v1, come dichiarato in §4.3.

---

### P2 — RAG sidecar: ownership e deployment

**Posizione**: ⚠ MODIFICARE (verso semplificazione)

**Razionale**: la proposta del brief è "processo Python separato, IPC via Unix socket, lifecycle gestito da launcher script" (§6.1, §8.2). Per single-user su una macchina, l'IPC introduce: socket lifecycle management, error handling sulla connessione, deployment con due processi orchestrati, complicazioni nel `.mcpb` packaging. I benefici (crash isolation) sono parzialmente compensabili con threading + supervisione interna. Container è eccessivo per single-user macOS.

**Alternativa proposta**:
- **v1: same-process Python con isolamento via `concurrent.futures.ThreadPoolExecutor` dedicato al RAG**
  - Embedding model caricato lazy al primo `search` o `ask_database`
  - Query ChromaDB serializzate via lock interno (ChromaDB embedded non è thread-safe per writes)
  - Try/except esplicito attorno alle chiamate RAG con fallback graceful a BM25-only
  - Astrazione `RAGProvider` come interfaccia, swappable
- **v2** (se metriche di production lo richiedono): separazione in processo con IPC. Il refactor è contenuto perché `RAGProvider` è già un'interfaccia.

**Trade-off esplicito**:
- *Si guadagna*: ~1 settimana di delivery, deployment unico, packaging `.mcpb` più semplice, debugging unificato
- *Si perde*: crash isolation (un OOM dell'embedding model porta giù il server), aggiornamento indipendente del modello (mitigato con feature flag)

**Confidence**: media-alta. Assunzione critica: ChromaDB embedded resta stabile sotto carico realistico (max ~50K record nei DB Stefano). Mitigazione: spike di 1-2 giorni prima della W5 per stress-test ChromaDB embedded con 100K record sintetici.

---

### P3 — MVP scope (3 read-only vs 5 con write)

**Posizione**: ⚠ MODIFICARE

**Razionale**: 3 tool read-only è troppo conservativo. Il pattern `dry_run + audit_id + before-state` è la **value proposition principale** rispetto al connector `dvcrn/mcp-server-devonthink` (§2.1). Validarlo a fine settimana 8 lascia metà del progetto su ipotesi non testate. Includere UN solo write tool (`file_document`) chiude il loop. Cinque tool con `bulk_apply` sono troppi: `bulk_apply` e `create_smart_rule` hanno blast radius alto e valore non ancora validato.

**Alternativa proposta — MVP a 4 tool**:

| Tool | Tipo | Razionale inclusione |
|---|---|---|
| `search` | read (hybrid BM25 + vector) | Capability primaria, differenzia dal connector esistente |
| `ask_database` | read (RAG Q&A) | Innovazione centrale, valida il sidecar end-to-end |
| `find_related` | read | Wrap intelligente di "See Also"/"Compare", basso rischio, valore alto |
| `file_document` | write con `dry_run` | Valida pattern dry-run + audit + undo dal day 1 |

**Esclusi da v1 (con razionale)**:
- `summarize_topic`: replicabile dal client con `ask_database` + prompt template; non aggiunge capability strutturale
- `bulk_apply`: blast radius alto, prematuro senza pattern dry-run validato in produzione su `file_document`
- `create_smart_rule`: caso edge per power user, non è core MVP

**Trade-off esplicito**:
- *Si guadagna*: validazione del pattern dry-run/audit/undo dal day 1, MVP più focalizzato, value prop completa (read + 1 write tipico)
- *Si perde*: una settimana aggiuntiva sul percorso critico (compensata dal -1.5 settimane di P1 e -1 di P2)

**Confidence**: media. Assunzione: `file_document` ha auto-classify e auto-tag affidabili in DT4 — da validare nella settimana 1-2 con uno spike su database reali.

---

### P4 — Test strategy

**Posizione**: ✗ RIFIUTO della trattazione attuale (il brief identifica il problema ma non propone strategia)

**Razionale**: §10 elenca "Test suite con JXA mocking, smoke test su ogni release DT" come mitigazione, ma non è una strategia: è una lista. Va trattata come ADR a sé prima della W3, perché impatta scelte di codebase (interface contract, fixture format, CI runner).

**Alternativa proposta — strategia a 4 tier**:

1. **Unit (offline, fast, ogni commit)**
   - Coverage target: service layer, schema Pydantic, cache layer, error handling
   - `DEVONthinkAdapter` mockato via `unittest.mock.AsyncMock`
   - Fixture JSON per output simulati delle dictionary calls
   - Runner: linux GitHub Actions (gratis)

2. **Contract test (record/replay, fast, ogni PR)**
   - Pattern VCR.py-style: cassette JSON con `(input_jxa_script, output_json)`
   - Cassette generate una tantum su Mac reale con DT, committate in repo
   - Replay in CI senza DT
   - Forzano consistenza del bridge contract
   - Runner: linux (gratis)

3. **Integration test (slow, su PR su main + nightly)**
   - Eseguiti su Mac CI runner (GitHub Actions `macos-14`)
   - Database DT fixture committato in repo (template minimale, ~50 record sintetici)
   - Spawn DT in headless-ish mode (o launch normale, accettando che la GUI appaia)
   - Coverage: end-to-end di ogni tool MVP, scenari di errore (DT not running, timeout, ecc.)

4. **Smoke test post-release (manuali o in pipeline staging)**
   - `vibrofer-dt-mcp doctor --extended`: 5-10 chiamate reali a DT, validate output schemas
   - Eseguiti su ogni release DT minor (4.x) prima di pubblicare nuova versione del connector
   - Trigger anche da `cron` settimanale per detection regressioni esterne

**Costo CI (assunzione, da validare)**: GitHub Actions `macos-14` ~10x del runner linux. Mitigazione: integration test solo su PR verso `main` e nightly, non su feature branch. Stima ~$50-100/mese per progetto a basso volume di PR.

**Trade-off esplicito**:
- *Si guadagna*: confidence in produzione, riproducibilità, regression detection automatica
- *Si perde*: settimana di setup infrastrutturale (in W2 o W3), costo CI macOS

**Confidence**: media. Assunzioni da validare con spike: (a) feasibility di template DT minimale committabile (licenza DT permette redistribuzione di un .dtBase2?); (b) costi reali di GitHub Actions macOS sotto frequenza CI tipica; (c) stabilità di osascript in CI runner non interattivo.

---

### P5 — Tool versioning

**Posizione**: ⚠ MODIFICARE — il brief identifica la domanda (§12.6) ma non propone pattern

**Razionale**: MCP 2026 non ha header version standardizzato per i tool (verificato sulla spec ufficiale, [modelcontextprotocol.io](https://modelcontextprotocol.io)). I client (Claude Desktop, Claude.ai) salvano riferimenti per nome tool. Una rinomina rompe i prompt salvati. Versioning per nome è il pattern de facto, ma serve disciplina sull'evoluzione del schema.

**Pattern raccomandato — backward-compat by default + suffix solo su breaking change**:

| Cambiamento | Versioning | Esempio |
|---|---|---|
| Aggiunta campo opzionale al request | Nessuno | `search` accetta nuovo `filters.kind` |
| Aggiunta campo al response | Nessuno | `search.results[].score_components` aggiunto |
| Rimozione/rinomina campo, cambio semantica | **Suffix versioning** | `search` → `search_v2`, vecchio mantenuto deprecated |
| Cambio del set di valori enum (rimozione) | Suffix versioning | `mode` perde `bm25` → nuovo tool |
| Cambio del set di valori enum (aggiunta) | Nessuno | `mode` aggiunge `rerank` |

**Regole operative**:
- Vecchio tool mantenuto per **6 mesi** dopo l'introduzione del successore (allineato a deprecation policy moderna)
- Tool description deprecata include riga `[DEPRECATED, use search_v2]` ben visibile per tool search
- Changelog pubblicato in repo + sezione "Breaking changes" nelle release notes

**Riferimenti**: pattern simile a [Stripe API versioning](https://stripe.com/docs/upgrades) ma più conservativo (Stripe usa date-based, non semantic). Anthropic stessa nei propri tool MCP non documenta una policy esplicita — non sono presenti fonti ufficiali sul pattern preferito MCP per tool versioning al 2026.

**Trade-off esplicito**:
- *Si guadagna*: prevedibilità per gli utenti, prompt salvati non si rompono
- *Si perde*: codebase con duplicazioni temporanee dei vecchi tool, maintenance overhead

**Confidence**: media — questa è opinion-leadership su un pattern non ancora consolidato dalla community MCP. Se in 6-12 mesi emerge uno standard MCP per versioning, l'ADR andrà aggiornato.

---

### P6 — Scope OAuth granularity

**Posizione**: ⚠ MODIFICARE

**Razionale**: i 5 scope proposti (`dt:read`, `dt:write`, `dt:delete`, `dt:bulk`, `dt:admin`) sono ridondanti per il single-user e creano frizione nel consent flow. La granularità per database (es. `dt:read:business` vs `dt:read:privato`) è interessante ma rappresentata male come scope OAuth: i database DT sono entità dinamiche (l'utente ne crea/rinomina), gli scope OAuth sono stringhe statiche.

**Alternativa proposta — 3 scope + database-scoping nei parametri**:

| Scope | Copre | Default consent |
|---|---|---|
| `dt:read` | search, get, list, summarize, ask_database, find_related | Sì (al primo consent) |
| `dt:write` | tag, rename, move, delete, file_document, bulk_apply | No (escalation esplicita) |
| `dt:admin` | create_smart_rule, modify_database settings | No (escalation esplicita) |

**Database-scoping al di fuori dello scope OAuth**:
- Consent UI mostra: "Il client può accedere a questi database: [Business, Privato, ...]" con checkbox per database
- La selezione è persistita nel server (non nell'OAuth token) e applicata come filtro automatico su ogni tool call
- Gestisce database creati dopo il consent: chiede conferma via `RECONSENT_REQUIRED` la prima volta che il client tenta accesso

**Razionale del merge `delete`+`bulk` in `write`**: distinguerli aggiunge friction senza aumentare significativamente la sicurezza — chi ha `dt:write` può rinominare a `_DELETED_` e archiviare massivamente, l'effetto utente è simile. La protezione vera viene da `dry_run` mandatory + audit log + undo.

**Trade-off esplicito**:
- *Si guadagna*: consent flow chiaro (3 vs 5 scope, label ovvi), gestione naturale di database dinamici
- *Si perde*: granularità di scope (ma compensata dal database-scoping)

**Confidence**: media-alta. Assunzione: il single-user resta dominante v1. Se v2 introduce multi-user reale, valutare aggiunta `dt:bulk` come scope distinto (limite alle operazioni batch >N record).

---

### P7 — DT Server bridge in astrazione

**Posizione**: ⚠ MODIFICARE — astrazione sì, implementazione no

**Razionale**: progettare un'astrazione su un'API che non è ancora studiata in profondità rischia di vincolare al modello sbagliato. DT Server non è una REST API ma un'interfaccia HTML/login (§2.3): il contratto pulito di `DEVONthinkAdapter` (es. `async def get_record(uuid) -> Record`) potrebbe non mappare bene su scraping HTML. Meglio fissare il contratto astratto basandosi su JXA (che è la fonte di verità della scripting dictionary DT) e validare DT Server in v2 con uno spike dedicato.

**Alternativa proposta**:
- v1: interfaccia `DEVONthinkAdapter` definita con metodi astratti (`get_record`, `search`, `list_databases`, `apply_tag`, ecc.)
- v1: ADR-001 "Bridge contract" che documenta input/output schemas, error semantics, idempotency requirements (vedi §6 ADR candidate)
- v1: una sola implementazione `JXAAdapter`
- v2+: spike di 1 settimana su DT Server per validare la mappabilità sull'interfaccia esistente. Solo dopo il spike, decidere se implementare o se serve refactor del contratto

**Trade-off esplicito**:
- *Si guadagna*: focus delivery, contratto pulito basato su realtà (JXA), nessun debito tecnico da rimappatura forzata
- *Si perde*: nulla di concreto in v1; in v2 potrebbe servire un piccolo refactor se DT Server ha quirks non anticipati

**Confidence**: alta.

---

### P8 — Backward compat DT3

**Posizione**: ✗ RIFIUTO

**Razionale**:
1. Il differenziale di scripting non è solo `Application("DEVONthink 3")` vs `Application("DEVONthink")`: DT4 introduce AI generativa nativa, smart rule conditions nuove, field aggiuntivi (§2.3). Feature gating è invasivo.
2. L'utente target dichiarato (Stefano, §4.3) usa DT4. Il connector esistente `dvcrn/mcp-server-devonthink` (§2.1) copre già DT3, quindi l'utenza DT3 ha alternative.
3. DT3 → DT4 è un upgrade da $99-149 (verifica fonte: non sono riuscito a verificare i prezzi correnti sul sito DEVONtechnologies, dato indicativo): chi non ha aggiornato in 12 mesi ha probabilmente motivi specifici e non aggiornerà per usare un nuovo MCP connector.
4. Mantenimento: ogni nuovo tool richiede doppia validazione, doppia matrice di test, doppia documentazione.

**Alternativa proposta**: drop esplicito di DT3 in v1. Documentare in README ("Requires DEVONthink 4.0 or later") e in `vibrofer-dt-mcp doctor` come check di compatibilità. Se user request emerge in volume, valutare branch separato `dt3-compat` mantenuto per community contribution.

**Trade-off esplicito**:
- *Si guadagna*: ~1 settimana di lavoro evitato + ~10-15 % di complessità del codebase (stima)
- *Si perde*: TAM marginale dell'utenza DT3 che non aggiorna

**Confidence**: alta.

---

## 3. Gap Analysis — cose che il brief NON copre ma dovrebbe

Lista prioritizzata. P0 = blocker per produzione, P1 = importante per MVP, P2 = nice-to-have v1.5+.

| # | Gap | Priorità | Impatto |
|---|---|---|---|
| 1 | **Test strategy** concreta a 4 tier (vedi §2 P4) | P0 | Blocker quality |
| 2 | **CI/CD pipeline** definita: macOS runner, costi, frequenza, branch policy | P0 | Blocker delivery |
| 3 | **Embedding model lifecycle**: cosa succede su upgrade modello? Reindex full? Coexistenza? Hash content vs hash content+model? | P0 | Blocker correctness |
| 4 | **Sidecar startup time**: caricamento `bge-m3` impiega ~5-15s (~2GB download). Strategia lazy-load + UX startup? Cold start vs warm? | P1 | UX |
| 5 | **Concurrent write protection**: due client che invocano `bulk_apply` o `file_document` concorrentemente — locking strategy a livello server (mutex per record? per database?) | P1 | Data integrity |
| 6 | **Telemetry opt-in/opt-out**: OTel può esportare verso terzi. Privacy by design (G2 §3.1) richiede default disabled + consent esplicito | P1 | Privacy / G2 |
| 7 | **Rate limiting strategy**: menzionato come error code (`RATE_LIMITED`, §6.6) ma non come policy — token bucket per scope? Per session? Limiti hard-coded? | P1 | Stability |
| 8 | **Audit log retention vs GDPR/diritto cancellazione**: se l'utente cancella un record DT, l'audit log mantiene reference UUID. Policy esplicita serve | P1 | Compliance |
| 9 | **Strategia di rollback** del connector: come downgrade da v1.x a v1.0 se un release rompe? Versioned config schema? | P1 | Operations |
| 10 | **Localizzazione tool description**: italiano (utente target) o inglese (LLM funzionano meglio in EN)? Decisione + razionale | P1 | UX/Performance |
| 11 | **Embedding model licensing**: bge-m3 è MIT (verifica: non sono riuscito a verificare la licenza esatta su Hugging Face nel review), e5-large è MIT. Va verificato e documentato | P1 | Legal |
| 12 | **OAuth callback URL design**: per HTTP transport serve redirect URI. Loopback `localhost:N`? Custom scheme? Cloudflare Tunnel domain? | P2 | HTTP transport |
| 13 | **Bundled binary size** di `.mcpb`: include Python interpreter? Embedding model? Dimensione attesa? Strategia di download lazy del modello al primo uso? | P2 | Distribution |
| 14 | **Auto-launch DT** se `DT_NOT_RUNNING`: decisione policy (auto-launch silente, prompt utente, errore secco?) | P2 | UX |
| 15 | **Strutturazione dei "Prompts" MCP** (§5.3): elencati 4 candidate ma senza scope. Sono solo template testuali o invocano automaticamente sequenze di tool? Come vengono versionati? | P2 | Feature scope |

---

## 4. Risk Re-assessment

Rivalutazione dei rischi del §10 + nuovi rischi emersi dal review.

### Rischi del brief — confermati / declassati

| Rischio (§10) | Probabilità originale | Probabilità revisionata | Impatto | Note |
|---|---|---|---|---|
| JXA bridge rompe con update DT minor | Media | **Alta** ↑ | Alto | DT4 è all'inizio del ciclo, breaking minor probabili. Mitigazione test è essenziale (vedi P4) |
| Embedding sync out-of-sync | Alta | **Media** ↓ | Medio | ChromaDB embedded + reconciliation hash-based + smart rule è robusto |
| OAuth setup complica adoption | Media | Media | Medio | Confermato. Mitigazione "stdio default" è corretta |
| ChromaDB lock contention | Bassa | Bassa | Medio | Confermato (DB fuori cartella DT) |
| Performance JXA con DB grandi (>100K record) | Alta | Alta | Alto | **Rischio principale**. Cache + bypass via vector + paginazione sono mitigazioni necessarie ma non sufficienti — serve spike di profiling W2 |
| AI nativa DT4 cambia interfaccia | Media | **Bassa** ↓ | Medio | Adapter pattern già pianificato; AI nativa non è core MVP se `summarize_topic` esce dal MVP (P3) |
| Smart rule trigger inaffidabile | Media | Media | Alto | Confermato. Polling + reconciliation notturno è ragionevole |
| Conflitto licenza GPL con `dvcrn/...` | Bassa | Bassa | Alto | Confermato. Implementazione clean-room obbligatoria |

### Nuovi rischi (non coperti nel §10)

| Rischio | Probabilità | Impatto | Mitigazione |
|---|---|---|---|
| **Costi macOS CI runner** in GitHub Actions sotto carico tipico (PR + nightly) | Alta | Basso (economico) | Limitare integration test a PR su `main` + nightly; valutare self-hosted runner Mac mini |
| **Embedding model download size** (~2GB bge-m3) + scenari offline / connessione lenta | Media | Medio (UX setup) | Lazy download al primo `search` con progress bar; documentare `vibrofer-dt-mcp doctor --download-models` |
| **Privacy leak in structured logs**: query sensitive in stderr → log retention/persistence | Media | Medio | Redaction default attiva su payload tool, configurable, off by default per `audit_id` |
| **Crash isolation insufficient con same-process sidecar** (P2): OOM dell'embedding model porta giù il server MCP | Media | Medio | Memory limit configurable + supervisor restart logic + fallback graceful BM25 |
| **Tool description lingua sbagliata** può degradare tool selection da parte dell'LLM | Media | Medio | A/B test con eval set di prompt italiani vs inglesi prima di freeze |
| **`dvcrn/mcp-server-devonthink` evolve e copre i gap** prima del rilascio | Media | Alto (strategico) | Monitoring repo upstream; differenziarsi sul RAG sidecar (non replicabile in TS senza ecosystem) |
| **DT4.x licensing change** (es. AI features dietro paywall futuro) potrebbe rompere `summarize_topic`/`ask_database` | Bassa | Medio | Adapter pattern + fallback a LLM client-side |

---

## 5. MVP Scope finale raccomandato

**Cinque tool inclusi, tre esclusi rispetto al brief** (§5.4 lista 7).

### Inclusi in v1

| Tool | Tipo | Razionale inclusione |
|---|---|---|
| `search` | read (hybrid BM25 + vector) | Capability primaria. Differenzia da `dvcrn/...` con vector RAG sidecar |
| `ask_database` | read (RAG Q&A multi-doc) | Innovazione centrale, valida pipeline embedding → retrieval → answer |
| `find_related` | read | Wrap "See Also"/"Compare", basso rischio, valore alto |
| `file_document` | write con `dry_run` mandatory | Valida pattern dry-run + audit + undo dal day 1 |
| **`list_databases`** (nuovo) | read | Resource enumeration di base, abilita altri tool, costo zero |

Aggiunta di `list_databases` perché è prerequisito UX per gli altri tool (l'LLM deve sapere quali database esistono prima di fare query mirate). Era già in roadmap W1-2 (§9) ma non in §5.4.

### Esclusi da v1 (con razionale)

| Tool | Razionale esclusione |
|---|---|
| `summarize_topic` | Replicabile dal client con `ask_database` + prompt template ad hoc. Dipendenza da AI nativa DT4 (rischio interfaccia). Non aggiunge capability strutturale |
| `bulk_apply` | Blast radius alto. Valore non validato. Prerequisito: `file_document` deve aver dimostrato il pattern dry-run in produzione |
| `create_smart_rule` | Caso edge per power user. Bassa frequenza d'uso attesa per Stefano. Rinviabile a v2 |

### Resources MCP in v1

Mantenere quanto in §5.3 (dt://database/{name}, dt://record/{uuid}, ...) ma con limite stretto **≤ 25K token** per resource (ribadito) e validazione automatica nei test.

### Prompts MCP in v1

**Esclusi tutti** dalla v1. I 4 candidate (§5.3 — `research_synthesis`, `client_brief`, `weekly_review`, `tag_migration`) richiedono validazione use-case con utente. Aggiungerli post-MVP dopo 2-4 settimane di uso reale, in base a pattern d'uso emersi.

---

## 6. Roadmap Revised

Roadmap a 12 settimane con correzioni di scope e sequenza. Le settimane risparmiate (P1 -1.5, P2 -1, P8 -1 = -3.5) sono assorbite da W7 ridotta (-1) e W11-12 buffer (-2.5 trasformate in hardening + spike).

| Settimana | Originale (§9) | Revised | Delta |
|---|---|---|---|
| W1-2 | Foundations + 3 tool (list_db, get_record, search BM25) | **Foundations + spike profiling JXA + ADR-001/002/003 + 3 tool read** (`list_databases`, `search` BM25, `find_related`) | + spike + ADR formali |
| W3-4 | Pool + cache + 3 tool | **Pool + cache + `ask_database` (BM25 mode)** + structured logging + Pydantic schemas | Tolto `summarize_topic` (escluso da MVP) |
| W5-6 | RAG sidecar (processo separato) | **RAG same-process** + ChromaDB + bge-m3 + smart rule sync + hybrid search in `search` e `ask_database` | Same-process invece di sidecar |
| W7 | Write ops (3 tool) | **Solo `file_document`** con dry_run + audit log + undo | -1 settimana (era W7-8) |
| W8 | Write ops parte 2 | **HTTP transport + OAuth scope semplificato** (3 scope) | Era W9-10, anticipato |
| W9 | HTTP + OAuth | **Test strategy implementation** (contract test, integration test, smoke test) | Spostato test strategy come fase dedicata |
| W10 | HTTP + OAuth parte 2 | **Hardening, OTel tracing, performance benchmarks** | Performance W11 originale |
| W11 | Hardening | **Documentation + `.mcpb` + pipx packaging + onboarding flow** | |
| W12 | Hardening parte 2 | **Buffer + post-release feedback loop + spike v2 (DT Server, sidecar separato se metriche lo richiedono)** | |

### GO/NO-GO checkpoint revised

- **W2**: latenza JXA p95 < 500ms su DB Stefano? Compatibilità DT4 confermata? **+ Stress test ChromaDB con 50K record sintetici**
- **W6**: vector search migliora quality vs BM25 su 20 query reference? Sync smart-rule funziona affidabile su 1 settimana?
- **W8** (nuovo): pattern `dry_run + audit + undo` valida su `file_document` con 50+ esecuzioni reali?

---

## 7. Architecture Decision Records candidate

Lista degli ADR formali da scrivere, in ordine di priorità (P0 = bloccante per W1, P1 = entro W4, P2 = entro W8).

| # | Titolo | Scope | Priorità |
|---|---|---|---|
| ADR-001 | Bridge architecture: JXA-only in v1 con interfaccia astratta multi-bridge ready | Drop x-callback-url e DT Server bridge da v1, definire `DEVONthinkAdapter` contract | P0 |
| ADR-002 | RAG sidecar deployment model: same-process Python con threading isolation in v1 | Razionale, criteri di promozione a processo separato in v2 | P0 |
| ADR-003 | MVP tool scope: 5 tool incluso `file_document` con `dry_run` mandatory | Lista inclusi/esclusi, criteri di inclusione | P0 |
| ADR-004 | Test strategy: 4-tier (unit / contract VCR-style / integration macOS CI / smoke post-release) | Tooling, fixture format, frequency, costi CI | P0 |
| ADR-005 | Tool versioning: backward-compat by default, suffix versioning su breaking change, deprecation 6 mesi | Regole concrete, esempi, deprecation policy | P1 |
| ADR-006 | OAuth scope model: 3 scope (`dt:read`, `dt:write`, `dt:admin`) + database-scoping in tool params | Razionale, consent flow, gestione database dinamici | P1 |
| ADR-007 | DT4-only support, drop DT3 backward compatibility | Razionale, requisiti minimi di versione, doctor check | P1 |
| ADR-008 | Embedding model selection: `bge-m3` vs `multilingual-e5-large` | Benchmark su query italiane reali, tradeoff multilinguismo/dimensione/licenza | P1 |
| ADR-009 | Vector DB choice: ChromaDB embedded in v1, Qdrant migration path in v2 | Criteri di promozione (volume, multi-collection, persistence) | P1 |
| ADR-010 | Distribution strategy: `.mcpb` + `pipx` dual-target, embedding model lazy-download | Build pipeline, packaging size budget, model download UX | P2 |
| ADR-011 | Telemetry & observability: opt-in OTel, structured logging stderr, audit log retention 90gg con GDPR-compliant deletion | Privacy by design, redaction defaults, retention policy | P2 |
| ADR-012 | Tool description language: inglese per LLM performance, italiano nei messaggi di errore user-facing | Razionale + A/B test plan | P2 |
| ADR-013 | Concurrent write protection: lock per-record + transaction log | Strategia di locking, deadlock prevention, integrazione con audit | P2 |
| ADR-014 | Rate limiting: token bucket per scope (con valori di default) | Policy concreta, override per uso interno, error semantics | P2 |

---

## 8. Domande aperte (richiedono input prima di chiudere il review)

Le seguenti decisioni dipendono da informazioni che il brief non chiarisce e che incidono sulle raccomandazioni:

1. **Single-user è veramente garantito v1?** Il §4.3 lo dice, ma §5.2 menziona "Streamable HTTP per Claude.ai web, app mobili" con OAuth. Se v2 include accesso multi-device dello stesso utente da remoto (Cloudflare Tunnel SATURNO), va anticipato il modello di sessione/scope. Se v2 include accesso di altri colleghi Vibrofer, OAuth model va rivisto.

2. **CI infrastructure**: esiste già un Mac mini self-hosted (es. nell'infra SATURNO) utilizzabile come CI runner, o si parte da GitHub Actions `macos-14`? Impatta costi e ADR-004.

3. **Telemetry policy**: è ammesso esportare metriche OTel verso un endpoint owned-by-Stefano (es. Grafana Cloud, Honeycomb), o tutto deve restare strettamente on-device anche in modalità HTTP? Impatta ADR-011.

4. **Lingua tool description**: c'è una preferenza forte per italiano (utente target Stefano) o si accetta inglese per ottimizzare performance LLM? Impatta ADR-012 e i benchmark del W6.

5. **Database fixture per integration test**: la licenza DT permette di committare un `.dtBase2` minimale in repo open-source? Va verificato con DEVONtechnologies o sui ToS DT prima di adottare ADR-004 nella forma proposta.

6. **Budget tempo per spike**: gli spike proposti (W2 stress-test ChromaDB, eventuale spike DT Server in v2) richiedono 1-2 giorni ciascuno. Sono accettabili o vanno compressi?

---

## 9. Confidence statement

**Confidence complessiva del review**: 80 %.

**Breakdown**:
- Validazione P1, P2, P7, P8: confidence **alta** (90 %) — ragionamento basato su principi noti di system design (bounded scope, YAGNI, crash blast radius)
- Gap analysis e MVP scope (P3): confidence **alta** (85 %) — assunzione critica è la stabilità di ChromaDB embedded, mitigata da spike W2
- Test strategy (P4): confidence **media** (70 %) — costi CI macOS e feasibility fixture DT da validare con spike (1-2 giorni)
- Tool versioning (P5): confidence **media** (65 %) — pattern non consolidato dalla community MCP, opinion-leadership
- OAuth scope (P6): confidence **media-alta** (75 %) — dipende da scenari multi-user futuri non chiari (vedi domanda aperta #1)
- Risk re-assessment: confidence **alta** (85 %)
- Roadmap revised: confidence **media** (70 %) — la stima -3.5 settimane assorbita in buffer è ottimistica; un terzo del buffer potrebbe sparire in unforeseen issues

**Raccomandazioni robuste** (eseguibili senza ulteriori spike):
- ADR-001 (JXA-only v1)
- ADR-003 (MVP a 5 tool incluso `file_document`)
- ADR-006 (3 OAuth scope)
- ADR-007 (drop DT3)

**Raccomandazioni che richiedono spike di validazione**:
- ADR-002 (same-process sidecar) → spike ChromaDB stress test W2
- ADR-004 (test strategy) → spike costi CI macOS + feasibility fixture
- ADR-005 (tool versioning) → riesame a 6-12 mesi quando MCP community consolida pattern

**Assunzioni implicite del review da segnalare**:
- (A1) Single-user resta scenario v1 — input richiesto (domanda aperta #1)
- (A2) ChromaDB embedded scala bene a ~50K record nei DB Stefano — validabile con spike
- (A3) `bge-m3` è MIT — non sono riuscito a verificare la licenza esatta nel review, va confermato
- (A4) AppleScript/JXA dictionary di DT4 resta stabile in patch release minor — storia DT3 dice di sì, DT4 è giovane, rischio non zero
- (A5) Costi GitHub Actions macOS sotto budget Vibrofer — da verificare

---

**Fine review.**

*Documento prodotto come output dell'attività di architectural review. Non sostituisce gli ADR formali, che vanno scritti separatamente come da §7. Tutte le raccomandazioni sono tracciabili al brief originale via riferimenti `§X.Y`.*
