# ADR 0004 — MVP tool scope: 5 tool incluso `file_document` con `dry_run` mandatory

- **Status**: Accepted
- **Date**: 2026-04-30
- **Decisori**: Stefano Ferri
- **Supersedes**: decisione provvisoria precedente "3 tool read-only" (sessione 2026-04-30)
- **Fonte**: REVIEW_ADR §2 P3, §5, §7 ADR-003

---

## Contesto

Il brief listava 7 tool potenziali in §5.4. La proposta intermedia (utente) era 3 tool read-only per minimizzare rischio. La review ha identificato che 3 tool read-only è troppo conservativo: rinvia la validazione del pattern critico (`dry_run + audit_id + before-state + undo`) a fine progetto, lasciando metà della roadmap su ipotesi non testate. Il pattern dry-run è la value proposition principale rispetto al connector esistente `dvcrn/mcp-server-devonthink`.

## Decisione

**MVP a 5 tool**: 4 read + 1 write con `dry_run` mandatory.

| Tool | Tipo | Razionale inclusione |
|---|---|---|
| `list_databases` | read | Resource enumeration di base, abilita altri tool, costo zero. Prerequisito UX |
| `search` | read (hybrid BM25 + vector) | Capability primaria. Differenzia dal connector esistente con vector RAG |
| `ask_database` | read (RAG Q&A multi-doc) | Innovazione centrale, valida pipeline embedding → retrieval → answer |
| `find_related` | read | Wrap "See Also"/"Compare" di DT, basso rischio, valore alto |
| `file_document` | write con `dry_run=True` default | **Valida pattern dry-run + audit + undo dal day 1** |

## Esclusi da v1 (con razionale)

| Tool | Razionale esclusione |
|---|---|
| `summarize_topic` | Replicabile dal client con `ask_database` + prompt template ad hoc. Dipendenza da AI nativa DT4 (rischio interfaccia). Non aggiunge capability strutturale |
| `bulk_apply` | Blast radius alto. Valore non validato. Prerequisito: `file_document` deve aver dimostrato il pattern dry-run in produzione |
| `create_smart_rule` | Caso edge per power user. Bassa frequenza d'uso attesa. Rinviabile a v2 |

## Razionale del cambio (3 → 5)

- **Validazione precoce del value-prop**: il pattern dry-run è il fulcro della differenziazione vs `dvcrn/...`. Validarlo solo a W7 lascia ipotesi non testate troppo a lungo
- **5 ≠ 7**: non passiamo da 3 a 7 perché `bulk_apply` e `create_smart_rule` hanno blast radius alto e valore non ancora validato; vanno dopo conferma del pattern su `file_document`
- **`list_databases` aggiunto perché è prerequisito UX**: l'LLM deve sapere quali DB esistono prima di fare query mirate; era già in roadmap W1-2 brief §9 ma non in §5.4

## Sequenza di implementazione

| Settimana | Tool implementati | Note |
|---|---|---|
| W1-W2 | `list_databases`, `search` (BM25 only), `find_related` | Foundations + JXA bridge |
| W3-W4 | `ask_database` (BM25 mode prima, vector dopo W6) | Pool + cache + structured logging |
| W5-W6 | `search` upgrade a hybrid (BM25 + vector), `ask_database` con vector | RAG same-process |
| W7 | `file_document` con `dry_run` + audit + undo | Validazione pattern critico |

## Resources MCP in v1

Mantenere brief §5.3 (URI `dt://database/{name}`, `dt://record/{uuid}`, ...) con limite stretto **≤ 25K token** per resource (ribadito) e validazione automatica nei test.

## Prompts MCP in v1

**Esclusi tutti** dalla v1. I 4 candidate del brief (`research_synthesis`, `client_brief`, `weekly_review`, `tag_migration`) richiedono validazione use-case con utente. Aggiungerli post-MVP dopo 2-4 settimane di uso reale.

## Criteri di inclusione futura

Per aggiungere un nuovo tool post-MVP:
1. Use-case validato su uso reale (non ipotetico)
2. Pattern di safety appropriato (dry-run per write, bounded resources per read)
3. Audit log compatibile
4. Description ≤ 2KB con sezioni "When to use", "Don't use for", "Examples"
5. Schema Pydantic v2 + test unit coverage ≥ 80%

## Conseguenze

- ✅ Pattern dry-run validato dal day 1 (riduce rischio v1)
- ✅ Value prop completa (read + 1 write tipico) in MVP
- ✅ Set ridotto rispetto a 7 → riduce noise per LLM tool selection
- ⚠ Una settimana aggiuntiva sul percorso critico vs 3 read-only (compensata dai risparmi di ADR-001 e ADR-003)
- ⚠ `file_document` richiede auto-classify e auto-tag affidabili in DT4 → da validare con spike W1-W2 su database reali

## Validazione richiesta

- Spike W1-W2: `file_document` auto-classify/auto-tag su 20 record sintetici → tasso di scelta corretta ≥ 80%
- Se fail: rinviare `file_document` a v1.5 e tornare a MVP 4 read-only

## Riferimenti

- REVIEW_ADR.md §2 P3, §5, §7 ADR-003
- Brief §5.4 (7 tool originali), §8.4 (proposta brief 3 tool)
