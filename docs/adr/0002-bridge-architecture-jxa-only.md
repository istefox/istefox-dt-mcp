# ADR 0002 — Bridge architecture: JXA-only in v1 con interfaccia astratta multi-bridge ready

- **Status**: Accepted
- **Date**: 2026-04-30
- **Decisori**: Stefano Ferri
- **Supersedes**: parte di brief §5.5 (architettura tre-bridge)
- **Fonte**: REVIEW_ADR §2 P1, §7 ADR-001

---

## Contesto

Il brief proponeva tre bridge concorrenti con failover (`JXA`, `x-callback-url`, `DT Server HTTPS`). Per il caso d'uso single-user, single-device dichiarato come target v1 (brief §4.3), la review ha identificato questo come over-engineering: JXA copre il superset funzionale, x-callback-url ha latenza inferiore solo su una manciata di operazioni, DT Server è giustificato solo da scenari multi-host classificati come v2+.

## Decisione

In v1:

- **Una sola implementazione concreta**: `JXAAdapter`
- **Interfaccia astratta** `DEVONthinkAdapter` (ABC) definita esplicitamente con tutti i metodi async necessari
- **No implementazione** di `XCallbackAdapter` né `DTServerAdapter`
- **ADR contract documentato**: input/output schemas, error semantics, idempotency requirements

## Razionale

- **Riduzione delivery time**: ~1.5 settimane risparmiate (review §2 P1)
- **Matrice di test ridotta**: una sola implementazione → meno superficie di bug
- **YAGNI**: failover automatico e operazioni a bassa latenza via x-callback non hanno valore dimostrato per il single-user con DT locale
- **Reversibilità garantita**: l'astrazione ABC permette di aggiungere implementazioni future senza refactor del service layer

## Criteri di promozione futura

### `XCallbackAdapter` (v1.5)
Aggiungere solo se profiling identifica bottleneck quantitativo:
- ≥ 30% delle chiamate concentrate su 3-5 operazioni candidabili (open record, create-from-clipboard)
- Misurazione latenza JXA p95 > 800ms su quelle operazioni specifiche

### `DTServerAdapter` (v2+)
Aggiungere solo se emerge requirement concreto:
- Multi-host scenario reale (server MCP su macchina diversa da DT)
- Spike di 1 settimana preliminare per validare feasibility (DT Server è HTML-based, non REST)

## Contratto `DEVONthinkAdapter`

Interfaccia formale documentata in `libs/adapter/src/istefox_dt_mcp_adapter/contract.py`. Metodi async previsti per MVP:

```
async def list_databases() -> list[Database]
async def get_record(uuid: str) -> Record
async def search(query: str, **filters) -> list[SearchResult]
async def find_related(uuid: str, k: int = 10) -> list[RelatedResult]
async def apply_tag(uuid: str, tag: str, *, dry_run: bool = True) -> TagResult
async def move_record(uuid: str, dest_group: str, *, dry_run: bool = True) -> MoveResult
```

Tutti i metodi:
- Ritornano modelli Pydantic v2 (`libs/schemas/`)
- Sollevano errori strutturati (`errors.py` taxonomy)
- Sono idempotenti dove semanticamente possibile
- Validano input al confine (no trust assumption)

## Conseguenze

- ✅ Delivery accelerato di ~1.5 settimane
- ✅ Codebase più piccolo, maintenance ridotta
- ✅ Estensibilità preservata via ABC
- ⚠ Nessun failover automatico in v1 → mitigato con retry exponential backoff su JXA (max 3 tentativi)
- ⚠ Operazioni "open record" via JXA hanno latenza ~200-300ms (vs ~50ms via x-callback) → accettabile per MVP

## Riferimenti

- REVIEW_ADR.md §2 P1, §7 ADR-001
- Brief §5.5 (architettura originale tre-bridge)
- ADR 0001 (stack)
