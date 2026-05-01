"""Italian localization for user-facing error messages.

Tool descriptions and field-level docs are in english (better LLM
selection performance). User-facing error messages are translated
here to italian.

Translations are loaded from `locales/it.toml` at startup.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from istefox_dt_mcp_schemas.errors import ErrorCode

_LOCALES_DIR = Path(__file__).parent / "locales"


class Translator:
    """Maps ErrorCode -> italian message + recovery hint."""

    def __init__(self, locale_path: Path | None = None) -> None:
        path = locale_path or (_LOCALES_DIR / "it.toml")
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        self._messages: dict[str, dict[str, str]] = data.get("error", {})

    def message_it(self, code: ErrorCode | str) -> str:
        key = code.value if isinstance(code, ErrorCode) else code
        return self._messages.get(key, {}).get("message", key)

    def recovery_hint_it(self, code: ErrorCode | str) -> str:
        key = code.value if isinstance(code, ErrorCode) else code
        return self._messages.get(key, {}).get("recovery_hint", "")
