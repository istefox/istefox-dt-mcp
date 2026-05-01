# ADR 0007 — DT4-only support, drop DT3 backward compatibility

- **Status**: Accepted
- **Date**: 2026-04-30
- **Decisori**: Stefano Ferri
- **Supersedes**: brief §8.7 (proposta backward-compat best-effort)
- **Fonte**: REVIEW_ADR §2 P8, §7 ADR-007

---

## Contesto

Il brief proponeva backward compatibility best-effort verso DT3 con detection runtime + adapter pattern + feature gating. La review ha rifiutato la proposta sulla base di quattro argomenti: differenziale di scripting non superficiale, utenza target già su DT4, alternativa esistente per DT3, costo di maintenance doppia.

## Decisione

**v1 supporta esclusivamente DEVONthink 4.0 o successive**. Niente backward compatibility verso DT3.

- **Detection runtime**: il connector verifica la versione DT all'avvio (`Application("DEVONthink").version()`)
- **Comportamento su DT3**: errore strutturato `DT_VERSION_INCOMPATIBLE` con `recovery_hint` che suggerisce upgrade a DT4 o uso del connector `dvcrn/mcp-server-devonthink` per DT3
- **`istefox-dt-mcp doctor`**: include version check come step esplicito
- **README**: prerequisito chiaro "Requires DEVONthink 4.0 or later"

## Razionale

1. **Differenziale tecnico non superficiale**:
   - DT4 introduce AI generativa nativa (chat, summarize, transform) — assente in DT3
   - Smart rule conditions nuove
   - Field aggiuntivi nei record
   - App name cambiato: `Application("DEVONthink")` (DT4) vs `Application("DEVONthink 3")` (DT3)
   - Feature gating per supportare entrambe richiederebbe codice condizionale invasivo

2. **Utenza target su DT4**:
   - Stefano (utente target dichiarato, brief §4.3) usa DT4
   - Connector esistente `dvcrn/mcp-server-devonthink` (brief §2.1) copre già DT3 — l'utenza DT3 ha alternative

3. **DT3 → DT4 è upgrade economico** ($99-149 indicativo, non verificato): chi non ha aggiornato in 12+ mesi ha motivi specifici e probabilmente non aggiornerà per usare un nuovo MCP connector

4. **Maintenance doppia**:
   - Ogni nuovo tool richiederebbe doppia validazione, doppia matrice di test, doppia documentazione
   - Stima ~10-15% di complessità del codebase aggiunta per DT3 support (review §2 P8)
   - Settimana di lavoro evitata = ~1 in W1-W2

## Conseguenze

- ✅ Codebase più semplice (~10-15% in meno)
- ✅ Una settimana di lavoro evitata in W1-W2
- ✅ Test matrix dimezzata
- ✅ Possibilità di sfruttare AI nativa DT4 in `summarize_topic` / `ask_database` (post-MVP)
- ⚠ TAM marginale dell'utenza DT3 esclusa → mitigato dall'esistenza del connector `dvcrn/...`
- ⚠ Possibile richiesta utenti DT3 in futuro → policy: branch separato `dt3-compat` aperto a community contribution se volume lo giustifica

## Implementazione

```python
# In libs/adapter/src/istefox_dt_mcp_adapter/jxa.py
class JXAAdapter:
    MIN_DT_VERSION = "4.0.0"

    async def health_check(self) -> HealthStatus:
        version = await self._jxa("Application('DEVONthink').version()")
        if not _version_gte(version, self.MIN_DT_VERSION):
            raise DTVersionIncompatibleError(
                detected=version,
                required=self.MIN_DT_VERSION,
                recovery_hint=(
                    "Aggiorna a DEVONthink 4.0 o superiore. "
                    "Per DT3 usa il connector dvcrn/mcp-server-devonthink."
                ),
            )
        ...
```

## Riferimenti

- REVIEW_ADR.md §2 P8, §7 ADR-007
- Brief §2.3 (capability DT4), §8.7 (proposta originale backward-compat)
- Connector DT3: https://github.com/dvcrn/mcp-server-devonthink
