# istefox-dt-mcp-sidecar

RAG sidecar — processo Python separato per indicizzazione vettoriale di DEVONthink.

## Responsabilità

- Indicizza record DT in ChromaDB locale
- Genera embedding multilingue (bge-m3 / multilingual-e5-large)
- Sync incrementale via smart rule DT → webhook locale
- Reconciliation notturno hash-based
- Espone `query(text, k, filters)` via Unix socket al server MCP

## Stato

Scaffold. Implementazione pendente review architetturale Cowork.

## Vincoli

- Vector DB fuori dalla cartella DEVONthink (evita lock contention)
- Privacy: nessun embedding esce dalla macchina
- Opzionale: se assente, `search` degrada a BM25-only via JXA
