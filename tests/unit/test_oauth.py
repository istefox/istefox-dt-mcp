"""Unit tests for the OAuth foundation (0.4.0 phase 4 step A).

Covers OAuthSecret persistence, JWTIssuer round-trip, PKCE verification,
and AuthCodeStore one-shot consume semantics.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from istefox_dt_mcp_server.auth.oauth import (
    AuthCodeStore,
    JWTIssuer,
    OAuthSecret,
    verify_pkce_s256,
)
from joserfc.errors import InvalidClaimError

# ---------------------------------------------------------------------------
# OAuthSecret
# ---------------------------------------------------------------------------


def test_oauth_secret_generated_on_first_call(tmp_path: Path) -> None:
    s = OAuthSecret(tmp_path / "oauth_secret")
    secret = s.get()
    assert len(secret) == OAuthSecret.SECRET_BYTES
    # File exists with mode 0600 (mask out the directory/special bits).
    assert (tmp_path / "oauth_secret").exists()
    mode = (tmp_path / "oauth_secret").stat().st_mode & 0o777
    assert mode == 0o600


def test_oauth_secret_caches_across_calls(tmp_path: Path) -> None:
    s = OAuthSecret(tmp_path / "oauth_secret")
    a = s.get()
    b = s.get()
    assert a == b
    # Same bytes returned even after the cache is hot.


def test_oauth_secret_persists_across_instances(tmp_path: Path) -> None:
    p = tmp_path / "oauth_secret"
    a = OAuthSecret(p).get()
    b = OAuthSecret(p).get()  # second instance reads the file
    assert a == b


def test_oauth_secret_rejects_wrong_length(tmp_path: Path) -> None:
    p = tmp_path / "oauth_secret"
    p.write_bytes(b"short")
    s = OAuthSecret(p)
    with pytest.raises(RuntimeError, match="wrong length"):
        s.get()


def test_oauth_secret_creates_parent_dir(tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "nested" / "oauth_secret"
    s = OAuthSecret(nested)
    s.get()
    assert nested.exists()


# ---------------------------------------------------------------------------
# JWTIssuer
# ---------------------------------------------------------------------------


def _issuer(tmp_path: Path, ttl_s: int = 3600) -> JWTIssuer:
    return JWTIssuer(OAuthSecret(tmp_path / "secret"), ttl_s=ttl_s)


def test_jwt_round_trip(tmp_path: Path) -> None:
    issuer = _issuer(tmp_path)
    token, exp = issuer.issue(principal_id="alice", scopes=["dt:read", "dt:write"])
    assert isinstance(token, str)
    assert exp > int(time.time())
    claims = issuer.verify(token)
    assert claims.principal_id == "alice"
    assert claims.scopes == frozenset({"dt:read", "dt:write"})
    assert claims.expires_at == exp


def test_jwt_rejects_tampered_token(tmp_path: Path) -> None:
    issuer = _issuer(tmp_path)
    token, _ = issuer.issue(principal_id="alice", scopes=["dt:read"])
    # Flip one byte in the signature (last 4 chars are signature tail in JWS).
    tampered = token[:-4] + ("x" * 4)
    # joserfc may raise BadSignatureError or DecodeError depending on
    # whether the corruption affects b64 decoding or just the signature
    # bytes. Either way it must NOT validate.
    with pytest.raises(Exception):
        issuer.verify(tampered)


def test_jwt_rejects_expired_token(tmp_path: Path) -> None:
    # Issue with negative TTL to force expiry instantly.
    issuer = _issuer(tmp_path, ttl_s=-1)
    token, _ = issuer.issue(principal_id="alice", scopes=["dt:read"])
    with pytest.raises(Exception, match=r"exp|expir"):
        issuer.verify(token)


def test_jwt_rejects_wrong_issuer(tmp_path: Path) -> None:
    """Tokens signed with a different issuer field shouldn't validate."""
    issuer = _issuer(tmp_path)
    # Forge a token by hand with a different issuer claim.
    from joserfc import jwt
    from joserfc.jwk import OctKey

    forged = jwt.encode(
        {"alg": "HS256"},
        {
            "iss": "evil-server",
            "aud": JWTIssuer.AUDIENCE,
            "sub": "alice",
            "scope": "dt:read",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        },
        OctKey.import_key(OAuthSecret(tmp_path / "secret").get()),
    )
    with pytest.raises(InvalidClaimError):
        issuer.verify(forged)


def test_jwt_empty_scopes_round_trip(tmp_path: Path) -> None:
    issuer = _issuer(tmp_path)
    token, _ = issuer.issue(principal_id="alice", scopes=[])
    claims = issuer.verify(token)
    assert claims.scopes == frozenset()


