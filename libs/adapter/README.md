# istefox-dt-mcp-adapter

Bridge layer per DEVONthink — interfaccia unificata `DEVONthinkAdapter` con tre canali:

- **JXA pool** (primario): `osascript -l JavaScript` con worker pool async, semaphore, cache SQLite
- **x-callback-url** (fallback leggero): `x-devonthink-item://`, `x-devonthink://` per ops a bassa latenza
- **DT Server HTTPS** (opzionale, multi-host): edizione Server di DT, scraping/parsing

## Stato

Scaffold. Implementazione pendente review architetturale Cowork.

## Vincoli

- DT4 primario: `Application("DEVONthink")` (non `Application("DEVONthink 3")`)
- JXA single-threaded → semaphore pool 4-8 worker, timeout default 5s
- Errori strutturati con codici tassonomici + `recovery_hint`
