# istefox-dt-mcp-server

MCP server FastMCP con transport dual-mode (stdio + streamable HTTP).

## Responsabilità

- Espone tool, resource, prompt MCP
- Routing al service layer
- Logging strutturato su stderr (mai stdout in stdio mode)
- Audit log append-only per write ops

## Stato

Scaffold. Implementazione pendente review architetturale Cowork.

## Vincoli

- stdio: MAI scrivere su stdout
- Tool description ≤ 2KB
- Server instructions ≤ 2KB
- Schema-first via Pydantic v2
