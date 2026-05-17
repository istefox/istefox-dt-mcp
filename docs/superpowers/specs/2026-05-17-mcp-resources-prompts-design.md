# MCP Resources + Prompts ("protocol completeness") — Design Spec

- **Status**: proposed 2026-05-17
- **Target version**: 0.5.0
- **Owner**: istefox
- **Scope**: 3 read-only `dt://` MCP Resources (bounded, consent-gated), 2 MCP Prompts (template-only), `safe_resource` security helper, ADR-0009
- **Related**: CLAUDE.md §2.2 (resource URI stabili/deterministici, ≤25K token), ADR-0006 (OAuth scope model — Accepted), ADR-0005 (test strategy 4-tier — Accepted)
- **Out of scope**: nuovi tool, nuovi script JXA, nuovi metodi adapter astratti, nuove dipendenze runtime, `dt://search/*` (URI non-deterministico), enumerazione record di un DB, `total_chars` preciso (richiederebbe JXA nuovo)

---

## 1. Context

`istefox-dt-mcp` è a v0.4.0 in produzione: 7 tool, transport stdio+HTTP, OAuth 2.1+PKCE, ConsentStore per-DB. Manca però l'unica grande superficie del protocollo MCP non coperta: **zero Resources e zero Prompts** registrati (`grep` conferma nessun `@mcp.resource` / `@mcp.prompt`). Il CLAUDE.md §2.2 impone esplicitamente "Resource URI stabili e deterministici (`dt://...`)" e "Resource bounded: ogni resource ≤ 25K token. Mai dump di interi database" — un vincolo finora non implementato.

Driver per 0.5.0:
- **Completezza protocollo**: i client MCP possono referenziare contenuti DT come *contesto* (resource) senza spendere una tool call, e disporre di workflow pronti (prompt). È il passo che rende il plugin un cittadino MCP completo.
- **Costo controllato**: la direzione scelta dall'utente è un bundle 0.5.0 *coeso* e *leggero*. Questa feature si realizza interamente per **riuso** dell'infrastruttura 0.4.0: zero dipendenze nuove, zero JXA nuovi, zero metodi adapter nuovi.

Asset esistenti riusati:
- `adapter.list_databases()`, `adapter.get_record(uuid)` (→ `Record.database_uuid`, 0.4.0), `adapter.get_record_text(uuid, max_chars)` (troncamento già lato JXA).
- `auth/scope.py` (`current_context`, `current_scopes`, `Scope`), `auth/consent.py` (`check_or_raise`, `ReconsentRequiredError`), `audit.py` (`append`, `timer`), `deps.translator`.
- Pattern `register(mcp, deps)` (es. `tools/find_related.py`) e filtro consent (`tools/list_databases.py`).

Nulla per Resources/Prompts oggi: vanno introdotti il package `resources/`, il package `prompts/`, e un helper di sicurezza dedicato.

## 2. Goals

- **G1**: 3 resource read-only registrate: `dt://databases`, `dt://record/{uuid}/metadata`, `dt://record/{uuid}/text`.
- **G2**: Ogni resource è **deterministica e stabile**: stesso URI + stesso stato DT ⇒ output byte-identico (chiavi ordinate, ordinamenti espliciti). `{uuid}` = UUID DEVONthink (identità canonica già in uso).
- **G3**: Ogni resource è **bounded ≤ 25K token** con troncamento esplicito e flag `truncated`; mai dump di un intero database.
- **G4**: Le read di resource passano per lo **stesso gate** dei tool: scope `dt:read` + ConsentStore per-DB. Una read non autorizzata **solleva** (errore di protocollo MCP), non ritorna un envelope finto-success, e viene comunque **auditata**.
- **G5**: 2 prompt registrati (`weekly_review`, `triage_inbox`), soli template che orchestrano i tool esistenti; user-facing in italiano (default), `lang="en"` commuta.
- **G6**: ADR-0009 scritto (Accepted) a documentare la decisione architetturale; segnalazione esplicita in chat e nei commit (CLAUDE.md §7/§8).
- **G7**: Copertura test 4-tier (ADR-0005): unit (bound, determinismo, consent/scope, stdio), contract via cassette esistenti, integration su fixture DT, +1 step smoke E2E.
- **G8**: Zero dipendenze runtime nuove; `contract.py` e gli script JXA invariati.

## 3. Non-goals

