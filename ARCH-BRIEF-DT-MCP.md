# Architecture Brief — MCP Connector per DEVONthink 4

**Documento**: ARCH-BRIEF-DT-MCP
**Versione**: 0.1 (draft per review architetturale)
**Data**: 29 aprile 2026
**Autore**: Stefano Ferri (CEO Vibrofer Srl) con assistenza Claude Opus 4.7
**Destinatario**: Cowork — review architetturale e refinement
**Scopo**: brief preliminare per la progettazione di un MCP connector di livello "best-in-class" per DEVONthink 4, da rifinire prima dell'implementazione

---

## 0. Come usare questo documento

Questo è un **architecture brief**, non una specifica chiusa. Contiene:

- Il contesto di partenza e i vincoli
- Una proposta architetturale a sei layer
- Le decisioni tecniche prese e le motivazioni
- I trade-off aperti che richiedono validazione
- Una roadmap 90 giorni indicativa

L'obiettivo del review è validare le scelte di alto livello, identificare gap, e produrre un ADR (Architecture Decision Record) finale che diventerà l'input per l'implementazione.

---

## 1. Executive Summary

Si propone un MCP server **dual-transport, multi-bridge, RAG-augmented** per DEVONthink 4, scritto in Python, con un layer di servizio orientato al risultato (non al wrapping 1:1 della scripting dictionary) e un sidecar locale di vector search che colma il gap semantico oggi non coperto da DEVONthink stesso.

**Punti di differenziazione rispetto a soluzioni esistenti** (es. `dvcrn/mcp-server-devonthink`):

1. Capability outcome-oriented, non wrapper di API
2. RAG locale con vector DB embedded (ChromaDB o Qdrant) per semantic search
3. Multi-bridge con failover (JXA primario, x-callback-url, DT Server)
4. Dual transport (stdio + Streamable HTTP con OAuth 2.1)
5. Audit log, dry-run obbligatorio per write ops, undo
6. Observability nativa (structured logging, OpenTelemetry, metriche)

Stack target: **Python 3.12 + FastMCP + ChromaDB + uv**.

Tempistica indicativa: **MVP in 12 settimane**, con GO/NO-GO decision point a fine settimana 2 e a fine settimana 6.

---

## 2. Contesto

### 2.1 Stato dell'arte

