"""Transport-layer entrypoints.

stdio transport is invoked directly via `FastMCP.run()`; HTTP transport
lives in `transport/http.py` and goes through uvicorn under the hood.
Auth (added in 0.4.0 phase 2+) wraps the HTTP transport via FastMCP
middleware, not here.
"""
