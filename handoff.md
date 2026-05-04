# handoff.md — istefox-dt-mcp

> Documento di passaggio tra sessioni di lavoro. Aggiornato a fine sessione.

---

## Snapshot sessione corrente

- **Data fine**: 2026-05-04 sera (~22:00 locali)
- **Branch**: `main` @ `4dbc983` (in sync con origin/main)
- **Output principale**: cassette VCR real-data — infrastruttura completa + 6 cassette pulite catturate ma NON ancora committate (3 punti di attenzione da risolvere prima)

---

## Stato corrente del progetto

### Versione live
- **GitHub Releases**: `v0.1.0` (rilasciata 2026-05-02, ancora attuale)
- **MCP Registry**: `io.github.istefox/dt-mcp` v0.1.0
- **Repo**: pubblico, MIT, solo `istefox` come contributor

### 0.2.0 in corso — landed in main

PR mergiate da inizio 0.2.0 (ordine cronologico):

| PR | Topic |
|---|---|
| #43 | Drift detection 3-stati (no_drift/already_reverted/hostile_drift) per file_document undo |
| #45 | `summarize_topic` — server-side clustering retrieval (4 dimensioni) |
| #49 | **Cassette VCR infrastructure** (record-cassette CLI + sanitization + manifest + setup script + recording guide + invariant tests) |
| #50 | fix setup_test_database: ~/Databases/ + lookup-by-name dopo createDatabase |
| #51 | fix setup_test_database: createRecordWith + kind→type mapping + location group walk |
| #52 | fix setup_test_database: rtf → "formatted note" (DT4 silently no-op su "rtf") |
| #53 | fix load_manifest: parents[5] → parents[4] (off-by-one) |
| #54 | fix record_cassette: parents[5] → parents[4] in CLI + `_resolve_placeholder_uuids` (placeholder→real UUID via lookup-by-name) |
| #55 | fix DEFAULT_INPUTS["move_record"]: destination "fixtures-dt-mcp/Archive" (formato Database/Group) |
| #56 | fix record_cassette: `cache_enabled=False` durante capture (TTL SQLite cache short-circuita JXA) |
| #57 | fix sanitizer: split mappa DB vs record (system Inbox vs gruppo /Inbox) + manifest `system_databases` |
| #58 | fix sanitizer: trailing-slash path + UUID in `reference_url` |
| #59 | fix sanitizer: `real_uuid_map` per riscrivere argv + stdout text-level |

### Test status
- 208 unit + contract test pass
- 7 integration test (skip default)
- macos-import-and-bundle CI: pass

---

## Cose pendenti — cassette VCR (working tree, non committate)

Le 6 cassette catturate live dal DB `fixtures-dt-mcp` sono nel working tree (`tests/contract/cassettes/*.json`) ma NON sono state committate. **CLEAN**: zero leak (nessun username, nessun DB privato, nessun UUID reale DT).

### 3 punti di attenzione da risolvere prima di committarle

1. **`Sample PDF Invoice 2025` ora vive in `/Archive/` invece di `/Inbox/`** — durante il recording, `move_record` (dry_run=False di default) ha effettivamente spostato il record. Tutte le cassette catturate dopo `move_record` riflettono lo stato post-move. Il DB ora drift-a dal manifest. Da decidere:
   - Spostare manualmente il record da `/Archive` a `/Inbox` in DT4 e ricatturare per location stabile, OPPURE
   - Aggiornare il manifest per dichiarare `/Archive` come location attesa per quel record (ma diventa più strano semanticamente)

2. **`find_related` ritorna lista vuota `[]`** — il record fixture è un PDF placeholder senza contenuto reale, quindi DT4 non trova similar. Da decidere:
   - Accettare la lista vuota (la cassette testa solo lo "shape" della risposta vuota), OPPURE
   - Popolare i record fixture con contenuto reale così `find_related` può tornare match significativi