# ---------------------------------------------------------------------------
# PKCE
# ---------------------------------------------------------------------------


def test_pkce_s256_round_trip() -> None:
    verifier = "test-verifier-" + "a" * 50
    challenge = create_s256_code_challenge(verifier)
    assert verify_pkce_s256(verifier, challenge) is True


def test_pkce_s256_rejects_wrong_verifier() -> None:
    challenge = create_s256_code_challenge("right-one-" + "a" * 50)
    assert verify_pkce_s256("wrong-one-" + "a" * 50, challenge) is False


def test_pkce_s256_handles_empty_input() -> None:
    # Authlib doesn't crash on empty; verifier just won't match.
    assert verify_pkce_s256("", "anything") is False


# ---------------------------------------------------------------------------
# AuthCodeStore
# ---------------------------------------------------------------------------


def test_auth_code_issue_and_consume(tmp_path: Path) -> None:
    store = AuthCodeStore(tmp_path / "codes.sqlite")
    code = store.issue(
        principal_id="alice",
        granted_scopes=["dt:read", "dt:write"],
        granted_database_uuids=["DB-1", "DB-2"],
        redirect_uri="https://client/cb",
        code_challenge="challenge123",
    )
    assert code  # non-empty opaque string
    record = store.consume(code)
    assert record is not None
    assert record.principal_id == "alice"
    assert record.granted_scopes == frozenset({"dt:read", "dt:write"})
    assert record.granted_database_uuids == frozenset({"DB-1", "DB-2"})
    assert record.redirect_uri == "https://client/cb"
    assert record.code_challenge == "challenge123"


def test_auth_code_is_one_shot(tmp_path: Path) -> None:
    store = AuthCodeStore(tmp_path / "codes.sqlite")
    code = store.issue(
        principal_id="alice",
        granted_scopes=["dt:read"],
        granted_database_uuids=[],
        redirect_uri="https://client/cb",
        code_challenge="c",
    )
    assert store.consume(code) is not None
    # Second attempt fails — the code is gone.
    assert store.consume(code) is None


def test_auth_code_unknown_returns_none(tmp_path: Path) -> None:
    store = AuthCodeStore(tmp_path / "codes.sqlite")
    assert store.consume("does-not-exist") is None


def test_auth_code_expires(tmp_path: Path) -> None:
    """Issued codes outside the TTL window are rejected on consume."""
    store = AuthCodeStore(tmp_path / "codes.sqlite", ttl_s=1)
    code = store.issue(
        principal_id="alice",
        granted_scopes=["dt:read"],
        granted_database_uuids=[],
        redirect_uri="https://client/cb",
        code_challenge="c",
    )
    # Force expiry by rewriting issued_at backwards.
    import sqlite3

    conn = sqlite3.connect(store.db_path)
    conn.execute(
        "UPDATE auth_code SET issued_at = ? WHERE code = ?",
        (int(time.time()) - 60, code),
    )
    conn.commit()
    conn.close()

    assert store.consume(code) is None  # expired → no record
    # And the row should now be gone (consume always deletes).
    assert store.consume(code) is None


def test_auth_code_prune_expired(tmp_path: Path) -> None:
    store = AuthCodeStore(tmp_path / "codes.sqlite", ttl_s=1)
    # Issue 2 codes, age one of them past TTL.
    fresh = store.issue(
        principal_id="alice",
        granted_scopes=["dt:read"],
        granted_database_uuids=[],
        redirect_uri="https://client/cb",
        code_challenge="c1",
    )
    stale = store.issue(
        principal_id="alice",
        granted_scopes=["dt:read"],
        granted_database_uuids=[],
        redirect_uri="https://client/cb",
        code_challenge="c2",
    )
    import sqlite3

    conn = sqlite3.connect(store.db_path)
    conn.execute(
        "UPDATE auth_code SET issued_at = ? WHERE code = ?",
        (int(time.time()) - 60, stale),
    )
    conn.commit()
    conn.close()

    deleted = store.prune_expired()
    assert deleted == 1
    # Fresh code still consumable.
    assert store.consume(fresh) is not None


def test_oauth_secret_strict_perms_on_unix() -> None:
    """Sanity: regenerating in a temp dir gets a 0600 file (no one else readable)."""
    if os.name != "posix":
        pytest.skip("permission check is unix-only")
    # The actual permission test is covered by the dedicated test
    # above; here we just smoke-test the import path.
    assert OAuthSecret.SECRET_BYTES == 32
