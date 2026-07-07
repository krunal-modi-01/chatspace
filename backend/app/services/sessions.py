"""Session store CRUD (T10, ADR-0006).

Owns the lifecycle of a `sessions` row: minting a new session with a
hashed refresh token and 30-day sliding expiry, listing a user's active
sessions, and revoking one. Does **not** implement login/refresh/logout
endpoints (T15) or WS revalidation (T23) — those are separate consumers
that will call into this module.

The raw refresh token is generated here (high-entropy, `secrets.token_urlsafe`)
and returned exactly once to the caller; only its SHA-256 hash
(`app.core.token_hash.hash_refresh_token`) is ever persisted, logged, or
compared. Nothing in this module logs `raw_refresh_token`.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum, auto
from ipaddress import IPv4Address, IPv6Address
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import generate_id
from app.core.token_hash import hash_refresh_token
from app.models.session import Session

logger = logging.getLogger(__name__)

# 256 bits of entropy, base64url-encoded — matches the "opaque secret" the
# contract describes for the refresh token; `hash_refresh_token` never
# needs to salt this because the input space is already astronomically
# large (see that module's docstring).
_RAW_REFRESH_TOKEN_BYTES = 32


def generate_raw_refresh_token() -> str:
    """Return a new, cryptographically random opaque refresh token.

    Never logged by this or any other function in this module — callers
    (e.g. the future login/refresh endpoints, T15) must uphold the same
    guarantee.
    """

    return secrets.token_urlsafe(_RAW_REFRESH_TOKEN_BYTES)


@dataclass(frozen=True, slots=True)
class CreatedSession:
    """A newly minted session plus the one-time raw refresh token.

    `raw_refresh_token` is intentionally the only place the raw value ever
    appears after this call returns — the caller must hand it to the
    client and then discard it, never persist or log it.
    """

    session: Session
    raw_refresh_token: str


async def create_session(
    db: AsyncSession,
    *,
    user_id: UUID,
    session_ttl_days: int,
    user_agent: str | None = None,
    ip_address: IPv4Address | IPv6Address | str | None = None,
    now: datetime | None = None,
) -> CreatedSession:
    """Create a new session row for `user_id` with a 30-day sliding expiry.

    Stores only the SHA-256 hash of the freshly minted raw refresh token
    (`sessions.refresh_token_hash`); the raw value is returned once via
    `CreatedSession.raw_refresh_token` and never persisted.
    """

    issued_at = now or datetime.now(UTC)
    raw_token = generate_raw_refresh_token()

    session = Session(
        id=generate_id(),
        user_id=user_id,
        refresh_token_hash=hash_refresh_token(raw_token),
        user_agent=user_agent,
        ip_address=ip_address,
        issued_at=issued_at,
        last_used_at=None,
        expires_at=issued_at + timedelta(days=session_ttl_days),
        revoked_at=None,
    )
    db.add(session)
    await db.flush()

    logger.info(
        "session created",
        extra={"user_id": str(user_id), "session_id": str(session.id)},
    )

    return CreatedSession(session=session, raw_refresh_token=raw_token)


async def get_session(db: AsyncSession, session_id: UUID) -> Session | None:
    """Return the `sessions` row for `session_id`, or `None`."""

    return await db.get(Session, session_id)


async def list_active_sessions_for_user(db: AsyncSession, user_id: UUID) -> list[Session]:
    """Return every non-revoked session for `user_id`, most recently issued first.

    Backed by `ix_sessions_user_active` (partial index on `user_id WHERE
    revoked_at IS NULL`) — this is also the query the Postgres fallback for
    "revoke all of a user's sessions" (deactivation, out of T10 scope) will
    reuse.
    """

    result = await db.execute(
        select(Session)
        .where(Session.user_id == user_id, Session.revoked_at.is_(None))
        .order_by(Session.issued_at.desc())
    )
    return list(result.scalars().all())


def extend_session_expiry(
    session: Session, *, session_ttl_days: int, now: datetime | None = None
) -> None:
    """Slide `session.expires_at` forward on refresh-token use.

    Mutates `session` in place (caller is expected to be inside a
    session-bound unit of work, e.g. the future refresh-token exchange
    endpoint, T15) and stamps `last_used_at`.
    """

    current_time = now or datetime.now(UTC)
    session.last_used_at = current_time
    session.expires_at = current_time + timedelta(days=session_ttl_days)


class RevokeOutcome(Enum):
    """Result of attempting to revoke a session (DELETE `/v1/auth/sessions/{id}`)."""

    REVOKED = auto()
    """Session existed and belonged to `user_id`; now revoked (idempotent —
    also returned if it was already revoked)."""

    NOT_FOUND = auto()
    """No session with that id exists at all."""

    FORBIDDEN = auto()
    """Session exists but belongs to a different user."""


async def revoke_session(
    db: AsyncSession,
    *,
    session_id: UUID,
    user_id: UUID,
    now: datetime | None = None,
) -> RevokeOutcome:
    """Revoke `session_id` on behalf of `user_id`.

    Idempotent: revoking an already-revoked session owned by `user_id`
    still returns `REVOKED` (matches the contract's logout idempotency
    rule, extended to the explicit-session-id revoke path). Does **not**
    touch the Redis revocation cache — callers must call
    `app.services.session_revocation.invalidate_session_cache` afterward
    so a revoked session fails within the same request cycle rather than
    waiting for the cache TTL to lapse.
    """

    session = await db.get(Session, session_id)
    if session is None:
        return RevokeOutcome.NOT_FOUND
    if session.user_id != user_id:
        return RevokeOutcome.FORBIDDEN

    if session.revoked_at is None:
        session.revoked_at = now or datetime.now(UTC)
        await db.flush()
        logger.info(
            "session revoked",
            extra={"user_id": str(user_id), "session_id": str(session_id)},
        )

    return RevokeOutcome.REVOKED