- **NG1**: Nuovi tool o nuove capability di scrittura. Questo bundle è puramente read/template.
- **NG2**: `dt://search/{query}` o qualsiasi URI il cui contenuto dipende da ranking/stato variabile — viola §2.2 (determinismo) ed è già coperto dal tool `search`.
- **NG3**: Resource composita `dt://record/{uuid}` (metadata+full text in uno) — più difficile da bound; lo split metadata/text è strettamente migliore.
- **NG4**: Enumerazione dei record di un database via resource (es. `dt://database/{name}/records`) — vietata da §2.2 ("mai dump di interi database").
- **NG5**: `max_chars` configurabile per-request via query param — renderebbe lo stesso URI non-deterministico. Resta costante di modulo.
- **NG6**: `total_chars` esatto del record — richiederebbe modificare `get_record_text.js` (JXA nuovo). Deferito (YAGNI); si usa l'euristica `truncated = (len(text) == max_chars)`.
- **NG7**: Più di 2 prompt. `find_related_synthesis` (wrapper sottile) e `summarize_database` (ridondante con `summarize_topic`) tagliati.

## 4. Architecture

### 4.1 Superficie

```
MCP client
   │  resources/list, resources/read            prompts/list, prompts/get
   ▼                                                   ▼
FastMCP server (server.py)
   ├── @mcp.resource("dt://databases")            ┌── @mcp.prompt weekly_review
   ├── @mcp.resource("dt://record/{uuid}/metadata")│   @mcp.prompt triage_inbox
   ├── @mcp.resource("dt://record/{uuid}/text")    └── (solo template, nessun deps)
   │        │
   │        ▼  safe_resource(...)  ── NON safe_call
   │   ┌─────────────────────────────────────────────┐
   │   │ scope gate (Scope.READ) ─ current_scopes()   │
   │   │ consent gate ─ consent.check_or_raise(db_uuid)│  (solo resource record)
   │   │ audit.append(tool_name="resource:dt://…")     │
   │   │ translator → raise (no envelope)              │
   │   └─────────────────────────────────────────────┘
   │        │
   ▼        ▼
adapter.list_databases() / get_record() / get_record_text()   (riuso, invariati)
```

### 4.2 Perché `safe_resource` e non `safe_call`

`safe_call` (`apps/server/src/istefox_dt_mcp_server/tools/_common.py:194`) è generico su `OutT: Envelope[Any]` e su **ogni** ramo (scope denied, reconsent, AdapterError, ok) fa `return output_factory(success=…, …)`. Una MCP resource però restituisce **contenuto raw** (stringa JSON), non un `Envelope`; in caso di errore il protocollo MCP si aspetta che la read **sollevi**, non che produca un body `{"success": false}`. Riusare `safe_call` significherebbe (a) infilare un envelope errato nel body della resource, (b) non sollevare mai sugli errori. Quindi:

`safe_resource` (nuovo, `resources/_common.py`, ~60 LOC) **riusa gli stessi mattoni** di `safe_call` ma con contratto diverso (raise invece di envelope):

1. `current_context()` / `current_scopes()` (`auth/scope.py`) — stessa sorgente scope dei tool. `ctx is None` (stdio / unit test / script) ⇒ `local-stdio` accesso pieno, identico a `list_databases.py` e `scope.py`.
2. Gate `Scope.READ`. Se assente: `deps.audit.append(tool_name="resource:<uri>", input_data={"uri":…}, output_data=None, duration_ms=0.0, error_code=OAUTH_INSUFFICIENT_SCOPE)` poi **`raise`** (FastMCP → errore MCP). Parità con `safe_call` ll. 234-252 ma con raise.
3. Solo resource record: risolvi `database_uuid` (vedi §4.4) e `deps.consent.check_or_raise(principal_id, database_uuid, database_name=…)`. Su `ReconsentRequiredError`: audit con `error_code=RECONSENT_REQUIRED` poi **re-raise**.
4. Successo: `with timer() as t: …; deps.audit.append(tool_name="resource:<uri>", input_data={"uri":…}, output_data=<summary piccolo, NON il body intero>, duration_ms=t.duration_ms)`. `structlog.contextvars.bind_contextvars` come `safe_call` l. 224.
5. `AdapterError` → `deps.translator.message_it(...)` ma **raise** un'eccezione pulita, non un envelope.

`tool_name="resource:<uri>"` sfrutta il fatto che la colonna `tool_name` dell'audit è free-text (`audit.py`) ⇒ **nessuna migrazione audit**, le read resource sono interrogabili nello stesso log append-only.

### 4.3 Le 3 resource

| URI | Payload | Strategia bound | Adapter |
|---|---|---|---|
| `dt://databases` | `{databases:[{uuid,name,path,is_open,record_count}], truncated:bool}` ordinato per `uuid` | nessun contenuto/enumerazione record; backstop `bound_json` | `list_databases()` + `consent.filter_visible(principal, dbs)` (come `list_databases.py`) |
| `dt://record/{uuid}/metadata` | `Record` senza body: `{uuid,name,kind,location,path,reference_url,created,modified,added,tags,size,word_count,database_uuid,tags_truncated:bool}` | shape fissa; tag cappati a 100 con `tags_truncated` | `get_record(uuid)` |
| `dt://record/{uuid}/text` | `{uuid,text,truncated:bool,returned_chars:int}` | `max_chars=RESOURCE_MAX_CHARS` (costante) passato a `get_record_text`; troncamento già lato JXA | `get_record(uuid)` → consent → `get_record_text(uuid, RESOURCE_MAX_CHARS)` |