3. **`<UNKNOWN_PATH_1>` rimanente nel campo `path`** — è il filesystem path interno del `.dtBase2` bundle (`/Files.noindex/<machine-uuid>.pdf`). Documentato come known limitation in PR #58. Safe (nessun leak), non deterministico. Da fare:
   - Allentare l'invariant test `test_cassettes_have_no_unknown_placeholders` per consentire `<UNKNOWN_PATH_n>` SOLO sul campo `path` di Record, NON su location

### Step di chiusura del feature cassette VCR

Quando i 3 punti sopra sono decisi:

1. Riportare il record in `/Inbox` o aggiornare il manifest
2. Ricatturare con `uv run istefox-dt-mcp record-cassette --all`
3. Aggiornare l'invariant test (point 3 sopra)
4. **Riscrivere i contract test assertions** in `tests/contract/test_jxa_replay.py` per matchare i dati reali di `fixtures-dt-mcp` (oggi falliscono perché cablate sui vecchi cassette sintetici, es. `assert len(databases) == 2`)
5. Aggiornare CHANGELOG sezione Unreleased
6. Commit cassette + invariant + contract test rewrite in un PR finale

---

## Stato repo locale

```
~/Developer/Devonthink_MCP/
├── main branch @ 4dbc983 (in sync con origin/main)
├── working tree:
│   └── tests/contract/cassettes/*.json (6 file modificati, NON staged)
└── 0 stale branches (cleanup fatto durante la sessione)
```

`git status` → 6 cassette modified non staged.
`git log --oneline -5`:
```
4dbc983 fix(sanitizer): rewrite real DT UUIDs in argv via real_uuid_map (#59)
db04074 fix(sanitizer): match trailing-slash paths + rewrite UUIDs in reference_url (#58)
f4b9b08 fix(sanitizer): split DB and record name maps to handle DT4 system Inbox (#57)
49fdb76 fix(record_cassette): disable cache during capture (#56)
907bf5a fix(record_cassette): correct DEFAULT_INPUTS move_record destination format (#55)
```

---

## Stato DT4 (Stefano's Mac)

- Database `fixtures-dt-mcp` aperto in `~/Databases/fixtures-dt-mcp.dtBase2`
- 10 record creati nei rispettivi gruppi (post move_record: il primo PDF è in `/Archive` invece che `/Inbox`)
- Database `privato` chiuso (chiuso manualmente prima delle catture pulite)
- Database sistema `Inbox` aperto (non chiudibile, gestito dal sanitizer come `system_databases`)

---

## 0.2.0 roadmap rimanente

- ⏳ **Cassette VCR live** — infrastruttura ✅, capture ✅, mancano i 3 punti sopra + test rewrite
- ⏸️ **`create_smart_rule`** — DEFERRED (issue #47 — DT4 SDK gap)
- ⏸️ **RAG benchmark cross-corpus** — bloccato su early adopter
- ⏸️ **HTTP transport + OAuth multi-device** — ADR-006 da finalizzare
- ⏸️ **Per-op drift detection per `bulk_apply` undo** — schema upgrade audit log

---

## Per riprendere

```bash
cd ~/Developer/Devonthink_MCP
git status                 # → 6 cassette modified non staged
git log --oneline -5       # → ultimo PR #59
ls tests/contract/cassettes/  # → 6 file
```

Verifica integrità cassette:
```bash
python3 -c "
import json, re
real_uuid_re = re.compile(r'[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}')
fixture_re = re.compile(r'^FIXTURE-')
for n in ['list_databases', 'search_bm25', 'find_related', 'get_record', 'apply_tag', 'move_record']:
    full = json.dumps(json.load(open(f'tests/contract/cassettes/{n}.json')))
    leaks = ['stefanoferri'] if 'stefanoferri' in full else []
    leaks += ['privato'] if 'privato' in full.lower() else []
    leaks += ['real-DT-UUID'] if [u for u in real_uuid_re.findall(full) if not fixture_re.match(u)] else []
    print(f'{n}: {\"CLEAN\" if not leaks else \"LEAK: \" + str(leaks)}')
"
```
