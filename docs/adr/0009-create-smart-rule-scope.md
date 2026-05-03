# ADR 0009 — `create_smart_rule` scope and safety boundaries

- **Status**: **Proposed** (awaiting user approval)
- **Date**: 2026-05-04
- **Decisori**: Stefano Ferri
- **Predecessor**: ADR-0004 (MVP tool scope) deferred `create_smart_rule` to v2; this ADR resurfaces it for 0.2.0 with explicit guardrails

---

## Contesto

`create_smart_rule` è la prima tool del connector che crea un oggetto DEVONthink **non-record**. Tutti gli altri write tool (`file_document`, `bulk_apply`) modificano record esistenti — invariante implicita del modello "una operazione write tocca uno (o più) record già conosciuti, e il before-state è un Record Pydantic". Le smart rule rompono questa invariante in due modi:

1. **Side effect ricorrente**: una volta creata, la rule continua a girare (specie con trigger `On Creation` o `On Modification` o scheduled). Le sue azioni POST-creazione non sono nell'audit log del connector.
2. **Action surface ricca**: DT smart rules supportano AppleScript arbitrario come action. Esporre questo via MCP significa permettere all'LLM di generare ed eseguire codice AppleScript persistente — moltiplicatore di blast radius enorme.

L'ADR-0004 aveva escluso `create_smart_rule` dal v1 con motivazione "edge case per power user, bassa frequenza d'uso". Per 0.2.0 la riconsiderazione è: il valore strutturale (l'LLM codifica logica di triage che DT enforce per sempre) è alto per power user con archivi grandi. Ma il valore va catturato senza esporre la superficie pericolosa.

## Decisione

**Includere `create_smart_rule` in 0.2.0 con quattro vincoli rigidi**:

### V1 — Trigger restricted to `On Demand` only

