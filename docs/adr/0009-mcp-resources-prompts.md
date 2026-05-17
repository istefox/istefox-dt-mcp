# ADR-0009: MCP Resources + Prompts surfaces (bounded, consent-gated)

- **Status**: Accepted
- **Date**: 2026-05-17
- **Decisori**: istefox
- **Fonte**: docs/superpowers/specs/2026-05-17-mcp-resources-prompts-design.md, CLAUDE.md §2.2, ADR-0006

## Contesto

Il server espone 7 tool ma zero MCP Resources e zero Prompts, nonostante il
CLAUDE.md §2.2 imponga URI `dt://` stabili/deterministici e resource bounded
≤25K token. È l'unica grande superficie del protocollo MCP non coperta.

## Decisione

Adottare le superfici MCP Resources e Prompts.

- **Resources**: 3, read-only — `dt://databases`,
  `dt://record/{uuid}/metadata`, `dt://record/{uuid}/text`. URI deterministici
  e stabili basati sullo UUID DEVONthink. Ogni resource è bounded ≤25K token
  via troncamento esplicito (`RESOURCE_MAX_CHARS`, backstop
  `RESOURCE_JSON_BUDGET_CHARS`); mai dump di un intero database.
- **Sicurezza**: le read di resource passano per lo stesso gate scope
  `dt:read` + ConsentStore dei tool, tramite l'helper `safe_resource` (NON
  `safe_call`: le resource restituiscono contenuto raw e su errore devono
  *sollevare* un errore di protocollo MCP, non un envelope `success=false`).
  Record di un database non autorizzato, o con `database_uuid` non
  determinabile sotto un principal HTTP, sono negati (fail-closed).
- **Prompts**: 2, soli template (`weekly_review`, `triage_inbox`) che
  orchestrano i tool esistenti. Zero dipendenze/JXA.

## Razionale

Completa il protocollo a costo minimo: zero dipendenze runtime nuove, zero
script JXA nuovi, zero metodi adapter astratti nuovi. Riuso integrale
dell'infrastruttura 0.4.0 (adapter, ConsentStore, audit, scope).

## Conseguenze

- Aumenta di poco il costo di contesto delle liste resource/prompt
  (3+2 voci, descrizioni ≤1 riga). Accettato; YAGNI sul resto.
- Il bound ≤25K token è enforced dal backstop sul corpo serializzato
  (`RESOURCE_JSON_BUDGET_CHARS = 60_000`): a ~2.5 char/token
  (peggior caso per il corpus target IT/EN/FR/DE) ≈ 24K token, sotto
  il limite con headroom. Stima char-based (nessuna dipendenza
  tokenizer, vincolo zero-new-deps); conservativa per le lingue target.
- `total_chars` esatto non disponibile (richiederebbe JXA nuovo): deferito.

## Riferimenti

- Spec: docs/superpowers/specs/2026-05-17-mcp-resources-prompts-design.md
- ADR-0006 (OAuth scope model), ADR-0005 (test strategy 4-tier)
