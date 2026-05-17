"""DEVONthink MCP prompts (0.5.0).

Template-only: no deps, no JXA, no adapter calls. They emit guidance
that orchestrates the existing tools. User-facing text is Italian by
default (`lang="it"`); `lang="en"` switches. Tool names stay English
because MCP clients select tools better in English.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from ..deps import Deps


def weekly_review_text(databases: str | None, lang: str) -> str:
    """Render the weekly-review prompt body."""
    if lang == "en":
        scope = f" (limit to: {databases})" if databases else ""
        return (
            "Run a weekly review of the DEVONthink databases.\n\n"
            "1. If I didn't name databases, call the `list_databases` tool "
            "and list the open ones.\n"
            f"2. For each database{scope}, use `search` (or `summarize_topic` "
            "if available) to find records added or modified in the last 7 "
            "days.\n"
            "3. Use `find_related` on the 2-3 most relevant records to "
            "surface thematic clusters.\n"
            "4. Produce a structured digest: per database, the main themes, "
            "key documents (with reference_url), and 3 suggested actions.\n"
            "This is read-only: do not modify anything."
        )
    scope = f" (limitati a: {databases})" if databases else ""
    return (
        "Esegui una review settimanale dei database DEVONthink.\n\n"
        "1. Se non ti ho indicato database, chiama il tool `list_databases` "
        "ed elenca quelli aperti.\n"
        f"2. Per ciascun database{scope}, usa `search` (o `summarize_topic` "
        "se disponibile) per individuare i record aggiunti o modificati "
        "negli ultimi 7 giorni.\n"
        "3. Usa `find_related` sui 2-3 record più rilevanti per scoprire "
        "cluster tematici.\n"
        "4. Produci un digest strutturato: per ogni database i temi "
        "principali, i documenti chiave (con reference_url) e 3 azioni "
        "suggerite.\n"
        "Questa è una review in sola lettura: non modificare nulla."
    )


def triage_inbox_text(inbox_database: str, lang: str, apply: bool) -> str:
    """Render the inbox-triage prompt body."""
    if lang == "en":
        tail = (
            "3. After I approve a preview, call `file_document` again with "
            "dry_run=false and confirm_token = the audit_id returned by the "
            "matching preview (the token is one-shot and expires in 5 "
            "minutes)."
            if apply
            else "3. Do NOT apply: stop at the preview and wait for my "
            "explicit confirmation."
        )
        return (
            f"Triage the '{inbox_database}' inbox in DEVONthink.\n\n"
            f"1. Use `search` with a broad query limited to the "
            f"'{inbox_database}' database to list unfiled records.\n"
            "2. For each record call `file_document` with dry_run=true and "
            "show me the proposed classification/tags preview, applying "
            "nothing.\n"
            f"{tail}"
        )
    tail = (
        "3. Dopo che ho approvato una preview, richiama `file_document` con "
        "dry_run=false e confirm_token = l'audit_id restituito dalla preview "
        "corrispondente (il token è monouso e scade in 5 minuti)."
        if apply
        else "3. NON applicare: fermati alla preview e aspetta una mia "
        "conferma esplicita."
    )
    return (
        f"Esegui il triage dell'inbox '{inbox_database}' di DEVONthink.\n\n"
        f"1. Usa `search` con una query ampia limitata al database "
        f"'{inbox_database}' per elencare i record non archiviati.\n"
        "2. Per ogni record chiama `file_document` con dry_run=true e "
        "mostrami la preview di classificazione/tag proposti, senza "
        "applicare nulla.\n"
        f"{tail}"
    )


def register(mcp: FastMCP, deps: Deps) -> None:
    del deps  # prompts are static templates; no deps needed

    @mcp.prompt(
        name="weekly_review",
        description="Guida una review settimanale dei documenti DEVONthink recenti.",
    )
    def weekly_review(databases: str | None = None, lang: str = "it") -> str:
        return weekly_review_text(databases, lang)

    @mcp.prompt(
        name="triage_inbox",
        description="Guida il triage dell'Inbox DEVONthink con file_document in dry-run.",
    )
    def triage_inbox(
        inbox_database: str = "Inbox",
        lang: str = "it",
        apply: bool = False,
    ) -> str:
        return triage_inbox_text(inbox_database, lang, apply)
