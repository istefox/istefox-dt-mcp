"""OAuth 2.1 + PKCE foundation (0.4.0 phase 4).

Three concerns are split into focused classes so they can be tested
in isolation:

- ``OAuthSecret``: persists a 32-byte HMAC key on disk with strict
  file permissions (0600). Generated lazily on first run.
- ``JWTIssuer``: signs and verifies bearer tokens (HS256) carrying
  ``sub`` (principal_id), ``scope`` (space-separated scope list),
  ``exp``, ``iat``, ``jti`` claims.
- ``AuthCodeStore``: short-lived SQLite store that holds pending
  authorization codes (10-minute TTL by default), with one-shot
  consumption to prevent code replay.

PKCE verification is a tiny pure helper that wraps authlib's S256
challenge primitive — kept here so the rest of the OAuth path
doesn't import authlib directly.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from joserfc import jwt
from joserfc.errors import ExpiredTokenError, InvalidClaimError
from joserfc.jwk import OctKey

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

log = structlog.get_logger(__name__)


# Token lifetime: 1 hour. Short enough to bound replay damage, long
# enough that a typical interactive session doesn't re-prompt.
DEFAULT_JWT_TTL_S = 3600

# Authorization codes are exchanged for tokens within ~10 minutes.
# The OAuth 2.1 spec recommends a max of 10 minutes; we follow.
DEFAULT_AUTH_CODE_TTL_S = 600


# ---------------------------------------------------------------------------
# OAuth secret persistence
# ---------------------------------------------------------------------------


class OAuthSecret:
    """A 32-byte HMAC key persisted to disk for JWT signing.

    File layout: a single binary file at ``<data_dir>/oauth_secret``
    with mode ``0600`` (readable only by the user). Generated lazily
    if missing. Rotation is intentional manual: delete the file and
    restart — all outstanding tokens become invalid (acceptable for
    single-user v1).
    """

    SECRET_BYTES = 32

    def __init__(self, path: Path) -> None:
        self.path = path
        self._cached: bytes | None = None

    def get(self) -> bytes:
        """Return the secret, generating + persisting it on first call."""
        if self._cached is not None:
            return self._cached
        if self.path.exists():
            self._cached = self.path.read_bytes()
            if len(self._cached) != self.SECRET_BYTES:
                raise RuntimeError(
                    f"OAuth secret at {self.path} has wrong length "
                    f"({len(self._cached)} != {self.SECRET_BYTES}). "
                    "Delete the file and restart to regenerate."
                )
            return self._cached
        # First run — generate, write with strict perms.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        secret = secrets.token_bytes(self.SECRET_BYTES)
        # `os.open` lets us set the mode atomically on creation;
        # otherwise there's a window where the file is world-readable.
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, secret)
        finally:
            os.close(fd)
        log.info("oauth_secret_generated", path=str(self.path))
        self._cached = secret
        return secret


# ---------------------------------------------------------------------------
# JWT issuer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TokenClaims:
    """Decoded JWT claims relevant to the request context."""

    principal_id: str
    scopes: frozenset[str]
    expires_at: int


class JWTIssuer:
    """Sign + verify bearer tokens with HS256.

    Issuer/audience are fixed strings so the token shape is uniform;
    we don't pretend to be a multi-tenant authz server.
    """

    ALG = "HS256"
    ISSUER = "istefox-dt-mcp"
    AUDIENCE = "istefox-dt-mcp-client"

    def __init__(self, secret: OAuthSecret, *, ttl_s: int = DEFAULT_JWT_TTL_S) -> None:
        self.secret = secret
        self.ttl_s = ttl_s

    def _key(self) -> OctKey:
        # joserfc HS256 wants an OctKey, not raw bytes.
        return OctKey.import_key(self.secret.get())

    def issue(
        self,
        *,
        principal_id: str,
        scopes: Iterable[str],
    ) -> tuple[str, int]:
        """Sign a bearer token. Returns ``(token, expires_at_unix)``."""
        now = int(time.time())
        exp = now + self.ttl_s
        scope_str = " ".join(sorted(set(scopes)))
        claims: dict[str, Any] = {
            "iss": self.ISSUER,
            "aud": self.AUDIENCE,
            "sub": principal_id,
            "scope": scope_str,
            "iat": now,
            "exp": exp,
            "jti": secrets.token_urlsafe(16),
        }
        token = jwt.encode({"alg": self.ALG}, claims, self._key())
        return token, exp

    def verify(self, token: str) -> TokenClaims:
        """Decode + validate a bearer token. Raises on any failure.

        Raises:
            BadSignatureError: signature mismatch.
            ExpiredTokenError: ``exp`` in the past.
            InvalidClaimError: missing/wrong ``iss``/``aud`` claim.
        """
        decoded = jwt.decode(token, self._key())
        # joserfc's claims_requests + ClaimsOption is the documented
        # path; for the v1 single-issuer setup we hand-roll the few
        # checks we care about — keeps test surface tiny.
        claims = decoded.claims
        if claims.get("iss") != self.ISSUER:
            raise InvalidClaimError("iss")
        if claims.get("aud") not in (self.AUDIENCE, [self.AUDIENCE]):
            raise InvalidClaimError("aud")
        exp = int(claims.get("exp", 0))
        if exp < int(time.time()):
            raise ExpiredTokenError("exp")
        sub = str(claims.get("sub") or "")
        if not sub:
            raise InvalidClaimError("sub")
        scope_str = str(claims.get("scope") or "")
        scopes = frozenset(s for s in scope_str.split(" ") if s)
        return TokenClaims(principal_id=sub, scopes=scopes, expires_at=exp)


# ---------------------------------------------------------------------------
# PKCE
# ---------------------------------------------------------------------------


def verify_pkce_s256(code_verifier: str, code_challenge: str) -> bool:
    """True iff the verifier hashes (S256) to the recorded challenge.

    Only S256 is supported; ``plain`` is rejected by OAuth 2.1 anyway.
    """
    try:
        computed = create_s256_code_challenge(code_verifier)
    except Exception:  # noqa: BLE001 — invalid utf-8, etc.
        return False
    return bool(computed == code_challenge)


# ---------------------------------------------------------------------------
# Authorization code store
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuthCodeRecord:
    """A pending authorization code awaiting token exchange."""

    code: str
    principal_id: str
    granted_scopes: frozenset[str]
    granted_database_uuids: frozenset[str]
    redirect_uri: str
    code_challenge: str
    issued_at: int


class AuthCodeStore:
    """SQLite-backed short-lived authorization code registry.

    Codes are one-shot: ``consume`` deletes the row atomically so
    replay attacks fail closed. Codes outside the TTL are pruned
    lazily on consume (good enough for single-user v1; a janitor
    thread would be nice in a future revision).
    """

    def __init__(self, db_path: Path, *, ttl_s: int = DEFAULT_AUTH_CODE_TTL_S) -> None:
        self.db_path = db_path
        self.ttl_s = ttl_s
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db_path, check_same_thread=False, isolation_level=None
        )
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = FULL")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS auth_code (
                    code              TEXT PRIMARY KEY,
                    principal_id      TEXT NOT NULL,
                    granted_scopes    TEXT NOT NULL,
                    granted_db_uuids  TEXT NOT NULL,
                    redirect_uri      TEXT NOT NULL,
                    code_challenge    TEXT NOT NULL,
                    issued_at         INTEGER NOT NULL
                )
                """)

    def issue(
        self,
        *,
        principal_id: str,
        granted_scopes: Iterable[str],
        granted_database_uuids: Iterable[str],
        redirect_uri: str,
        code_challenge: str,
    ) -> str:
        """Mint a new authorization code; returns the opaque code string."""
        code = secrets.token_urlsafe(32)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO auth_code (
                    code, principal_id, granted_scopes, granted_db_uuids,
                    redirect_uri, code_challenge, issued_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    code,
                    principal_id,
                    " ".join(sorted(set(granted_scopes))),
                    " ".join(sorted(set(granted_database_uuids))),
                    redirect_uri,
                    code_challenge,
                    int(time.time()),
                ),
            )
        return code

    def consume(self, code: str) -> AuthCodeRecord | None:
        """One-shot retrieval. Returns ``None`` if missing or expired."""
        cutoff = int(time.time()) - self.ttl_s
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT code, principal_id, granted_scopes, granted_db_uuids,
                       redirect_uri, code_challenge, issued_at
                FROM auth_code
                WHERE code = ? AND issued_at >= ?
                """,
                (code, cutoff),
            ).fetchone()
            # Always delete (even on miss it's a no-op) so any code we
            # SELECT'd is consumed regardless of expiry status.
            conn.execute("DELETE FROM auth_code WHERE code = ?", (code,))
        if row is None:
            return None
        return AuthCodeRecord(
            code=row[0],
            principal_id=row[1],
            granted_scopes=frozenset(s for s in row[2].split(" ") if s),
            granted_database_uuids=frozenset(s for s in row[3].split(" ") if s),
            redirect_uri=row[4],
            code_challenge=row[5],
            issued_at=row[6],
        )

    def prune_expired(self) -> int:
        """Best-effort cleanup. Returns rows deleted."""
        cutoff = int(time.time()) - self.ttl_s
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM auth_code WHERE issued_at < ?", (cutoff,))
            return int(cur.rowcount or 0)
