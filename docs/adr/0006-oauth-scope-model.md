# ADR 0006 — OAuth scope model: 3 scope + database-scoping in tool params

- **Status**: Accepted
- **Date**: 2026-05-08
- **Decisori**: Stefano Ferri
- **Supersedes**: brief §5.2 (proposta 5 scope `dt:read`/`dt:write`/`dt:delete`/`dt:bulk`/`dt:admin`)
- **Fonte**: REVIEW_ADR §2 P6, §7 ADR-006
- **Related**: ADR-001 (stack: OAuth via authlib), ADR-007 (DT4-only)
- **Prerequisito di**: implementazione HTTP transport (target 0.4.0)

---

## Contesto

Il brief proponeva 5 scope OAuth distinti:

| Scope | Copre |
|---|---|
| `dt:read` | search, get, list, summarize, ask_database, find_related |
| `dt:write` | tag, rename, move, file_document |
| `dt:delete` | trash, permanent delete |
| `dt:bulk` | bulk_apply (batch ops) |
| `dt:admin` | create_smart_rule, modify database settings |

In aggiunta era stata prospettata granularità **per database** (es. `dt:read:business` vs `dt:read:privato`).

La review architetturale ha rifiutato entrambe le proposte sulla base di tre argomenti: (1) ridondanza per single-user target, (2) frizione nel consent flow, (3) impossibilità di scope statici per database dinamici.

## Decisione

**Tre scope OAuth**: `dt:read`, `dt:write`, `dt:admin`. Database-scoping spostato fuori da OAuth, gestito come selezione persistita lato server e applicata come filtro automatico su ogni tool call.

### Modello scope finale

| Scope | Copre | Default consent |
|---|---|---|
| `dt:read` | `search`, `find_related`, `ask_database`, `summarize_topic`, `list_databases`, ogni read tool futuro | Sì (al primo consent) |
| `dt:write` | `file_document`, `bulk_apply`, ogni write tool futuro (incluso delete via trash, rename, move, tag) | No (escalation esplicita richiesta) |
| `dt:admin` | `create_smart_rule`, modifica settings database, configurazione server | No (escalation esplicita richiesta) |

### Database-scoping al di fuori dello scope OAuth

- Il consent UI mostra: *"Il client può accedere a questi database: [Business] [Privato] [Inbox] ..."* con checkbox per database
- La selezione è persistita **lato server** in `~/Library/Application Support/istefox-dt-mcp/consent.db` (SQLite), non nell'OAuth token
- Ogni tool call applica automaticamente il filtro: i database non selezionati sono invisibili (come se non esistessero)
- Database creati **dopo** il consent: il primo tentativo di accesso restituisce errore strutturato `RECONSENT_REQUIRED` con `recovery_hint: "Database '<name>' creato dopo il consent. Apri <consent_url> per autorizzarlo."`

### Errori strutturati

```json
{
  "error_code": "OAUTH_INSUFFICIENT_SCOPE",
  "required_scope": "dt:write",
  "granted_scopes": ["dt:read"],
  "recovery_hint": "Il tool 'file_document' richiede scope dt:write. Riesegui il consent flow."
}
```

```json
{
  "error_code": "RECONSENT_REQUIRED",
  "database_name": "Nuovo Cliente",
  "database_uuid": "ABCD-1234",
  "recovery_hint": "Database 'Nuovo Cliente' non è nel set autorizzato. Apri <consent_url> per aggiungerlo."
}
```

## Razionale

### Perché 3 scope e non 5

1. **Merge `dt:delete` + `dt:bulk` in `dt:write`**: distinguerli aggiunge friction senza aumentare la sicurezza reale. Chi ha `dt:write` può rinominare a `_TRASH_` e archiviare massivamente — l'effetto utente è simile. La protezione effettiva viene da `dry_run` mandatory + audit log + undo (ADR-004), non dalla granularità scope.

2. **Single-user target v1**: il brief §4.3 e l'analisi della review concordano sul single-user come scenario primario. 5 scope per single-user creano consent dialog densi (5 toggle) senza valore aggiunto.

3. **Consent flow chiaro**: 3 scope = 3 etichette ovvie ("Leggi", "Scrivi", "Amministra"). 5 scope obbligano l'utente a comprendere la differenza tra `dt:write` e `dt:bulk` — info architetturale che non dovrebbe trapelare nel consent UI.

### Perché database-scoping fuori da OAuth

