"""Structured error taxonomy for the bridge layer.

Every error carries a machine-readable code, a human recovery hint
in italian (user-facing), and an optional audit_id for traceability.
The server layer maps these to the Envelope error fields.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from istefox_dt_mcp_schemas.errors import ErrorCode

if TYPE_CHECKING:
    from uuid import UUID


class AdapterError(Exception):
    """Base exception for all bridge-level errors."""

    code: ErrorCode = ErrorCode.INTERNAL_ERROR

    def __init__(
        self,
        message: str,
        *,
        recovery_hint: str = "",
        audit_id: UUID | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.recovery_hint = recovery_hint
        self.audit_id = audit_id
        self.__cause__ = cause


class DTNotRunningError(AdapterError):
    code = ErrorCode.DT_NOT_RUNNING

    def __init__(self, audit_id: UUID | None = None) -> None:
        super().__init__(
            "DEVONthink is not running",
            recovery_hint="Avvia DEVONthink 4 e riprova.",
            audit_id=audit_id,
        )


class DTVersionIncompatibleError(AdapterError):
    code = ErrorCode.DT_VERSION_INCOMPATIBLE

    def __init__(
        self,
        detected: str,
        required: str,
        audit_id: UUID | None = None,
    ) -> None:
        super().__init__(
            f"DEVONthink {detected} detected, requires >= {required}",
            recovery_hint=(
                "Aggiorna a DEVONthink 4.0 o superiore. "
                "Per DT3 usa il connector dvcrn/mcp-server-devonthink."
            ),
            audit_id=audit_id,
        )
        self.detected = detected
        self.required = required


class JXATimeoutError(AdapterError):
    code = ErrorCode.JXA_TIMEOUT

    def __init__(self, timeout_s: float, audit_id: UUID | None = None) -> None:
        super().__init__(
            f"JXA call timed out after {timeout_s}s",
            recovery_hint=(
                "Operazione lenta: verifica che DEVONthink non sia bloccato. "
                "Considera di aumentare jxa_timeout_ms in config."
            ),
            audit_id=audit_id,
        )
        self.timeout_s = timeout_s


class JXAError(AdapterError):
    code = ErrorCode.JXA_ERROR

    def __init__(
        self,
        message: str,
        stderr: str = "",
        audit_id: UUID | None = None,
    ) -> None:
        super().__init__(
            message,
            recovery_hint=(
                "Errore interno del bridge JXA. Riprova; se persiste, "
                "controlla i log strutturati su stderr."
            ),
            audit_id=audit_id,
        )
        self.stderr = stderr


class JXAParseError(AdapterError):
    code = ErrorCode.JXA_PARSE_ERROR

    def __init__(self, raw_output: str, audit_id: UUID | None = None) -> None:
        super().__init__(
            "Failed to parse JXA output as JSON",
            recovery_hint=(
                "Il bridge ha ricevuto output non-JSON. "
                "Probabile incompatibilità con la versione di DEVONthink."
            ),
            audit_id=audit_id,
        )
        self.raw_output = raw_output


class RecordNotFoundError(AdapterError):
    code = ErrorCode.RECORD_NOT_FOUND

    def __init__(self, uuid: str, audit_id: UUID | None = None) -> None:
        super().__init__(
            f"Record {uuid} not found",
            recovery_hint=(
                "Il record richiesto non esiste o è in un database chiuso. "
                "Verifica l'UUID e che il database sia aperto."
            ),
            audit_id=audit_id,
        )
        self.uuid = uuid


class DatabaseNotFoundError(AdapterError):
    code = ErrorCode.DATABASE_NOT_FOUND

    def __init__(self, name: str, audit_id: UUID | None = None) -> None:
        super().__init__(
            f"Database '{name}' not found or not open",
            recovery_hint=(
                "Apri il database in DEVONthink (File → Open Database). "
                "Verifica il nome esatto con list_databases."
            ),
            audit_id=audit_id,
        )
        self.database_name = name


class ValidationError(AdapterError):
    code = ErrorCode.VALIDATION_ERROR

    def __init__(self, message: str, audit_id: UUID | None = None) -> None:
        super().__init__(
            message,
            recovery_hint="Input non valido. Vedi il dettaglio dell'errore.",
            audit_id=audit_id,
        )


class RateLimitedError(AdapterError):
    code = ErrorCode.RATE_LIMITED

    def __init__(self, retry_after_s: float, audit_id: UUID | None = None) -> None:
        super().__init__(
            f"Rate limit exceeded, retry after {retry_after_s}s",
            recovery_hint=f"Troppe richieste concorrenti. Riprova tra {retry_after_s} secondi.",
            audit_id=audit_id,
        )
        self.retry_after_s = retry_after_s