Esiste già un connector open source: [`dvcrn/mcp-server-devonthink`](https://github.com/dvcrn/mcp-server-devonthink) (TypeScript, 16 tool, ~60 star, GPL-3.0). Funziona, ma è essenzialmente un wrapper 1:1 della scripting dictionary di DT, single-bridge (JXA only), single-transport (stdio only), senza RAG né observability strutturata. È un buon punto di partenza concettuale ma non è "best-in-class".

### 2.2 Trend MCP 2026 (validati su fonti multiple)

- **Outcome-first tool design** invece di API-wrapping (Itential, AutoCon 4 — aprile 2026)
- **Aggressive surface area curation**: 5–15 tool ad alto valore, non 80 wrapper
- **Bounded context resources** per evitare hallucination da overload
- **OAuth 2.1 + PKCE** standard de facto per HTTP transport (CData 2026)
- **Tool search nativo** (Anthropic): definizioni deferite, non upfront
- **Streamable HTTP** sostituisce SSE per remote servers
- **Deterministic guardrails**: schema validation, idempotency, dry-run mandatory

### 2.3 Capability DEVONthink 4

| Capability | Disponibile | Note critiche |
|---|---|---|
| AppleScript / JXA dictionary | Sì | App name in DT4: `Application("DEVONthink")` (cambiato dalla 3.x) |
| Smart Rules event-driven | Sì | Niente Foundation framework affidabile dentro le rule |
| AI classica (See Also, Classify, Compare) | Sì | Locale, privacy-safe |
| AI generativa integrata (chat, summarize, transform) | Sì DT4 | Provider configurabili: OpenAI, Anthropic, Mistral, Ollama, LM Studio |
| Vector DB / semantic search nativi | **No** | Roadmap dichiarata da DEVONtechnologies (feb 2026) ma non disponibile |
| URL scheme `x-devonthink-item://` | Sì | Item links stabili tra macchine |
| DT Server web UI | Sì (edition Server) | Non è una vera REST API — HTML/login-based |

**Implicazione architetturale chiave**: il vector search è il gap reale che permette a un nuovo connector di superare quelli esistenti. Va costruito come sidecar locale, sincronizzato via smart-rule.

---

## 3. Obiettivi e non-obiettivi

### 3.1 Obiettivi

- **G1**: Connector best-in-class per ogni client MCP (Claude Desktop, Claude.ai web, Claude Code, Cursor, altri)
- **G2**: Privacy by design — nessun dato esce dalla macchina dell'utente per default
- **G3**: Production-grade: observability, audit, error handling, recovery
- **G4**: Sblocco di capability oggi non disponibili (semantic search, RAG multi-doc con citazioni)
- **G5**: Estendibilità: nuovi tool aggiungibili senza toccare il bridge layer
- **G6**: Compatibilità DT4.x con strategia di backward-compat verso DT3 ove possibile

### 3.2 Non-obiettivi (esplicitamente fuori scope per la v1)

- ✗ Supporto DEVONthink To Go (mobile)
- ✗ Multi-tenancy con utenti multipli su uno stesso server
- ✗ Sostituzione del DT Server web UI
- ✗ Modifica programmatica della UI di DEVONthink
- ✗ Integrazione con DEVONagent (motore di ricerca separato)
- ✗ Sync DEVONthink-side (DT gestisce il proprio sync)

---

## 4. Vincoli

### 4.1 Vincoli di piattaforma

- DEVONthink è macOS-only → server deve girare su macOS per il bridge JXA
- DEVONthink Pro deve essere in esecuzione (eccetto bridge DT Server)
- JXA è single-threaded sotto il cofano → necessario worker pool con backpressure

### 4.2 Vincoli di protocollo MCP

- stdio transport: **mai scrivere su stdout** (corrompe JSON-RPC). Logging solo su stderr o file
- Schema JSON Schema rigorosi per ogni tool
- Resource URI stabili e deterministici
- Tool description ≤ 2KB, server instructions ≤ 2KB (limite Claude Code)

### 4.3 Vincoli ambientali (utente target = Stefano/Vibrofer)

- macOS (Stefano usa Mac)
- DEVONthink 4 con database "Business" e "Privato" già strutturati
- Possibile esposizione remota via Cloudflare Tunnel (infra SATURNO già in essere)
- Stack preferito: Python (allineato a Hub Gestionale FastAPI), workflow vibe coding

---

## 5. Architettura proposta — vista a layer

```
┌─────────────────────────────────────────────────────────────┐
│ Tier 1 — Client AI                                          │
│ Claude Desktop, Claude.ai web, Claude Code, Cursor, altri   │
└────────────────────────┬────────────────────────────────────┘
                         │ JSON-RPC 2.0
┌────────────────────────┴────────────────────────────────────┐
│ Tier 2 — Transport dual-mode                                │
│  ┌──────────────────────┐  ┌─────────────────────────────┐ │
│  │ stdio                │  │ Streamable HTTP             │ │
│  │ Locale, subprocess   │  │ OAuth 2.1 + PKCE, scope     │ │
│  └──────────────────────┘  └─────────────────────────────┘ │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────────┐
│ Tier 3 — Capabilities MCP                                   │
│  Tools (azioni)  │  Resources (read-only)  │  Prompts       │
│  outcome-oriented│  bounded context        │  workflow tmpl │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────────┐
│ Tier 4 — Service Layer (la business logic)                  │
│  Hybrid Search │ RAG Q&A │ Summarize │ Bulk Ops │ Find Rel. │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────────┐
│ Tier 5 — Bridge Adapter (multi-channel + failover)          │
│  ┌────────────┐  ┌───────────────┐  ┌──────────────────┐   │
│  │ JXA Bridge │  │ x-callback-url│  │ DT Server HTTPS  │   │
│  │ pool async │  │ ops leggere   │  │ multi-host opzn. │   │
│  └────────────┘  └───────────────┘  └──────────────────┘   │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────────┐
│ Tier 6 — Target                                             │
│  DEVONthink 4 (macOS) — scripting dictionary, AI native     │
└─────────────────────────────────────────────────────────────┘
```

### 5.1 Tier 1 — Client AI

Standard MCP host. Nessun custom code lato client. Tutto il valore vive nel server.

### 5.2 Tier 2 — Transport dual-mode

Lo stesso binario espone due endpoint:

- **stdio**: per uso locale (Claude Desktop, Claude Code). Zero rete, autenticazione delegata al SO. Scenario primario in v1.
- **Streamable HTTP**: per uso remoto (Claude.ai web, app mobili). OAuth 2.1 con PKCE, refresh token rotation, scope granulari. Scenario v2.

**Decisione architetturale**: un solo codebase, transport selezionato via flag `--transport={stdio|http}`. Evita drift tra due implementazioni.

### 5.3 Tier 3 — Capabilities MCP

Le tre primitive del protocollo, ognuna usata per il proprio scopo nativo.

**Tools** (azioni con possibili side-effect):
- Schema-first con Pydantic v2
- Idempotency keys per write ops
- Dry-run mandatory per ops distruttive
- Output strutturato JSON

**Resources** (read-only browseable):
- URI pattern: `dt://database/{name}`, `dt://database/{name}/group/{path}`, `dt://record/{uuid}`, `dt://search?q={query}`
- Bounded: ogni resource ritorna ≤ 25K token (limite Claude Code default)
- Mai dump di interi database

**Prompts** (workflow templates):
- Esempi candidate: `research_synthesis`, `client_brief`, `weekly_review`, `tag_migration`
- Da definire dopo validazione use-case con utente

### 5.4 Tier 4 — Service Layer (il cuore del valore)

Tool outcome-oriented (NON wrapper 1:1 della dictionary). Lista MVP proposta (5-7 tool, allineata a best practice):

| Tool | Cosa fa | Bridge usato | Side-effect |
|---|---|---|---|
| `search` | Hybrid: BM25 nativo DT + vector RAG sidecar + re-ranking | JXA + RAG | No |
| `ask_database` | RAG Q&A multi-doc con citazioni stabili a UUID | RAG + JXA per fetch | No |
| `summarize_topic` | Riassunto multi-doc via DT4 native AI o LLM client | JXA (chiama AI nativa DT) | No |
| `find_related` | Wrap intelligente di "See Also" + "Compare" + filtri custom | JXA | No |
| `file_document` | Auto-classify + place + tag (con dry-run) | JXA | Sì |
| `bulk_apply` | Batch ops con preview, undo log, atomic transaction | JXA | Sì |
| `create_smart_rule` | Crea regole programmaticamente | JXA | Sì |

**Note sul design dei tool**:

- Ogni tool ha **descrizione MCP** ottimizzata per tool search (includere "quando usare", "non usare per", esempi).
- Ogni write tool ha parametro `dry_run: bool = True` come default sicuro.
- Output sempre `{success, data, warnings, audit_id}`.

### 5.5 Tier 5 — Bridge Adapter (il punto di forza tecnico)

Tre canali con interfaccia unificata `DEVONthinkAdapter`. Il service layer non sa quale bridge sta usando.

**Bridge primario — JXA Pool**

- Pool di N worker async che invocano `osascript -l JavaScript`
- Backpressure tramite semaphore (limite 4-8 worker concorrenti)
- Timeout per chiamata (default 5s, configurable)
- Retry con exponential backoff su errori transient
- Cache layer SQLite davanti per query read frequenti

```python
# Pseudocodice illustrativo
class JXABridge(DEVONthinkAdapter):
    def __init__(self, pool_size: int = 4):
        self.semaphore = asyncio.Semaphore(pool_size)
        self.cache = SQLiteCache(ttl=30)

    async def execute(self, script: str, cache_key: str | None = None) -> dict:
        if cache_key and (cached := self.cache.get(cache_key)):
            return cached
        async with self.semaphore:
            result = await self._run_osascript(script)
        if cache_key:
            self.cache.set(cache_key, result)
        return result
```

**Bridge fallback leggero — x-callback-url**

DT espone alcune operazioni come URL handler `x-devonthink-item://` e `x-devonthink://`. Latenza inferiore al JXA per operazioni semplici (open record, create from clipboard). Da usare per ops a bassa complessità dove latenza conta.

**Bridge opzionale multi-host — DT Server HTTPS**

Solo se l'utente ha l'edizione Server di DEVONthink. Permette il caso d'uso in cui il server MCP gira su macchina A e DEVONthink su macchina B. Nota: non è una vera REST API — sarà necessario un layer di scraping/parsing strutturato. Da considerare v2+.

**Selezione del bridge**

Ogni operazione dichiara una preferenza, il bridge manager sceglie:
1. Bridge dichiarato (se disponibile e healthy)
2. Bridge primario (JXA) se locale e DT in esecuzione
3. Errore strutturato con suggerimento al client

### 5.6 Tier 6 — Target

DEVONthink 4 (macOS).

---

## 6. Componenti cross-cutting

### 6.1 RAG Sidecar (l'innovazione centrale)

Processo Python separato dal server MCP, con cui comunica via Unix socket o named pipe.

**Responsabilità**:
1. Indicizzare i record DEVONthink in vector DB locale
2. Generare embedding multilingue (IT/EN/FR/DE) — modello candidato: `BAAI/bge-m3` o `intfloat/multilingual-e5-large`
3. Sync incrementale via smart rule DT che notifica il sidecar su modifica/aggiunta/cancellazione
4. Esporre `query(text, k, filters)` → `[(uuid, score, snippet)]`

**Stack**:
- ChromaDB embedded (zero-ops, single-user) o Qdrant (più scalabile, multi-collection)
- `sentence-transformers` per embedding
- File DB fuori dalla cartella DEVONthink per evitare lock contention
- Reconciliation job notturno: scansione completa, hash-based diff, riallineamento

**Privacy**: tutto locale, nessun embedding esce dalla macchina.

**Apertura**: il sidecar è opzionale. Se assente, `search` degrada a BM25-only via JXA.

### 6.2 Cache layer

SQLite con WAL mode, TTL configurabile per categoria:

| Categoria | TTL | Invalidazione esplicita |
|---|---|---|
| Risultati ricerca BM25 | 30s | Smart rule on change |
| Embedding di un record | ∞ (hash content-based) | Hash mismatch |
| Struttura database/group | 5 min | Smart rule on group change |
| Properties di record | 60s | Smart rule on update |

Riduce drasticamente le chiamate JXA (latenza tipica 200-500ms).

### 6.3 Observability

- **Structured logging** JSON su stderr (mai stdout in stdio mode). Schema: `{timestamp, level, tool, duration_ms, audit_id, error?}`
- **OpenTelemetry** tracing per chains tool→service→bridge→DT
- **Metriche** (in modalità HTTP): Prometheus endpoint con counter, histogram, gauge per tool calls, errors, latency, cache hit ratio
- **Health endpoints**: `/health` (liveness), `/ready` (DT in esecuzione + bridge OK + sidecar OK)

### 6.4 Audit log

Append-only SQLite separato. Ogni write ops ha:
- `audit_id` UUID
- timestamp ISO 8601
- principal (utente OAuth o "local")
- tool name + input JSON
- output hash
- durata
- before-state (per undo)

Retention configurabile (default 90 giorni). Permette compliance e undo selettivo.

### 6.5 Security & permission scope

OAuth scope granulari (per HTTP transport):
- `dt:read` — search, get, list, summarize
- `dt:write` — tag, rename, move (non delete)
- `dt:delete` — delete records
- `dt:bulk` — bulk operations
- `dt:admin` — create smart rules, modify databases

**Default**: solo `dt:read` concesso al primo consent. Scope più potenti richiedono escalation esplicita.

In stdio mode: scope determinato da config locale, no OAuth.

### 6.6 Error handling

Errori strutturati con codici tassonomici:
- `DT_NOT_RUNNING` — DEVONthink non aperto
- `DT_VERSION_INCOMPATIBLE` — versione DT non supportata
- `JXA_TIMEOUT` / `JXA_ERROR` — bridge JXA fallito
- `RECORD_NOT_FOUND` / `DATABASE_NOT_FOUND` — risorsa inesistente
- `PERMISSION_DENIED` — scope OAuth insufficiente
- `RATE_LIMITED` — troppe chiamate concorrenti
- `VALIDATION_ERROR` — schema input invalido

Ogni errore include `recovery_hint` testuale per il client.

---

## 7. Stack tecnologico raccomandato

| Componente | Tecnologia | Razionale |
|---|---|---|
| Linguaggio server | **Python 3.12** | Ecosistema RAG ricchissimo, allineato a Hub Gestionale, Pydantic v2 maturo |
| Framework MCP | **FastMCP** (SDK ufficiale Python) | Standard 2026, schema-first |
| Validazione | **Pydantic v2** | Schema MCP nativo, performance C-extension |
| Bridge JXA | `osascript` via `asyncio.subprocess` | Niente Node solo per JXA |
| Vector DB | **ChromaDB** embedded (v1) → Qdrant (v2 se serve) | Zero-ops in v1 |
| Embedding | `sentence-transformers` con `bge-m3` o `multilingual-e5-large` | Multilingue (IT/EN/FR/DE) |
| Cache | SQLite WAL | Già nello stack, niente Redis se single-user |
| Transport HTTP | `uvicorn` + streamable-http MCP SDK | Standard 2026 |
| Auth | `authlib` (OAuth 2.1 + PKCE) | Maturo |
| Packaging | `uv` + `pyproject.toml` | Mainstream Python 2026 |
| Distribuzione | `pipx install` o `.mcpb` desktop extension | Anthropic ha pubblicato `.mcpb` per install one-click |
| Test | `pytest` + `pytest-asyncio` | Standard |
| Observability | structured logging via `structlog`, OTel `opentelemetry-sdk` | Production-grade |

**Trade-off Python vs TypeScript**:
- **Pro Python**: ecosystem RAG, allineamento con stack utente, Pydantic v2 superiore a Zod per schema complessi
- **Contro Python**: overhead nel chiamare JXA (subprocess vs `osascript` library Node-side), packaging meno leggero per Claude Desktop

**Decisione raccomandata**: Python. Il vantaggio RAG è strutturale; il subprocess overhead è ammortizzabile con il pool worker.

---

## 8. Trade-off aperti / decisioni che richiedono review

### 8.1 ChromaDB vs Qdrant per il sidecar

ChromaDB è zero-ops, perfetto single-user. Qdrant scala meglio se in futuro si volesse multi-utente o persistence robusta. **Proposta**: ChromaDB in v1, abstract via interface, swappable in v2.

### 8.2 Sidecar embedded nel server vs processo separato

Un processo separato è più robusto (crash isolation) ma aggiunge complessità di IPC e deployment. **Proposta**: separato, comunicazione via Unix socket. Lifecycle gestito da un launcher script.

### 8.3 Sync incrementale via smart-rule vs polling vs filesystem watching

Smart rule è event-driven e nativo DT, ma può fallire silently. Polling è semplice ma inefficiente. Filesystem watching su `~/Library/Application Support/DEVONthink/` non funziona in modo affidabile. **Proposta**: smart rule + reconciliation notturno hash-based.

### 8.4 Scope dei tool MVP

7 tool sono molti per un MVP — raccomandazione standard 2026 è 3-5. **Proposta**: MVP con 3 tool (`search`, `ask_database`, `find_related`), tutti read-only. Write ops in fase 2.

### 8.5 Tool naming: verbose vs compact

`search_documents_in_database` vs `search`. Il primo aiuta l'LLM a discriminare, il secondo è più ergonomico. **Proposta**: nomi compatti, contesto nelle description (≤ 2KB).

### 8.6 Distribuzione: pipx vs .mcpb vs entrambi

`.mcpb` è Anthropic-ufficiale per Claude Desktop, install one-click. `pipx` è standard Python developer-friendly. **Proposta**: entrambi, build CI dual-target.

### 8.7 Backward compat con DT3

DT3 ha `Application("DEVONthink 3")`, DT4 ha `Application("DEVONthink")`. Detection runtime + adapter pattern? **Proposta**: detection runtime via osversion + DT version probe, supporto best-effort DT3 con feature gating (no AI generativa).

---

## 9. Roadmap 90 giorni (indicativa)

### Settimana 1-2 — Foundations

- Repo monorepo: `apps/server`, `apps/sidecar`, `libs/adapter`, `libs/schemas`
- CI: lint (ruff), test (pytest), build wheel
- FastMCP scaffold con stdio transport
- JXA bridge primitivo (single worker)
- 3 tool read-only: `list_databases`, `get_record`, `search` (BM25 only)
- Test su DEVONthink 4 reale

**GO/NO-GO checkpoint**: latenza JXA accettabile (<500ms p95)? Compatibilità DT4 confermata?

### Settimana 3-4 — Core tools + JXA pool

- Pool async JXA con backpressure
- Cache layer SQLite
- Tool: `find_related`, `summarize_topic` (chiama AI nativa DT4), `ask_database` (versione semplice senza vector)
- Schema validation Pydantic per ogni tool
- Structured logging stderr

### Settimana 5-6 — RAG sidecar

- Processo sidecar Python con ChromaDB
- Embedding pipeline `bge-m3`
- IPC server-sidecar via Unix socket
- Smart rule DT4 → sidecar via webhook locale
- Hybrid search nel tool `search`

**GO/NO-GO checkpoint**: vector search migliora significativamente la qualità delle risposte rispetto a BM25-only?

### Settimana 7-8 — Write ops + safety

- Tool: `file_document`, `bulk_apply`, `create_smart_rule`
- Dry-run mandatory
- Audit log SQLite append-only
- Undo selettivo
- Rate limiting

### Settimana 9-10 — HTTP transport + OAuth

- Streamable HTTP server (uvicorn)
- OAuth 2.1 con PKCE (authlib)
- Scope granulari + consent flow
- Deploy via Cloudflare Tunnel (riutilizzo infra SATURNO)
- Test da Claude.ai web

### Settimana 11-12 — Hardening

- OpenTelemetry tracing
- Performance benchmark (target: read p95 < 500ms, RAG p95 < 2s)
- `.mcpb` package + pipx package
- Documentazione utente
- Esempi di prompt patterns

---

## 10. Rischi e mitigazioni

| Rischio | Probabilità | Impatto | Mitigazione |
|---|---|---|---|
| JXA bridge rompe con update DT minor | Media | Alto | Test suite con JXA mocking, smoke test su ogni release DT, version probe |
| Embedding sync va out-of-sync con DT | Alta | Medio | Hash-based reconciliation notturno, full re-index on demand |
| OAuth setup complica adoption | Media | Medio | Stdio-only come default, OAuth come upgrade opzionale |
| ChromaDB lock contention | Bassa | Medio | DB fuori da cartella DT, file-locking esplicito, retry logic |
| Performance JXA peggiora con DB grandi (>100K record) | Alta | Alto | Cache aggressiva, vector search bypass per query semantiche, paginazione |
| AI nativa DT4 cambia interfaccia | Media | Medio | Adapter pattern sull'AI layer, feature gating |
| Smart rule trigger inaffidabile per sync sidecar | Media | Alto | Polling fallback ogni 5 min + reconciliation notturno |
| Conflitto licenza con `dvcrn/mcp-server-devonthink` (GPL) | Bassa | Alto | Implementazione clean-room senza guardare il codice esistente |

---

## 11. Aspetti operativi

### 11.1 Distribuzione

Tre target:
- **`.mcpb`**: install one-click in Claude Desktop
- **`pipx install vibrofer-dt-mcp`**: per developer / Claude Code
- **Docker**: `vibrofer/dt-mcp:latest` per HTTP transport (richiede però connessione SMB a una macchina con DT, scenario edge)

### 11.2 Configurazione

File `~/.config/vibrofer-dt-mcp/config.toml`:

```toml
[server]
transport = "stdio"   # o "http"
log_level = "info"

[bridge]
preferred = "jxa"     # jxa | xcallback | dtserver
jxa_pool_size = 4
jxa_timeout_ms = 5000

[sidecar]
enabled = true
embedding_model = "bge-m3"
vector_db = "chromadb"
vector_db_path = "~/.local/share/vibrofer-dt-mcp/vectors"

[security]
oauth_enabled = false  # true solo per HTTP
default_scopes = ["dt:read"]

[performance]
cache_enabled = true
cache_ttl_search_s = 30
cache_ttl_structure_s = 300
```

### 11.3 Setup utente

```bash
# Install
pipx install vibrofer-dt-mcp

# First run setup (interactive)
vibrofer-dt-mcp init

# Test connection
vibrofer-dt-mcp doctor

# Start server (stdio)
vibrofer-dt-mcp serve
```

Per Claude Desktop: aggiunto automaticamente a `claude_desktop_config.json` da `init`.

---

## 12. Aspetti che il review deve validare

Per Cowork o chiunque faccia il review architetturale, le aree dove serve più validazione:

1. **Modello del bridge multi-channel**: ha senso o è over-engineering per il single-user? Forse JXA-only in v1 è sufficiente.
2. **Ownership del RAG sidecar**: dentro lo stesso processo Python? Container separato? Ce lo chiediamo perché l'IPC aggiunge complessità.
3. **MVP scope**: 3 tool read-only è il giusto cut-off? O conviene puntare a 5 con almeno una write op per validare il dry-run pattern?
4. **DT Server bridge**: vale la pena progettarlo già nell'astrazione anche se non implementato in v1? Risk: over-design.
5. **Strategia di test**: come si testa un sistema che dipende da un'app GUI? Mocking di JXA è non banale.
6. **Versioning dell'API tool**: come gestire breaking changes nei tool quando sono già usati da prompt salvati? Versionamento per tool name (`search_v2`)? Header version?
7. **Scope OAuth**: 5 scope sono troppi pochi/troppi? Granularità giusta?
8. **Backward compat DT3**: vale lo sforzo o si lascia DT3-only ai connector esistenti?

---

## 13. Glossario

- **MCP**: Model Context Protocol, standard aperto Anthropic per AI ↔ tool integration
- **JXA**: JavaScript for Automation, alternativa a AppleScript per controllare app macOS
- **Bridge / Adapter**: layer che traduce le chiamate del service layer in operazioni concrete sul target
- **Sidecar**: processo separato che fornisce capability ausiliarie al server principale
- **RAG**: Retrieval-Augmented Generation
- **BM25**: algoritmo di ranking lessicale classico (full-text search)
- **PKCE**: Proof Key for Code Exchange, estensione OAuth per client pubblici
- **Streamable HTTP**: transport MCP HTTP-based, sostituisce SSE
- **`.mcpb`**: Desktop Extension package format di Anthropic per Claude Desktop

---

## 14. Riferimenti

### Specifiche e best practice MCP

- [Model Context Protocol — official docs](https://modelcontextprotocol.io)
- [Build an MCP server — official tutorial](https://modelcontextprotocol.io/docs/develop/build-server)
- [CData — MCP Server Best Practices for 2026](https://www.cdata.com/blog/mcp-server-best-practices-2026)
- [Itential — MCP Beyond the API Wrapper (AutoCon 4)](https://www.itential.com/blog/company/itential-mcp/designing-mcp-servers-for-infrastructure)
- [Truto — 2026 Architecture Guide for MCP](https://truto.one/blog/what-is-an-mcp-server-the-2026-architecture-guide-for-saas-pms)
- [The New Stack — 15 Best Practices for Building MCP Servers in Production](https://thenewstack.io/15-best-practices-for-building-mcp-servers-in-production/)

### DEVONthink

- [DEVONthink 4 — New Features](https://www.devontechnologies.com/apps/devonthink/new)
- [DEVONthink AI integration overview](https://www.devontechnologies.com/apps/devonthink/ai)
- [DEVONthink JXA reference (community)](https://bru6.de/jxa/automating-applications/devonthink/)
- [DEVONthink discourse — RAG roadmap statement (Feb 2026)](https://discourse.devontechnologies.com/t/rag-retrieval-augemented-generation-and-devonthink/86266/2)

### Connector esistente (per study only, NON per riuso codice)

- [`dvcrn/mcp-server-devonthink` GitHub](https://github.com/dvcrn/mcp-server-devonthink) — TypeScript, GPL-3.0, single-bridge

### Stack tecnologico

- [FastMCP — Python SDK](https://github.com/jlowin/fastmcp)
- [ChromaDB documentation](https://docs.trychroma.com/)
- [BAAI/bge-m3 multilingual embedding model](https://huggingface.co/BAAI/bge-m3)
- [Authlib OAuth 2.1 implementation](https://authlib.org/)

---

## 15. Appendice — Schema concettuale dei tool MVP

```python
# search
{
  "query": "vibrazioni HVAC datacenter",
  "databases": ["Business"],          # opzionale, default: tutti aperti
  "max_results": 10,
  "mode": "hybrid",                   # bm25 | semantic | hybrid
  "filters": {
    "tags": ["progetto-attivo"],
    "kind": ["pdf", "rtf"],
    "date_after": "2025-01-01"
  }
}
# →
{
  "success": true,
  "results": [
    {
      "uuid": "...",
      "name": "Keraglass — relazione tecnica REV03.pdf",
      "score": 0.87,
      "score_components": {"bm25": 0.74, "semantic": 0.91},
      "snippet": "...isolamento del condotto da 21m...",
      "path": "/Business/Progetti/Keraglass/...",
      "url": "x-devonthink-item://..."
    }
  ],
  "warnings": [],
  "audit_id": "uuid"
}

# ask_database
{
  "question": "Quali isolatori abbiamo proposto a Keraglass per i trespoli?",
  "databases": ["Business"],
  "max_chunks": 8,
  "include_citations": true
}
# →
{
  "success": true,
  "answer": "Per i trespoli T1, T2, T3 sono stati proposti...",
  "citations": [
    {"uuid": "...", "name": "...", "snippet": "...", "url": "x-devonthink-item://..."}
  ],
  "audit_id": "uuid"
}

# file_document
{
  "record_uuid": "...",
  "dry_run": true,                    # default true
  "auto_classify": true,
  "auto_tag": true,
  "destination_hint": null            # opzionale, override
}
# →
{
  "success": true,
  "preview": {
    "destination_group": "/Business/Clienti/Keraglass",
    "tags_to_add": ["progetto-attivo", "2026"],
    "tags_to_remove": [],
    "rename_to": null
  },
  "would_apply": true,
  "audit_id": "uuid"
}
```

---

**Fine documento.**

*Questo brief è un'ipotesi di lavoro. Non è una specifica implementativa. Tutte le decisioni etichettate "Proposta" sono validabili dal review architetturale.*