1. **Database dinamici vs scope statici**: l'utente crea/rinomina/elimina database in DT4 in qualsiasi momento. Gli scope OAuth sono stringhe statiche emesse al consent time. Mappare database → scope produrrebbe drift inevitabile (token con scope `dt:read:foo` quando "foo" è stato rinominato in "bar").

2. **Token più piccoli**: scope `dt:read:business dt:read:privato dt:write:business ...` esplodono linearmente con N database. Una selezione persistita server-side resta O(1) sul token.

3. **Ricontrollo esplicito su nuovi DB**: il flag `RECONSENT_REQUIRED` è un evento esplicito che obbliga l'utente a una decisione consapevole, invece di un comportamento implicito ("database appena creato eredita scope esistenti").

### Confidence

**Media-alta**. Assunzione: il single-user resta dominante v1. Se v2 introduce multi-user reale (più colleghi su SATURNO via Cloudflare Tunnel), valutare:

- Aggiunta di `dt:bulk` come scope distinto (limite alle operazioni batch >N record)
- Per-user database ACL (ortogonale agli scope OAuth)

## Conseguenze

- ✅ Consent UI con 3 toggle chiari invece di 5
- ✅ Token OAuth O(1) rispetto al numero di database
- ✅ Gestione naturale di database creati dopo il consent (RECONSENT_REQUIRED)
- ✅ Codice tool decoratable con `@requires_scope("dt:write")` (singolo decorator, niente combinazione di scope)
- ⚠ Granularità scope persa: chi ottiene `dt:write` può fare anche bulk → mitigato da `dry_run` mandatory (ADR-004) + audit log + undo
- ⚠ Selezione database persistita server-side richiede storage SQLite addizionale → trascurabile (~10KB)
- ⚠ Logica `RECONSENT_REQUIRED` deve essere implementata su tutti i tool path (lookup database al pre-flight) → factor in middleware MCP

## Implementazione (sketch — implementation deferred a 0.4.0)

```python
# apps/server/src/istefox_dt_mcp_server/auth/scope.py
from enum import StrEnum

class Scope(StrEnum):
    READ = "dt:read"
    WRITE = "dt:write"
    ADMIN = "dt:admin"

# Tool decorator
def requires_scope(scope: Scope):
    def decorator(fn):
        async def wrapper(*args, **kwargs):
            ctx = get_request_context()
            if scope not in ctx.granted_scopes:
                raise InsufficientScopeError(
                    required=scope,
                    granted=ctx.granted_scopes,
                )
            return await fn(*args, **kwargs)
        return wrapper
    return decorator

# Usage
@mcp.tool()
@requires_scope(Scope.WRITE)
async def file_document(...):
    ...
```

```python
# apps/server/src/istefox_dt_mcp_server/auth/consent.py
class ConsentStore:
    """Persistent per-database authorization, decoupled from OAuth tokens."""

    async def authorized_databases(self, principal_id: str) -> set[str]:
        """Return UUIDs of databases the principal has authorized."""
        ...

    async def filter_visible(
        self, principal_id: str, all_dbs: list[Database]
    ) -> list[Database]:
        authorized = await self.authorized_databases(principal_id)
        return [db for db in all_dbs if db.uuid in authorized]

    async def check_or_raise(self, principal_id: str, db_uuid: str) -> None:
        if db_uuid not in await self.authorized_databases(principal_id):
            raise ReconsentRequiredError(database_uuid=db_uuid)
```

## Fuori scope

- **Implementazione HTTP transport** (uvicorn + streamable-http MCP SDK): trattata in ADR separato quando target 0.4.0 sarà attivato
- **OAuth callback URL design** (loopback `localhost:N`, custom scheme, Cloudflare Tunnel domain): trattato in ADR HTTP transport (REVIEW_ADR §3 gap #12)
- **Rate limiting per scope** (token bucket): rinviato a ADR-014
- **Per-user multi-tenancy** (più colleghi Vibrofer su stesso server): out of scope v1, decisione esplicita di mantenere single-user

## Riferimenti

- REVIEW_ADR.md §2 P6 (proposta originale validata)
- REVIEW_ADR.md §7 ADR-006 (placeholder)
- Brief §5.2 (proposta 5 scope superseded)
- Brief §4.3 (single-user target v1)
- ADR-001 (stack: `authlib` per OAuth 2.1 + PKCE)
- ADR-004 (test strategy: scope-aware contract test)
