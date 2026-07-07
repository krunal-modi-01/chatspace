"""Login / refresh business logic (T15, ADR-0006, ADR-0009).

Owns exactly two flows on top of the T10 session store
(`app.services.sessions`) and T09's JWT signer (`app.core.jwt`):

- `authenticate_and_login`: verify credentials, gate on `is_active` and
  the ADR-0009 `must_change_password` compensating control, then mint a
  new session + access token (F10).
- `refresh_session`: exchange a valid, non-revoked, non-expired refresh
  token for a fresh access token, rotating the refresh token and sliding
  the session's expiry (F12).

Logout (revoke-current-session) needs no dedicated business logic beyond
what `app.services.sessions.revoke_session` already provides — see
`app.api.auth.logout`.

Every failure path raises a narrow, named exception; `app.api.auth` maps
each to the exact frozen-contract status code. None of these exceptions
carry which specific check failed on the wire (F11's "no field-level
disclosure" applies to `InvalidCredentialsError` in particular: a bad
email and a bad password are indistinguishable to the caller).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from ipaddress import IPv4Address, IPv6Address

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.jwt import create_access_token
from app.core.security import hash_password, verify_password
from app.core.token_hash import hash_refresh_token
from app.models.session import Session
from app.models.user import User
from app.services.sessions import create_session, extend_session_expiry, generate_raw_refresh_token

logger = logging.getLogger(__name__)

# A fixed, precomputed bcrypt hash of a non-real password, verified against
# whenever no user matches the supplied email. This keeps the "no such
# user" path doing the same bcrypt-verify work (and therefore a comparable
# amount of time) as the "user exists, password wrong" path, so a caller
# cannot use response latency to enumerate valid emails (F11). Computed
# once at import time, not per-request.
_DUMMY_PASSWORD_HASH = hash_password("not-a-real-password-used-only-for-timing-parity")


class InvalidCredentialsError(Exception):
    """Bad email or bad password — uniform, non-field-revealing (F11)."""


class AccountDeactivatedError(Exception):
    """`users.is_active is False` (403, "account deactivated")."""


class MustChangePasswordError(Exception):
    """ADR-0009 compensating control: login refused until password rotation.

    Raised only for credentials that are otherwise valid and for an
    active account — i.e. the caller has proven they know the password,
    but the account is flagged `must_change_password` (the env-seeded
    bootstrap System Admin, or any account explicitly flagged that way in
    the future).
    """


class InvalidRefreshTokenError(Exception):
    """Refresh token is missing/unknown, revoked, or expired (F12)."""


@dataclass(frozen=True, slots=True)
class LoginResult:
    """Successful login outcome: the user plus a freshly minted session."""

    user: User
    access_token: str
    expires_in: int
    refresh_token: str


@dataclass(frozen=True, slots=True)
class RefreshResult:
    """Successful refresh outcome: a fresh access token and rotated refresh token."""

    access_token: str
    expires_in: int
    refresh_token: str


async def authenticate_and_login(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    settings: Settings,
    user_agent: str | None = None,
    ip_address: IPv4Address | IPv6Address | str | None = None,
) -> LoginResult:
    """Verify credentials and, if permitted, mint a new session (F10).

    Order of checks (each an early, distinct failure per the frozen
    contract and database design's login-flow note):

    1. Credentials (email lookup + password verify) → `InvalidCredentialsError`.
    2. `users.is_active` → `AccountDeactivatedError`.
    3. `users.must_change_password` (ADR-0009) → `MustChangePasswordError`.

    Does not commit; the caller (`app.api.auth.login`) relies on
    `app.db.session.get_db_session`'s commit-on-clean-exit.
    """

    stmt = select(User).where(func.lower(User.email) == email.strip().lower())
    user = await db.scalar(stmt)

    if user is None:
        # No such user: still run a bcrypt verify against a dummy hash so
        # this path costs about the same as "user exists, wrong password"
        # (F11 — no timing side-channel for email enumeration).
        verify_password(password, _DUMMY_PASSWORD_HASH)
        raise InvalidCredentialsError("No user matches the supplied email.")

    if not verify_password(password, user.hashed_password):
        raise InvalidCredentialsError("Password does not match.")

    if not user.is_active:
        raise AccountDeactivatedError("Account is deactivated.")

    if user.must_change_password:
        raise MustChangePasswordError("Password must be changed before login is permitted.")

    created = await create_session(
        db,
        user_id=user.id,
        session_ttl_days=settings.session_ttl_days,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    access_token, expires_in = create_access_token(
        user_id=str(user.id), session_id=str(created.session.id), settings=settings
    )

    logger.info(
        "user logged in",
        extra={"user_id": str(user.id), "session_id": str(created.session.id)},
    )

    return LoginResult(
        user=user,
        access_token=access_token,
        expires_in=expires_in,
        refresh_token=created.raw_refresh_token,
    )


async def refresh_session(
    db: AsyncSession,
    *,
    raw_refresh_token: str,
    settings: Settings,
) -> RefreshResult:
    """Exchange a refresh token for a fresh access token, rotating it (F12).

    Looks the session up by `refresh_token_hash` (`uq_sessions_refresh_hash`),
    rejects it if revoked/expired/unknown or if the owning user is no
    longer active, then rotates the stored hash to a freshly minted raw
    token and slides `expires_at` forward (`extend_session_expiry`).

    Does not touch the Redis revocation cache: rotation does not change
    whether the session is active, so no cache invalidation is required
    (unlike `revoke_session`, which does flip that state).
    """

    token_hash = hash_refresh_token(raw_refresh_token)
    session = await db.scalar(select(Session).where(Session.refresh_token_hash == token_hash))

    now = datetime.now(UTC)
    if session is None or session.revoked_at is not None or session.expires_at <= now:
        raise InvalidRefreshTokenError("Refresh token is invalid, revoked, or expired.")

    user = await db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise InvalidRefreshTokenError("Refresh token's owning account is no longer active.")

    new_raw_token = generate_raw_refresh_token()
    session.refresh_token_hash = hash_refresh_token(new_raw_token)
    extend_session_expiry(session, session_ttl_days=settings.session_ttl_days, now=now)
    await db.flush()

    access_token, expires_in = create_access_token(
        user_id=str(user.id), session_id=str(session.id), settings=settings
    )

    logger.info(
        "session refreshed",
        extra={"user_id": str(user.id), "session_id": str(session.id)},
    )

    return RefreshResult(
        access_token=access_token,
        expires_in=expires_in,
        refresh_token=new_raw_token,
    )