Smart group / immagine senza OCR ⇒ `text=""` (già gestito da `get_record_text.js`). `reference_url` ha già il fallback `x-devonthink-item://{uuid}` (in `get_record.js`).

### 4.4 Consent per le resource record

`get_record(uuid)` ritorna `Record.database_uuid` (0.4.0). Flusso `dt://record/{uuid}/metadata`: `get_record` → `check_or_raise(principal, record.database_uuid, record.…)` → serializza. Flusso `dt://record/{uuid}/text`: `get_record` (per ottenere `database_uuid`) → `check_or_raise` → `get_record_text`. Due round-trip JXA (entrambi già esistenti e cache-ati): correttezza prima della micro-ottimizzazione. Estendere `get_record_text.js` per restituire anche `database_uuid` è considerato e **rifiutato** (JXA nuovo = superficie di manutenzione; deferire se la latenza lo richiede).

### 4.5 Enforcement bound (rischio §2.2)

In `resources/_common.py`:

```
RESOURCE_MAX_CHARS = 60_000          # ≈17K token @ 3.5 char/token (conservativo), <25K
RESOURCE_JSON_BUDGET_CHARS = 80_000  # tetto assoluto del payload serializzato

def bound_json(payload: dict) -> str:
    s = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    if len(s) > RESOURCE_JSON_BUDGET_CHARS:
        # difesa in profondità (dovrebbe essere irraggiungibile coi cap per-campo):
        # tronca payload["text"], setta payload["truncated"]=True, ri-serializza
        ...
    return s
```

Il bound è garantito da: (a) `get_record_text(max_chars=60_000)` lato JXA, (b) `dt://databases` non porta mai contenuto, (c) backstop `RESOURCE_JSON_BUDGET_CHARS`. **Rischio dichiarato**: la stima token è euristica; testo token-dense (CJK, blob base64-like) potrebbe avvicinarsi al limite. Mitigazione: 60K char = ~30% di headroom sotto i 25K + un test che asserisce il bound (§7).

### 4.6 Prompts

Soli template (FastMCP `@mcp.prompt`), nessun deps/JXA/adapter/audit. User-facing in italiano (default), `lang="en"` commuta. Nomi tool nel testo restano in inglese.

