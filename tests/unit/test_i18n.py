"""Translator loads italian messages from locales/it.toml."""

from __future__ import annotations

from istefox_dt_mcp_schemas.errors import ErrorCode
from istefox_dt_mcp_server.i18n import Translator


def test_translates_dt_not_running(translator: Translator) -> None:
    msg = translator.message_it(ErrorCode.DT_NOT_RUNNING)
    assert "DEVONthink" in msg
    assert "esecuzione" in msg.lower()


def test_recovery_hint_dt_not_running(translator: Translator) -> None:
    hint = translator.recovery_hint_it(ErrorCode.DT_NOT_RUNNING)
    assert "Avvia" in hint


def test_unknown_code_falls_back_to_key(translator: Translator) -> None:
    assert translator.message_it("UNKNOWN_CODE") == "UNKNOWN_CODE"


def test_string_code_accepted(translator: Translator) -> None:
    msg = translator.message_it("RECORD_NOT_FOUND")
    assert "Record" in msg
