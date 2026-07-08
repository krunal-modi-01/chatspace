"""Admin user directory + deactivate/reactivate business logic (T44, T20-as-specced).

Owns:

- `list_admin_users`: a cursor-paginated, optionally `q`/`status`-filtered
  browse of every user (active AND deactivated), reusing the T07 keyset
  pagination utility over `(created_at, id)` for consistency with
  ADR-0003 — same style as `app.services.invites.list_invites` (T43).
- `_lock_and_count_active_system_admins`: the row-locking guard query
  behind the frozen `409 | last active System Admin` rule (F27),
  serializing concurrent deactivations so the workspace can never race to
  zero admins.
- `deactivate_user` / `reactivate_user`: the never-built T20 logic,
  landing here per the T44 task breakdown. Deactivation (a) is a no-op
  for an already-inactive user (idempotent, matching
  `app.services.invites.revoke_invite`'s idempotency shape), (b) refuses
  to remove the *last* active System Admin, (c) runs
  `app.services.channels.run_sole_admin_succession` for every channel
  where the target is the sole admin (F36/R51) BEFORE flipping
  `is_active`, and (d) revokes every active session for the target via
  `app.services.sessions.revoke_sessions_for_user` (T10) in the same
  transaction. Callers (`app.api.admin`) own the Redis
  revocation-cache invalidation and the commit boundary, mirroring how
  `app.services.sessions.revoke_session` divides that responsibility.

Does **not** implement the HTTP endpoints, request-body parsing, or
status-code mapping — see `app.api.admin` for that. Never selects or
returns `hashed_password`; only the fields `AdminUserListItem` /
`AdminUserActionResponse` name explicitly ever reach a caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import CursorKey, Page, apply_keyset, paginate_rows
from app.models.user import User
from app.services.channels import run_sole_admin_succession
from app.services.sessions import revoke_sessions_for_user

if TYPE_CHECKING:
    from sqlalchemy import ColumnElement

AdminUserStatusFilter = Literal["active", "inactive"]


def _escape_like(value: str) -> str:
    """Escape `%`/`_`/backslash so a search term can't smuggle SQL `LIKE` wildcards.

    Not a security boundary in the injection sense (the value is already
    bound as a parameter) — purely so a search for a literal `%` or `_`
    in a name/email behaves as the admin expects rather than matching
    everything.
    """

    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_admin_users(
    db: AsyncSession,
    *,
    q: str | None = None,
    status_filter: AdminUserStatusFilter | None = None,
    limit: int,
    cursor: CursorKey | None = None,
) -> Page[User]:
    """Cursor-paginated user directory, searchable and including deactivated users (F72).

    `q` matches `first_name`/`last_name`/`username`/`email`
    case-insensitively (any substring match, any one column). `limit`
    must already be resolved/clamped by the caller
    (`app.core.pagination.resolve_limit`).
    """

    stmt = select(User)

    stripped_q = q.strip() if q else None
    if stripped_q:
        pattern = f"%{_escape_like(stripped_q)}%"
        stmt = stmt.where(
            or_(
                User.first_name.ilike(pattern, escape="\\"),
                User.last_name.ilike(pattern, escape="\\"),
                User.username.ilike(pattern, escape="\\"),
                User.email.ilike(pattern, escape="\\"),
            )
        )

    if status_filter == "active":
        stmt = stmt.where(User.is_active.is_(True))
    elif status_filter == "inactive":
        stmt = stmt.where(User.is_active.is_(False))

    stmt = apply_keyset(
        stmt,
        created_at_col=cast("ColumnElement[datetime]", User.created_at),
        id_col=cast("ColumnElement[UUID]", User.id),
        cursor=cursor,
    ).limit(limit + 1)

    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    return paginate_rows(
        rows,
        limit=limit,
        cursor_key=lambda user: CursorKey(created_at=user.created_at, id=user.id),
    )


async def _lock_and_count_active_system_admins(db: AsyncSession) -> int:
    """Count active System Admins while holding a row lock on each — the F27 guard.

    A plain count is a TOCTOU hazard under READ COMMITTED: two concurrent
    `deactivate` requests targeting the two *last* admins could each read
    `count == 2`, both pass the `<= 1` check, and both commit — leaving
    **zero** active System Admins (a full workspace lockout F27 exists to
    prevent). Selecting the active-admin rows `FOR UPDATE` (in a
    deterministic `id` order, so two racing transactions can't deadlock)
    serializes those requests: the second one blocks until the first
    commits, then re-reads the now-smaller set under the lock and correctly
    refuses with `LAST_ACTIVE_SYSTEM_ADMIN`. Must be called inside the
    caller's (uncommitted) transaction, before the compare-and-flip.
    """

    result = await db.execute(
        select(User.id)
        .where(User.is_system_admin.is_(True), User.is_active.is_(True))
        .order_by(User.id)
        .with_for_update()
    )
    return len(result.scalars().all())


class DeactivateOutcome(Enum):
    """Result of attempting to deactivate a user (`POST .../deactivate`)."""

    DEACTIVATED = auto()
    """Target was active; now deactivated, sessions revoked, succession applied."""

    ALREADY_INACTIVE = auto()
    """Target was already inactive; idempotent no-op (no further effect)."""

    LAST_ACTIVE_SYSTEM_ADMIN = auto()
    """Target is the sole active System Admin — rejected (F27, caller maps to `409`)."""


@dataclass(frozen=True, slots=True)
class DeactivationResult:
    """The outcome plus enough detail for the caller's content-free audit log."""

    outcome: DeactivateOutcome
    revoked_session_ids: list[UUID]
    promoted_channel_ids: list[UUID]


async def deactivate_user(
    db: AsyncSession, *, target: User, now: datetime | None = None
) -> DeactivationResult:
    """Deactivate `target` per F25/F27/F36 — the never-built T20 logic (T44).

    Order of operations, all in the caller's transaction (caller commits
    or rolls back based on `outcome`):

    1. Already inactive -> `ALREADY_INACTIVE`, no side effects at all
       (idempotent; mirrors `revoke_invite`'s "re-asserting an already-set
       state is a no-op" shape).
    2. Target is the sole active System Admin -> `LAST_ACTIVE_SYSTEM_ADMIN`,
       no mutation performed (F27) — the caller must roll back.
    3. Otherwise: run channel succession for every channel where `target`
       is the sole admin (F36/R51), flip `is_active = False`, then revoke
       every active session for `target` (T10). Returns the revoked
       session ids so the caller can bust each one's Redis
       revocation-cache entry immediately (this function only touches
       Postgres, same division of responsibility as
       `app.services.sessions.revoke_sessions_for_user` itself).
    """

    if not target.is_active:
        return DeactivationResult(
            outcome=DeactivateOutcome.ALREADY_INACTIVE,
            revoked_session_ids=[],
            promoted_channel_ids=[],
        )

    if target.is_system_admin:
        active_admin_count = await _lock_and_count_active_system_admins(db)
        if active_admin_count <= 1:
            return DeactivationResult(
                outcome=DeactivateOutcome.LAST_ACTIVE_SYSTEM_ADMIN,
                revoked_session_ids=[],
                promoted_channel_ids=[],
            )

    promoted_channel_ids = await run_sole_admin_succession(db, departing_user_id=target.id)

    target.is_active = False
    await db.flush()

    revoked_session_ids = await revoke_sessions_for_user(db, user_id=target.id, now=now)

    return DeactivationResult(
        outcome=DeactivateOutcome.DEACTIVATED,
        revoked_session_ids=revoked_session_ids,
        promoted_channel_ids=promoted_channel_ids,
    )


def reactivate_user(target: User) -> bool:
    """Flip `target.is_active = True` if not already, per F26.

    Deliberately does **not** restore any prior session (F26: "login
    restored with a fresh session (prior sessions not restored)") — the
    next `POST /v1/auth/login` mints a brand-new session normally; this
    function only clears the login gate. Returns whether a mutation
    actually happened (idempotent: reactivating an already-active user is
    a no-op, caller decides whether to commit).
    """

    if target.is_active:
        return False
    target.is_active = True
    return True
