# Smart rule DT4 → RAG sync (W6)

Setup utente per indicizzare automaticamente in tempo reale le
modifiche ai record DEVONthink nel vector store
`ChromaRAGProvider`. Tre smart rule (Imported, Modified, Trashed)
chiamano il webhook locale del daemon `istefox-dt-mcp watch`.

---

## Prerequisiti

1. RAG abilitato nel server:
   ```bash
   export ISTEFOX_RAG_ENABLED=1
   ```
2. (Opzionale ma consigliato) token di autenticazione webhook:
   ```bash
   export ISTEFOX_WEBHOOK_TOKEN="$(openssl rand -hex 16)"
   # salva il valore — ti servirà negli AppleScript
   ```
3. Daemon avviato:
   ```bash
   uv run istefox-dt-mcp watch \
       --port 27205 \
       --databases Business --databases privato \
       --reconcile-interval-s 21600   # ogni 6h
   ```
   Lascia il terminale aperto (o configuralo come `launchd` agent —
   sezione "Avvio automatico" più sotto).

---

## Smart rule: record creato (Imported)

In **DEVONthink → Tools → Smart Rules**, click `+` per crearne una nuova:

| Campo | Valore |
|---|---|
| Name | `RAG sync · imported` |
| Search in | `All Databases` (o solo Business + privato) |
| Conditions | Lascia vuoto (matcha tutto) o aggiungi `Kind is not Group` |
| Perform actions | `On Demand` + `After Importing` |

Aggiungi azione **Execute Script → Embedded** con questo AppleScript:

```applescript
on performSmartRule(theRecords)
    set webhookURL to "http://127.0.0.1:27205/sync-event"
    set bearerToken to ""  -- se usi ISTEFOX_WEBHOOK_TOKEN, mettilo qui

    repeat with theRecord in theRecords
        try
            set theUUID to (uuid of theRecord) as string
            set theDB to (name of (database of theRecord)) as string
            set jsonPayload to "{\"action\":\"created\",\"uuid\":\"" & theUUID & "\",\"database\":\"" & theDB & "\"}"

            if bearerToken is not "" then
                do shell script "curl -s --max-time 5 -X POST " & quoted form of webhookURL & ¬
                    " -H 'Content-Type: application/json'" & ¬
                    " -H 'Authorization: Bearer " & bearerToken & "'" & ¬
                    " -d " & quoted form of jsonPayload
            else
                do shell script "curl -s --max-time 5 -X POST " & quoted form of webhookURL & ¬
                    " -H 'Content-Type: application/json'" & ¬
                    " -d " & quoted form of jsonPayload
            end if
        on error errMsg
            log "RAG sync (created) failed: " & errMsg
        end try
    end repeat
end performSmartRule
```

---

## Smart rule: record modificato

Stesso template, sostituisci nella header:
- Name: `RAG sync · modified`
- Trigger: `On Demand` + `After Modifying`
- Nello script: `\"action\":\"modified\"`

---

## Smart rule: record cestinato/eliminato

Stesso template, sostituisci:
- Name: `RAG sync · deleted`
- Trigger: `After Trashing`
- Nello script: `\"action\":\"deleted\"`

(Il webhook accetta anche `created`/`modified` per registrare la
ri-comparsa di un record, utile se DT lo trash-and-restore.)

---

## Test manuale del webhook

Senza smart rule, da terminale:

```bash
curl -s -X POST http://127.0.0.1:27205/sync-event \
     -H 'Content-Type: application/json' \
     -d '{"action":"modified","uuid":"FAKE-UUID","database":"Business"}'
```

Atteso: `HTTP 202 Accepted` + `{"status":"queued"}`.

Nel log del daemon (stderr) vedrai:
```
webhook_event_received  action=modified uuid=FAKE-UUID
sync_event_fetch_failed  uuid=FAKE-UUID error=...   # ovviamente, UUID inventato
```

---

## Avvio automatico (launchd)

Crea `~/Library/LaunchAgents/com.istefox.dt-mcp-watch.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.istefox.dt-mcp-watch</string>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/bin/uv</string>
        <string>--directory</string>
        <string>/Users/stefanoferri/Developer/Devonthink_MCP</string>
        <string>run</string>
        <string>istefox-dt-mcp</string>
        <string>watch</string>
        <string>--databases</string><string>Business</string>
        <string>--databases</string><string>privato</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>ISTEFOX_RAG_ENABLED</key><string>1</string>
        <!-- <key>ISTEFOX_WEBHOOK_TOKEN</key><string>...</string> -->
    </dict>
    <key>KeepAlive</key><true/>
    <key>RunAtLoad</key><true/>
    <key>StandardOutPath</key>
    <string>/tmp/istefox-dt-mcp-watch.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/istefox-dt-mcp-watch.err</string>
</dict>
</plist>
```

Carica:

```bash
launchctl load ~/Library/LaunchAgents/com.istefox.dt-mcp-watch.plist
launchctl list | grep istefox     # verifica
tail -f /tmp/istefox-dt-mcp-watch.err
```

Per disabilitare: `launchctl unload ~/Library/LaunchAgents/com.istefox.dt-mcp-watch.plist`.

---

## Reliability

- Le smart rule DT4 possono fallire silently (nota brief §6.1). Per
  questo il daemon esegue una **reconciliation periodica**
  (`--reconcile-interval-s`, default 6h): se il webhook ha mancato un
  evento, il prossimo passaggio `reconcile` lo ricupera tramite
  set-diff (vedi `reindex.reconcile_database`).
- Il webhook ha timeout 5s lato curl + bounded queue lato daemon
  (1024 eventi). Se accumulato, batch di smart-rule grosso
  (es. trash di 1K record) viene processato gradualmente.
- Auth Bearer è opzionale ma **fortemente raccomandato** se il Mac è
  condiviso / accessibile via SSH.