Non si supportano `On Creation`, `On Modification`, `On Sync`, `On Demand In Front`, `On Schedule`. Solo `On Demand` (l'utente apre DT, seleziona la rule, clicca "Run").

**Motivazione**: i trigger automatici fanno scattare la rule in modo non controllato — un undo del `create_smart_rule` qualche giorno dopo la creazione non può rollback delle azioni già scattate. `On Demand` mantiene la decisione di esecuzione esplicita all'utente, che vede preview in DT GUI prima di triggerare.

**Costo**: l'utente deve manualmente runare la rule. Per casi che vogliono auto-fire, il workflow è: connector crea la rule "On Demand" → utente in DT UI cambia trigger a "On Creation" se vuole l'auto-fire → utente è informato di prendersi responsabilità del comportamento auto. Questo trade-off è esplicito nel tool description.

**Future**: in 0.3.0+ valutare `On Demand` + `On Modification` con un confirmation step robusto e una revisione di come l'audit log traccia i firing.

### V2 — Action whitelist; no AppleScript

Action types ammessi: `move`, `add_tag`, `remove_tag`, `set_label`, `set_color`, `mark_as_read`, `mark_as_unread`. **NON** ammessi: `run_script`, `execute_script`, e qualsiasi altra action che permetta esecuzione di codice arbitrario.

**Motivazione**: AppleScript via MCP = code execution arbitrario in produzione, persistente nel database utente, scattato da trigger non sempre prevedibili. Il rischio è asimmetrico (downside enorme, upside coperto da action whitelisted).

**Costo**: l'utente che vuole AppleScript dovrà creare la rule manualmente in DT. Il tool description lo dice esplicitamente.

**Future**: 0.3.0+ può valutare AppleScript con sandboxing (es. lint statico, code review prima dell'apply, audit log dello script content). Non in 0.2.0.

### V3 — Single-database scope

Una rule = una singola database (input field `database: str`). DT model permette già questo, ma la nostra API non offre rule cross-database multiplexing.

**Motivazione**: fit naturale con il modello DT, ridurre superficie. Cross-DB sarebbe sintassi sugar lato client (chiamare il tool N volte, una per DB).

**Costo**: minimo.

### V4 — Undo = delete-only, no record-action rollback

`undo` di un `create_smart_rule` audit_id elimina la rule stessa via `delete_smart_rule(uuid)`. **Non** rollback le azioni che la rule ha applicato sui record dalla creazione in poi (move, tag, ecc. su record che la rule ha matchato).

**Motivazione**: il connector audit log non traccia per-firing record changes — quelle azioni vivono in DT, fuori dal nostro perimetro di osservabilità. Tracciarle richiederebbe un trigger DT separato che POSTa al webhook locale per ogni firing — troppa infrastruttura per il payoff.

**Costo**: l'utente che fa undo molto dopo la creazione potrebbe ritrovarsi con record ancora moss/taggati dalla rule disabilitata. Documentato come limitazione nota nel tool description e nel CHANGELOG.

**Future**: 0.3.0+ può aggiungere "rule firing log via webhook" che registra ogni applicazione automatica nell'audit log connector — abilita rollback granulare. Pre-requisito: l'infrastruttura webhook che già esiste per la sync sidecar.

## Conseguenze

**Positive**

- Capability nuova per power user: codifica triage in DT senza GUI work.
- Surface area minima: niente AppleScript, niente trigger automatici → blast radius di prova-ed-errore ridotto al minimo.
- Pattern uniforme con altri write tool: dry-run + confirm_token + audit_id.
- Backward compatible: zero impact su record/tool esistenti.

**Negative**

- Tool meno potente del controparte GUI di DT (no AppleScript, no auto-trigger).
- Curva di valore: utenti che vogliono auto-fire devono comunque toccare la GUI.
- Audit log incompleto rispetto alle azioni che la rule causerà in futuro — undo "parziale" semanticamente.

**Mitigazioni**

- Tool description spiega chiaramente i limiti V1 + V2 + V4 e il workaround GUI.
- CHANGELOG entry idem.
- Future-work flagged nel spec §13.

## Alternative considerate (e rifiutate)

### A. Esporre tutto il surface DT smart rules (incl. AppleScript + tutti i trigger)

Rifiutato. Equivale a esporre code execution arbitrario via MCP. Anche se "l'LLM è bravo" non basta — il rischio è sistemico, non mitigabile a livello di prompt.

### B. Solo lettura (`list_smart_rules`, `describe_smart_rule`) senza creazione

Rifiutato. Non aggiunge capability: l'utente vede già le smart rules in DT GUI. Il valore è la creazione automatica, non l'introspezione.

### C. Creazione + AppleScript con sandbox via subprocess

Rifiutato per 0.2.0 (overkill). Considerare per 0.3.0+ se il numero di richieste utente lo giustifica.

### D. Creazione con solo trigger automatici (`On Creation`, ecc.)

Rifiutato. Il valore di una rule on-creation non testata prima è basso per gli utenti che vogliono iterare; "On Demand" permette iterazione veloce con preview in DT GUI.

## Test/validation della decisione

- 30 giorni di osservazione post-merge: contare quanti utenti chiedono AppleScript / auto-trigger nei feedback. Soglia per riaprire la decisione: ≥3 richieste indipendenti su trigger automatici, ≥2 su AppleScript.
- Se pattern di richieste suggerisce specifici trigger sicuri (es. solo `On Demand In Front`), considerare estensione mirata in 0.3.0.

## Riferimenti

- ADR-0004 (MVP tool scope) — esclusione originale
- Spec del tool: [`docs/superpowers/specs/2026-05-04-create-smart-rule-design.md`](../superpowers/specs/2026-05-04-create-smart-rule-design.md)
- Discussione brainstorming: chat 2026-05-03 (`summarize_topic` first, `create_smart_rule` second per overnight execution)
- DT4 smart rules AppleScript dictionary: `Application("DEVONthink").smartRules`
