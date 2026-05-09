"""Consent UI HTML rendering (0.4.0 phase 4).

A minimal one-page form rendered at ``/oauth/authorize``. The user
selects which scopes the client may exercise and which databases the
client may see, then submits to ``/oauth/consent`` (POST). The page
is intentionally plain — no JS, no external assets — so it works in
any browser including text-mode and embedded webviews.

The template lives inline in this module to keep the package
self-contained (no template directory to ship in the .mcpb bundle).
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import TYPE_CHECKING

from jinja2 import Environment, select_autoescape

if TYPE_CHECKING:
    from istefox_dt_mcp_schemas.common import Database


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>istefox-dt-mcp — Consent</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
           max-width: 560px; margin: 2em auto; padding: 0 1em; color: #222; }
    h1 { font-size: 1.4em; margin-bottom: 0.2em; }
    .client { color: #666; font-size: 0.95em; margin-bottom: 1.5em; }
    fieldset { border: 1px solid #ddd; padding: 1em; margin-bottom: 1em; }
    legend { font-weight: 600; padding: 0 0.5em; }
    label { display: block; margin: 0.4em 0; }
    .desc { color: #666; font-size: 0.85em; margin-left: 1.6em; }
    button { background: #0066cc; color: white; border: 0; padding: 0.6em 1.2em;
             font-size: 1em; cursor: pointer; border-radius: 4px; }
    button.deny { background: #888; margin-left: 0.5em; }
    .hint { color: #888; font-size: 0.85em; margin-top: 1em; }
    input[type="hidden"] { display: none; }
  </style>
</head>
<body>
  <h1>Authorize {{ client_label }}</h1>
  <p class="client">
    Client <code>{{ client_id }}</code> is requesting access to your DEVONthink data.
  </p>

  <form method="POST" action="/oauth/consent">
    <input type="hidden" name="client_id" value="{{ client_id }}">
    <input type="hidden" name="redirect_uri" value="{{ redirect_uri }}">
    <input type="hidden" name="state" value="{{ state }}">
    <input type="hidden" name="code_challenge" value="{{ code_challenge }}">
    <input type="hidden" name="code_challenge_method" value="{{ code_challenge_method }}">

    <fieldset>
      <legend>Scopes</legend>
      {% for s in scope_choices %}
        <label>
          <input type="checkbox" name="scope" value="{{ s.value }}"
                 {% if s.value in requested_scopes %}checked{% endif %}>
          <strong>{{ s.value }}</strong> &mdash; {{ s.label }}
        </label>
        <div class="desc">{{ s.description }}</div>
      {% endfor %}
    </fieldset>

    <fieldset>
      <legend>Databases</legend>
      {% if databases %}
        {% for db in databases %}
          <label>
            <input type="checkbox" name="database_uuid" value="{{ db.uuid }}">
            <strong>{{ db.name }}</strong>
            <span class="desc" style="display:inline">({{ db.uuid[:8] }}…)</span>
          </label>
        {% endfor %}
      {% else %}
        <p class="hint">No DEVONthink databases are currently open.</p>
      {% endif %}
    </fieldset>

    <button type="submit" name="action" value="approve">Approve</button>
    <button type="submit" name="action" value="deny" class="deny">Deny</button>
  </form>

  <p class="hint">Tokens last 1 hour. You can revoke access by signing out from the client.</p>
</body>
</html>
"""


@dataclass(frozen=True)
class ScopeChoice:
    """One row in the scope picker."""

    value: str
    label: str
    description: str


# Stable, human-friendly metadata for the 3 scopes (ADR-006).
SCOPE_CHOICES: tuple[ScopeChoice, ...] = (
    ScopeChoice(
        value="dt:read",
        label="Read access",
        description=(
            "Search and read records: search, find_related, ask_database, "
            "summarize_topic, list_databases."
        ),
    ),
    ScopeChoice(
        value="dt:write",
        label="Write access",
        description=(
            "Modify records: file_document, bulk_apply (tag/move/delete via trash)."
        ),
    ),
    ScopeChoice(
        value="dt:admin",
        label="Admin access",
        description="Server configuration, smart-rule creation.",
    ),
)


_env = Environment(autoescape=select_autoescape(["html", "xml"]))
_compiled_template = _env.from_string(_TEMPLATE)


def render_consent_page(
    *,
    client_id: str,
    client_label: str | None = None,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    code_challenge_method: str,
    requested_scopes: frozenset[str],
    databases: list[Database],
) -> str:
    """Render the consent HTML page.

    Inputs are escaped via Jinja2's autoescape; ``client_label`` is
    additionally length-clamped to bound DOM size.
    """
    label = (client_label or client_id)[:80]
    return _compiled_template.render(
        client_id=client_id,
        client_label=label,
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        requested_scopes=requested_scopes,
        scope_choices=SCOPE_CHOICES,
        databases=databases,
    )


def render_simple_error(title: str, message: str, *, status: int = 400) -> str:
    """Compact HTML error page used by the OAuth routes on bad input."""
    safe_title = html.escape(title[:120])
    safe_message = html.escape(message[:400])
    return (
        f"<!doctype html><html><body>"
        f"<h1>{safe_title}</h1><p>{safe_message}</p>"
        f"<p><small>HTTP {status} · istefox-dt-mcp</small></p>"
        f"</body></html>"
    )
