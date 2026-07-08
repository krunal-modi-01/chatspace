"""Invite lifecycle (T13, F1, R45): issuance, validation, rotation, revocation.

Owns the lifecycle of an `invites` row: minting a new single-use, 7-day
token (sweeping is not needed here — unlike password-reset tokens, an
invite is looked up/rotated by its own `id`, not "the latest for this
user"), looking one up by its raw value without consuming it (`GET
/v1/invites/{token}` does not redeem), rotating the token on resend, and
revoking.

The raw invite token is generated here (high-entropy,
`secrets.token_urlsafe`) and returned exactly once per mint/rotate call;
only its SHA-256 hash (`app.core.token_hash.hash_invite_token`) is ever
persisted. Nothing in this module logs the raw token, the invite link, or
the recipient's email address — log lines carry only ids and booleans
(content-free audit events, R24).

Does **not** implement the `/v1/invites*` HTTP endpoints (`app.api.invites`)
or send email (`app.services.email`, T11) — those are separate consumers
that call into this module. `redeem_invite` (T14) is the one piece of the
redemption path that lives here (mirroring `revoke_invite`'s shape); the
rest of `POST /v1/auth/register` (user creation, duplicate/password
validation, transaction boundary) lives in `app.api.auth` and
`app.services.registration`.

`list_invites` (T43) is the read side: a cursor-paginated, optionally
`status`-filtered browse of every invite ever issued, reusing the T07
keyset pagination utility over `(created_at, id)` for consistency with
ADR-0003. It performs no mutation and, like every other function here,
never selects or logs the raw token — only `Invite` rows (whose only
persisted secret is `token_hash`) come back to the caller.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import generate_id
from app.core.pagination import CursorKey, Page, apply_keyset, paginate_rows

if TYPE_CHECKING:
    from sqlalchemy import ColumnElement
from app.core.token_hash import hash_invite_token
from app.models.invite import Invite, InviteStatus
from app.models.user import User

logger = logging.getLogger(__name__)

InviteListStatusFilter = Literal["pending", "accepted", "revoked", "expired"]

# 256 bits of entropy, base64url-encoded — matches the construction already
# used for refresh tokens (`app.services.sessions`) and reset tokens
# (`app.services.password_reset`).
_RAW_INVITE_TOKEN_BYTES = 32

# Single-use, 7-day lifetime (frozen database design: "expires_at ... 7
# days from issue").
INVITE_TOKEN_TTL = timedelta(days=7)


def generate_raw_invite_token() -> str:
    """Return a new, cryptographically random opaque invite token.

    Never logged by this or any other function in this module — callers
    (the `/v1/invites*` endpoints) must uphold the same guarantee: the raw
    token is never returned in an API response body and never logged.
    """

    return secrets.token_urlsafe(_RAW_INVITE_TOKEN_BYTES)


@dataclass(frozen=True, slots=True)
class CreatedInvite:
    """A newly minted invite plus the one-time raw token value.

    `raw_token` is intentionally the only place the raw value ever
    appears after this call returns — the caller must embed it in the
    invite-link email and then discard it, never persist or log it.
    """

    invite: Invite
    raw_token: str


async def is_email_registered(db: AsyncSession, email: str) -> bool:
    """Case-insensitive check against `users`, mirroring `uq_users_email_lower`.

    Backs the frozen `409 | Email is already a registered user` response
    on `POST /v1/invites`.
    """

    result = await db.execute(
        select(User.id).where(func.lower(User.email) == email.strip().lower())
    )
    return result.scalar_one_or_none() is not None


async def create_invite(
    db: AsyncSession, *, email: str, created_by: UUID, now: datetime | None = None
) -> CreatedInvite:
    """Issue a new single-use, 7-day invite for `email` (F1).

    Stores only the SHA-256 hash of the freshly minted raw token
    (`invites.token_hash`); the raw value is returned once via
    `CreatedInvite.raw_token` and never persisted. Does not check for an
    already-registered email or send the invite email — those are the
    caller's (`app.api.invites`) responsibility, since a delivery failure
    there must roll back this row too (fail-loud, no dangling invite).
    """

    ts = now or datetime.now(UTC)
    raw_token = generate_raw_invite_token()
    invite = Invite(
        id=generate_id(),
        email=email,
        token_hash=hash_invite_token(raw_token),
        status=InviteStatus.PENDING,
        created_by=created_by,
        expires_at=ts + INVITE_TOKEN_TTL,
    )
    db.add(invite)
    await db.flush()

    # Audit logging deliberately deferred to the caller (`app.api.invites`):
    # this row is not yet committed, and the caller may still roll it back
    # (e.g. email delivery failure) — logging here would leave a false
    # "issued" audit entry for an invite that never persisted.
    return CreatedInvite(invite=invite, raw_token=raw_token)


async def find_valid_invite_by_token(
    db: AsyncSession, raw_token: str, *, now: datetime | None = None
) -> Invite | None:
    """Look up an invite by its raw token **without consuming it**.

    Returns `None` for any unusable token: unknown hash, non-`pending`
    status (accepted/revoked), or expired — every one of those maps to the
    same frozen `410` at the endpoint layer, so this function deliberately
    does not distinguish between them to its caller (uniform, non-
    enumerating behavior).
    """

    ts = now or datetime.now(UTC)
    token_hash = hash_invite_token(raw_token)
    result = await db.execute(select(Invite).where(Invite.token_hash == token_hash))
    invite = result.scalar_one_or_none()

    if invite is None or invite.status is not InviteStatus.PENDING or invite.expires_at <= ts:
        return None
    return invite


async def rotate_invite_token(
    db: AsyncSession, invite: Invite, *, now: datetime | None = None
) -> str:
    """Overwrite `invite.token_hash` with a freshly minted token (resend, F1).

    The prior token becomes unresolvable immediately (its hash is
    overwritten), so a subsequent `GET /v1/invites/{old_token}` returns
    `410`. Keeps `status` at `pending` and resets `expires_at` to a fresh
    7-day window. Caller is responsible for the commit boundary: on an
    email-delivery failure after calling this, the caller must roll back
    rather than commit, so the prior token remains valid (fail-loud, no
    silently-broken invite).
    """

    ts = now or datetime.now(UTC)
    raw_token = generate_raw_invite_token()
    invite.token_hash = hash_invite_token(raw_token)
    invite.expires_at = ts + INVITE_TOKEN_TTL
    await db.flush()
    return raw_token


def revoke_invite(invite: Invite) -> None:
    """Mark `invite` as revoked (soft revoke; row retained for audit, F1).

    Idempotent by construction: revoking an already-revoked invite just
    re-asserts the same status. Callers must reject (`409`) revoking an
    `accepted` invite *before* calling this — this function does not
    itself enforce that state-transition rule.
    """

    invite.status = InviteStatus.REVOKED


def redeem_invite(invite: Invite, *, now: datetime | None = None) -> None:
    """Mark `invite` as redeemed (`pending -> accepted`) on successful registration (T14).

    Mirrors `revoke_invite`'s shape: a pure in-memory mutation, no flush/
    commit of its own — the caller (`POST /v1/auth/register`) sets this in
    the *same* transaction as the new user's `INSERT` and flushes/commits
    both together, so a downstream failure (e.g. a duplicate-username/email
    `IntegrityError`) rolls this back too and the invite remains `pending`
    and redeemable.

    Callers must have already obtained `invite` via
    `find_valid_invite_by_token` (or an equivalent pending+unexpired check)
    — this function does not itself re-validate status/expiry, matching
    `revoke_invite`'s division of responsibility.
    """

    ts = now or datetime.now(UTC)
    invite.status = InviteStatus.ACCEPTED
    invite.accepted_at = ts


async def list_invites(
    db: AsyncSession,
    *,
    status_filter: InviteListStatusFilter | None = None,
    limit: int,
    cursor: CursorKey | None = None,
    now: datetime | None = None,
) -> Page[Invite]:
    """Cursor-paginated, optionally `status`-filtered browse of all invites (T43).

    `status_filter` narrows on the *wire* status, not the raw persisted
    `InviteStatus` — `"expired"` is derived (`pending` AND `expires_at <=
    now`) and `"pending"` on this filter means "pending and not yet
    expired", matching `find_valid_invite_by_token`'s own definition of a
    redeemable invite. `None` returns every invite regardless of status.

    Ordered `(created_at, id)` DESC (most recently issued first) via the
    T07 keyset utility; `limit` must already be resolved/clamped by the
    caller (`app.core.pagination.resolve_limit`).
    """

    ts = now or datetime.now(UTC)
    stmt = select(Invite)

    if status_filter == "pending":
        stmt = stmt.where(Invite.status == InviteStatus.PENDING, Invite.expires_at > ts)
    elif status_filter == "expired":
        stmt = stmt.where(Invite.status == InviteStatus.PENDING, Invite.expires_at <= ts)
    elif status_filter == "accepted":
        stmt = stmt.where(Invite.status == InviteStatus.ACCEPTED)
    elif status_filter == "revoked":
        stmt = stmt.where(Invite.status == InviteStatus.REVOKED)

    stmt = apply_keyset(
        stmt,
        created_at_col=cast("ColumnElement[datetime]", Invite.created_at),
        id_col=cast("ColumnElement[UUID]", Invite.id),
        cursor=cursor,
    ).limit(limit + 1)

    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    return paginate_rows(
        rows,
        limit=limit,
        cursor_key=lambda invite: CursorKey(created_at=invite.created_at, id=invite.id),
    )
