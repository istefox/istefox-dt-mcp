# handoff.md — istefox-dt-mcp

> Documento di passaggio tra sessioni di lavoro. Aggiornato a fine sessione.

---

## Snapshot sessione corrente

- **Data**: 2026-04-30
- **Operatore**: Stefano Ferri + Claude Opus 4.7
- **Output**: scaffold monorepo + git init + bozza email Cowork + ADR 0001

---

## Cosa è stato fatto in questa sessione

1. Letto e validato il brief architetturale `ARCH-BRIEF-DT-MCP.md` (v0.1, 29/04/2026).
2. Inizializzata directory progetto `/Users/stefanoferri/Developer/Devonthink_MCP/`.
3. Creati i tre file di project meta: `CLAUDE.md`, `memory.md`, `handoff.md`.
4. **Correzione namespace**: tutto rinominato da `vibrofer-*` a `istefox-*` (progetto personale, non lavorativo). Memoria globale aggiornata per default futuro.
5. Generato scaffold monorepo con `uv` workspace:
   - `apps/server` (MCP server FastMCP)
   - `apps/sidecar` (RAG ChromaDB)
   - `libs/adapter` (Bridge JXA/x-callback-url/DT Server)
   - `libs/schemas` (Pydantic v2 condivisi)
6. File config: `pyproject.toml` root + per-package, `.gitignore`, `README.md`.
7. ADR 0001 — Stack Python + FastMCP + ChromaDB + uv (`docs/adr/0001-stack-python-fastmcp-chromadb.md`).
8. Bozza messaggio review Cowork (`docs/cowork-review-request.md`) — pronta da copiare in email/Slack.
9. `git init` + primo commit con tutto lo scaffold.

---

## Stato corrente del progetto

- **Fase**: scaffold completato. In attesa di review architetturale Cowork.
- **Codice applicativo**: nessuno scritto. Solo `__init__.py` con `__version__`.
- **Dipendenze installate**: nessuna. `uv sync` non ancora eseguito.
- **Git**: repo locale inizializzato. Nessun remote configurato.

---

## Cosa fare nella prossima sessione

### Priorità ALTA — bloccanti per implementazione

- [ ] **Inviare il brief a Cowork** — usare `docs/cowork-review-request.md` come base. Stefano deve fornire contatto Cowork.
- [ ] Raccogliere feedback Cowork → produrre **ADR 0002** (validazione bridge multi-channel) e **ADR 0003** (MVP scope).
- [ ] Validare le 8 decisioni aperte elencate in `memory.md`.

### Priorità MEDIA — fattibile in parallelo al review

- [ ] Eseguire `uv sync` per validare il workspace e generare `uv.lock`
- [ ] Smoke test JXA: `osascript -l JavaScript -e 'Application("DEVONthink").name()'` — verifica DT4 risponde
- [ ] CI minimo (GitHub Actions o similar) per `ruff check` + `pytest`
- [ ] Decidere se creare repo GitHub privato (Stefano non ha ancora risposto)

### Priorità BASSA — può aspettare il post-ADR

- [ ] Definire schema Pydantic per i 3 tool MVP (`search`, `ask_database`, `find_related`)
- [ ] Bozza smart rule DT4 → webhook locale per il sync sidecar
- [ ] Primo prototipo `JXABridge` con pool async (1 worker → estendibile)

---

## Domande aperte per l'utente

1. **Repo remoto**: vuoi un repo GitHub privato fin da subito o local-only finché non c'è MVP?
2. **Cowork**: contatto/canale per spedire l'email di review?
3. **MVP scope**: 3 tool read-only (proposta brief) o 5 con almeno una write op?
4. **Distribuzione iniziale**: solo `pipx` per testing personale o subito anche `.mcpb`?
5. **Email Cowork**: la spedisci tu manualmente o vuoi che la prepari come bozza Gmail (richiederebbe autenticazione)?

---

## Note operative per chi riprende

- **Tutti i vincoli obbligatori** sono in `CLAUDE.md` §2. Leggerli PRIMA di proporre design alternativi.
- **Lo stack non si tocca** senza discussione (`CLAUDE.md` §3).
- **Niente codice GPL**: prima di importare una libreria, verifica licenza. Non guardare il sorgente di `dvcrn/mcp-server-devonthink`.
- **DT4 vs DT3**: `Application("DEVONthink")` per DT4. Se uno snippet usa `Application("DEVONthink 3")` è codice DT3, da non riusare 1:1.
- **stdio**: MAI `print()` o `stdout`. Solo `stderr` o file via `structlog`.
- **Namespace**: `istefox-*` (progetto personale). NON usare `vibrofer-*` se non esplicitamente richiesto.

---

## File chiave

| File | Scopo |
|---|---|
| `CLAUDE.md` | Regole + vincoli obbligatori del progetto |
| `memory.md` | Decisioni prese, decisioni aperte, contesto |
| `handoff.md` | Questo file — passaggi tra sessioni |
| `ARCH-BRIEF-DT-MCP.md` (root + `~/Downloads/`) | Brief architetturale completo (fonte di verità) |
| `docs/adr/0001-*.md` | ADR stack tecnologico |
| `docs/cowork-review-request.md` | Bozza email per review |
| `pyproject.toml` | Workspace uv (radice) |

---

## Log handoff

- **2026-04-30 — Sessione di setup iniziale**: creati i tre file di project meta. Nessun codice scritto.
- **2026-04-30 — Sessione di scaffolding**: corretto namespace `vibrofer→istefox`, generato monorepo `uv`, ADR 0001, bozza Cowork email, git init + primo commit. Pronti per review Cowork in parallelo a setup operativo (uv sync, CI).
