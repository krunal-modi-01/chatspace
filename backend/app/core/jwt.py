"""Access-token JWT sign/verify (ADR-0006, TSD §8 AuthN).

Short-lived (15-min) signed JWTs carrying `sub` (user_id) and `sid`
(session_id). Session persistence/revocation — minting/looking up the
`sessions` row a `sid` refers to, logout, refresh-token exchange — is T10;
this module only signs and verifies the token envelope itself.

The signing key is loaded exclusively from `Settings.jwt_signing_key`
(`pydantic-settings`, env-only) and is never logged: this module never
logs the key, the encoded token, or the decoded payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt

from app.core.config import Settings


class TokenError(Exception):
    """Base class for access-token sign/verify failures."""


class ExpiredTokenError(TokenError):
    """The token's `exp` claim is in the past."""


class InvalidTokenError(TokenError):
    """The token is malformed, has an invalid signature, or is missing a
    required claim."""


@dataclass(frozen=True, slots=True)
class AccessTokenPayload:
    """Decoded, verified access-token claims."""

    user_id: str
    session_id: str
    issued_at: datetime
    expires_at: datetime


def create_access_token(
    *,
    user_id: str,
    session_id: str,
    settings: Settings,
    now: datetime | None = None,
) -> tuple[str, int]:
    """Sign a new access token for `user_id` / `session_id`.

    Returns `(token, expires_in_seconds)`. `expires_in` reflects
    `Settings.jwt_access_token_ttl_minutes` — the contract fixes this at
    `900` (15 min) via the default, but it is read from settings rather
    than hardcoded so it stays in one place.
    """

    issued_at = now or datetime.now(UTC)
    ttl = timedelta(minutes=settings.jwt_access_token_ttl_minutes)
    expires_at = issued_at + ttl

    claims: dict[str, Any] = {
        "sub": user_id,
        "sid": session_id,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }

    token = jwt.encode(
        claims,
        settings.jwt_signing_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return token, int(ttl.total_seconds())


def decode_access_token(token: str, *, settings: Settings) -> AccessTokenPayload:
    """Verify and decode `token`, returning its claims.

    Raises `ExpiredTokenError` for an expired token and `InvalidTokenError`
    for any other verification failure (bad signature, malformed token,
    missing `sub`/`sid`). Never logs the raw token or its claims — callers
    must not either.
    """

    try:
        claims = jwt.decode(
            token,
            settings.jwt_signing_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        if "expired" in str(exc).lower():
            raise ExpiredTokenError("Access token has expired.") from None
        raise InvalidTokenError("Access token is invalid.") from None

    user_id = claims.get("sub")
    session_id = claims.get("sid")
    issued_at_raw = claims.get("iat")
    expires_at_raw = claims.get("exp")

    if not isinstance(user_id, str) or not isinstance(session_id, str):
        raise InvalidTokenError("Access token is missing required claims.")
    if not isinstance(issued_at_raw, int | float) or not isinstance(expires_at_raw, int | float):
        raise InvalidTokenError("Access token is missing required claims.")

    return AccessTokenPayload(
        user_id=user_id,
        session_id=session_id,
        issued_at=datetime.fromtimestamp(issued_at_raw, tz=UTC),
        expires_at=datetime.fromtimestamp(expires_at_raw, tz=UTC),
    )
