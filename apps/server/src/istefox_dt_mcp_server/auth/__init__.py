"""Authentication / authorization plumbing.

Phase 2 (0.4.0): Scope enum + RequestContext + contextvar plumbing.
Real OAuth issuance, JWT validation, and consent persistence land in
phase 3-4 — this module ships the enforcement skeleton so tools can
declare scope requirements today.

For stdio the middleware grants all scopes (single-user, local-trust).
For HTTP, a transport-stage stub reads the `X-Istefox-Scope` header
(testing-only); phase 4 swaps it for OAuth bearer-token validation.
"""
