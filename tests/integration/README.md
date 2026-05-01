# Tier 3 — Integration tests (real DEVONthink)

## Scopo

Validare il bridge JXA contro un'istanza reale di **DEVONthink 4** —
non mockata. Coprono il "happy path" di ogni tool primario e
includono un benchmark di latenza che misura il target GO/NO-GO
della W2 (`p95 read < 500ms`).

Questa suite **non sostituisce** i test unitari (che restano la
prima linea di difesa); è un controllo di realtà prima di ogni tag.

## Prerequisiti

- macOS con DEVONthink 4 installato e in esecuzione
- Almeno **un database aperto** con ≥5 record (più contenuto = test
  più stabili, specie per `find_related` e `classify_record`)
- Permesso AppleEvents concesso al terminale che esegue `pytest`
  (Impostazioni di sistema → Privacy e Sicurezza → Automazione →
  spuntare DEVONthink sotto l'app del terminale)
- `uv sync` eseguito (necessario per `pytest-benchmark`)

Se DEVONthink non è in esecuzione, l'autouse fixture `dt_running`
salta l'intero modulo con un messaggio chiaro — niente errori
fuorvianti.

## Come eseguirli

Smoke (6 test, uno per tool):

```bash
uv run pytest tests/integration -m integration -v
```

Benchmark di latenza (1 test):

```bash
uv run pytest tests/integration -m "integration and benchmark" \
    --benchmark-enable
```

Solo collection (per verificare che la discovery funzioni senza
toccare DT):

```bash
uv run pytest tests/integration -m integration --co -q
```

## Comportamento di skip

- DT non in esecuzione → skip dell'intero modulo
- Nessun database aperto → skip del test che richiede `first_open_database`
- Query broad senza hit nel DB dell'utente → skip del singolo test
  (DB minuscolo = caso degenere, non un bug)
- Tag probe già presente sul record sentinella → skip (richiede
  cleanup manuale, ma evita falsi positivi)

## Sessione default

I test integration **non vengono mai eseguiti** in `pytest tests/`
o `pytest tests/unit`. Il filtro `-m "not integration"` è applicato
da `addopts` in `pyproject.toml`. Servono `-m integration` espliciti
per attivarli.

## CI plan (deferred — Step 3)

I test integration giriranno su runner `macos-14` con DEVONthink
preinstallato. Non sono parte del workflow di CI di base; vengono
attivati manualmente prima di ogni release tag.

## Limitazioni note (0.1.0)

- **Nessun fixture DB sintetico**: i test usano i database aperti
  dell'utente. Significa che coverage e stabilità dipendono dal
  contenuto reale.
- **Asserzioni tolerance-based, non value-based**: nessun UUID,
  nome record o conteggio è hard-coded. È intenzionale — rende la
  suite portabile tra macchine diverse, ma riduce la specificità.
- **`apply_tag(dry_run=True)` è l'unica write op coperta**: per
  evitare qualsiasi rischio di mutazione del DB dell'utente. Le
  write ops "vere" (apply senza dry_run) saranno in una suite
  separata su DB sintetico, da introdurre in 0.2.x.
- **Latenza single-threaded**: il benchmark usa `pool_size=2` ma
  esercita il bridge serialmente. Test di concorrenza realistici
  arriveranno con il sidecar.