- **`weekly_review`** — args `databases: str | None = None` (nomi separati da virgola), `lang: str = "it"`. Istruisce il modello a: `list_databases` se `databases` non dato → `search`/`summarize_topic` per attività recente per DB → `find_related` per cluster → digest settimanale strutturato.
- **`triage_inbox`** — args `inbox_database: str = "Inbox"`, `lang: str = "it"`, `apply: bool = False`. Enumera candidati (search ampia scoped all'inbox), per ognuno `file_document` con **`dry_run=true`** e mostra la preview; solo se `apply=True` spiega il flusso preview-token → `dry_run=false` (rispetta il contratto safety dei write tool).

Solo 2 per anti-bloat: ogni prompt è costo di contesto sempre-visibile nel client. Coprono i due workflow ricorrenti a più alto valore (review periodica, triage inbox) ed esercitano sia il path read sia il path safe-write. Altri prompt si aggiungono solo se l'uso reale lo richiede (YAGNI).

## 5. ADR-0009

`docs/adr/0009-mcp-resources-prompts.md`, formato come `0006-oauth-scope-model.md` (Status/Date/Decisori/Fonte → Contesto → Decisione → Razionale → Conseguenze → Riferimenti). **Decisione**: *adottare le superfici MCP Resources e Prompts. Resources `dt://` read-only, URI deterministici e stabili basati sullo UUID DEVONthink, bounded ≤25K token via troncamento esplicito, mai dump di database. Le read di resource passano per lo stesso gate scope `dt:read` + ConsentStore dei tool tramite l'helper `safe_resource` (non `safe_call`, perché le resource restituiscono contenuto raw e devono sollevare su errore). Prompts soli template che orchestrano i tool esistenti, zero dipendenze/JXA. Set minimo: 3 resource, 2 prompt.*

## 6. File da creare / modificare

**Creare:**
- `apps/server/src/istefox_dt_mcp_server/resources/__init__.py`
- `apps/server/src/istefox_dt_mcp_server/resources/_common.py` — `safe_resource`, `bound_json`, `RESOURCE_MAX_CHARS`, `RESOURCE_JSON_BUDGET_CHARS`
- `apps/server/src/istefox_dt_mcp_server/resources/dt_resources.py` — `register(mcp, deps)` con i 3 `@mcp.resource(...)`
- `apps/server/src/istefox_dt_mcp_server/prompts/__init__.py`
- `apps/server/src/istefox_dt_mcp_server/prompts/dt_prompts.py` — `register(mcp, deps)` con `weekly_review` + `triage_inbox`
- `docs/adr/0009-mcp-resources-prompts.md`

**Modificare:**
- `libs/schemas/src/istefox_dt_mcp_schemas/tools.py` — append `DatabaseListResource`, `RecordMetadataResource`, `RecordTextResource` (riusano `common.Record`/`Database`, non li ridefiniscono)
- `apps/server/src/istefox_dt_mcp_server/server.py` — import + `resources.dt_resources.register(mcp, deps)` e `prompts.dt_prompts.register(mcp, deps)` dopo riga 65 (prima di `register_oauth_routes` riga 70); `SERVER_VERSION = "0.5.0"` (riga 28); +1 frase a `SERVER_INSTRUCTIONS` (riga 31) sui `dt://`

**Invariati (vincolo lean):** `libs/adapter/.../contract.py`, tutti gli script JXA in `libs/adapter/.../scripts/`, i 7 tool esistenti, `apps/server/pyproject.toml` (nessuna dipendenza nuova).

## 7. Test strategy (ADR-0005 4-tier)

- **Unit** (`tests/unit/`, AsyncMock adapter, Ubuntu, ogni push):
  - `test_resources_bounded`: mock `get_record_text` ritorna 10 MB ⇒ body ≤ `RESOURCE_JSON_BUDGET_CHARS` e `truncated is True` (test di enforcement §2.2).
  - `test_resources_uri_determinism`: doppia read dello stesso URI con stato mock identico ⇒ output byte-identico.
  - `test_resources_consent`: contesto HTTP senza il `database_uuid` autorizzato ⇒ `safe_resource` solleva `ReconsentRequiredError` + audit row `RECONSENT_REQUIRED`; senza `dt:read` ⇒ raise + audit `OAUTH_INSUFFICIENT_SCOPE` (parità con `test_safe_call_*`).
  - `test_resources_scope_stdio`: `current_context() is None` ⇒ accesso pieno, audit scritto.
  - `test_prompts`: ogni prompt con/senza args ⇒ struttura attesa, italiano di default, `lang="en"` commuta, arg-type invalidi rifiutati dalla signature.
- **Contract/VCR** (`tests/contract/`): nessuna cassetta nuova — guida le resource attraverso le cassette esistenti di `get_record`/`get_record_text`/`list_databases` per provare che il layer resource non rompe il contratto bridge.
- **Integration** (macOS, PR→main + nightly): leggi `dt://databases`, scegli un UUID noto dalla fixture, leggi `/metadata` e `/text`, asserisci schema-valid + bounded.
- **Smoke E2E** (`scripts/smoke_e2e.py`): +1 step dopo `find_related` — UUID del primo hit ⇒ esercita metadata+text su DT reale, stampa latenza, asserisci body ≤ budget.
- **Gate finali**: `ruff` + `black` + `mypy apps libs` clean; CI Ubuntu (lint+mypy+unit+contract) + macOS-14 (import-and-bundle) verdi.

## 8. Build sequence (~1 settimana, slice = PR coerenti)

1. **PR1 — ADR + schemi** (~0.5 g): ADR-0009 Accepted + 3 modelli Pydantic + test validazione schema. *Blocca il contratto prima del wiring.*
2. **PR2 — `safe_resource` + `dt://databases`** (~1.5 g): package `resources/`, `_common.py`, resource più semplice (no content), wiring `server.py`, bump 0.5.0. Test consent/scope/determinismo. *Plumbing sicurezza end-to-end, blast radius minimo.*
3. **PR3 — resource record metadata+text** (~1.5 g): le 2 resource record + flusso get_record→consent→get_record_text. Test bound-size + troncamento (guard §2.2) + contract via cassette esistenti. *Slice a rischio più alto, isolato.*
4. **PR4 — prompts** (~1 g): package `prompts/`, 2 prompt, wiring. Test render/lang/args. *Indipendente, parallelizzabile dopo PR1.*
5. **PR5 — integration + smoke + release** (~1 g): assert integration su fixture DT, +1 step smoke E2E, update `docs/architecture.md` + handoff/memory, `chore: release v0.5.0` (pipeline esistente: bump 2 file + CHANGELOG → release.yml → publish-registry auto).

Dipendenze: PR1→PR2→PR3; PR4 dopo PR1 (parallelo); PR5 ultimo.

## 9. Open questions

Nessuna. Le scelte potenzialmente aperte sono state chiuse esplicitamente come Non-goals (NG2/NG3/NG5/NG6/NG7) o decisioni di design (§4.2 `safe_resource`, §4.4 consent a due round-trip, §4.5 euristica bound).
