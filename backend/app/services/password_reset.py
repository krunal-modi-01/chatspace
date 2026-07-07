"""Password-reset token issuance and validation (T16, F15-F17, R48).

Owns the lifecycle of a `password_reset_tokens` row: minting a new,
single-use, 1-hour token while sweeping (invalidating) any earlier
outstanding token for the same user (F17 — "only the latest issued token
validates"), and looking one up by its raw value without yet consuming it
so a caller can run further validation (e.g. new-password policy) before
committing to burning the token.

The raw reset token is generated here (high-entropy,
`secrets.token_urlsafe`) and returned exactly once by
`create_password_reset_token`; only its SHA-256 hash
(`app.core.token_hash.hash_reset_token`) is ever persisted, logged, or
compared. Nothing in this module logs the raw token, the reset link, or
the recipient's email address.

Does **not** implement the `/v1/auth/password-reset*` HTTP endpoints
(T16's `app.api.password`) or send email (`app.services.email`,
T11) — those are separate consumers that call into this module.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import generate_id
from app.core.token_hash import hash_reset_token
from app.models.password_reset_token import PasswordResetToken

logger = logging.getLogger(__name__)

# 256 bits of entropy, base64url-encoded — matches the "opaque secret"
# construction already used for refresh tokens (`app.services.sessions`).
_RAW_RESET_TOKEN_BYTES = 32

# 1-hour single-use lifetime (R48, frozen database design).
RESET_TOKEN_TTL = timedelta(hours=1)


def generate_raw_reset_token() -> str:
    """Return a new, cryptographically random opaque password-reset token.

    Never logged by this or any other function in this module — callers
    (the `/v1/auth/password-reset*` endpoints) must uphold the same
    guarantee: the raw token is never returned in an API response body
    and never logged.
    """

    return secrets.token_urlsafe(_RAW_RESET_TOKEN_BYTES)


@dataclass(frozen=True, slots=True)
class CreatedResetToken:
    """A newly minted reset token plus the one-time raw value.

    `raw_token` is intentionally the only place the raw value ever
    appears after this call returns — the caller must embed it in the
    reset-link email and then discard it, never persist or log it.
    """

    token: PasswordResetToken
    raw_token: str


async def invalidate_outstanding_reset_tokens(
    db: AsyncSession, user_id: UUID, *, now: datetime | None = None
) -> None:
    """Mark every currently-unused reset token for `user_id` as used (F17).

    Backed by `ix_prt_user_active` (partial index on `user_id WHERE
    used_at IS NULL`). Sweeping prior tokens on every new issue is what
    makes "only the latest token validates" true — an earlier token found
    later by `find_valid_reset_token` will already have a non-null
    `used_at` and therefore resolve to the frozen `410` (superseded).
    """

    ts = now or datetime.now(UTC)
    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.used_at.is_(None),
        )
    )
    outstanding = list(result.scalars())
    for token in outstanding:
        token.used_at = ts
    if outstanding:
        await db.flush()


async def create_password_reset_token(
    db: AsyncSession, *, user_id: UUID, now: datetime | None = None
) -> CreatedResetToken:
    """Issue a new single-use, 1-hour reset token for `user_id`.

    Invalidates any earlier outstanding token for the same user first
    (F17), then stores only the SHA-256 hash of the freshly minted raw
    token (`password_reset_tokens.token_hash`); the raw value is returned
    once via `CreatedResetToken.raw_token` and never persisted.
    """

    ts = now or datetime.now(UTC)
    await invalidate_outstanding_reset_tokens(db, user_id, now=ts)

    raw_token = generate_raw_reset_token()
    token = PasswordResetToken(
        id=generate_id(),
        user_id=user_id,
        token_hash=hash_reset_token(raw_token),
        expires_at=ts + RESET_TOKEN_TTL,
        used_at=None,
    )
    db.add(token)
    await db.flush()

    logger.info(
        "password reset token issued",
        extra={"user_id": str(user_id), "reset_token_id": str(token.id)},
    )

    return CreatedResetToken(token=token, raw_token=raw_token)


async def find_valid_reset_token(
    db: AsyncSession, raw_token: str, *, now: datetime | None = None
) -> PasswordResetToken | None:
    """Look up a reset token by its raw value **without consuming it**.

    Returns `None` for any invalid token: unknown hash, already used, or
    expired — every one of those maps to the same frozen `410` at the
    endpoint layer (F17), so this function deliberately does not
    distinguish between them to its caller.

    Read-only by design: the caller runs further validation (new-password
    policy, `422`) *before* deciding to burn the token via
    `mark_reset_token_used`, so a policy failure never wastes the
    single-use token — the requester can retry with a compliant password
    using the same still-valid link.
    """

    ts = now or datetime.now(UTC)
    token_hash = hash_reset_token(raw_token)
    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    token = result.scalar_one_or_none()

    if token is None or token.used_at is not None or token.expires_at <= ts:
        return None
    return token


def mark_reset_token_used(token: PasswordResetToken, *, now: datetime | None = None) -> None:
    """Mark `token` as consumed (single-use, F17).

    Mutates `token` in place; the caller is expected to be inside the same
    unit of work that also updates the user's `hashed_password` so both
    changes commit atomically.
    """

    token.used_at = now or datetime.now(UTC)
