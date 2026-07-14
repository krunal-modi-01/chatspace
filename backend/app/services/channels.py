"""Channel create/get/public-browse/membership business logic (T18/T19, F29-F37).

Owns the transactional and query logic behind `/v1/channels*`:

- `create_channel`: inserts a `channels` row plus a `channel_members` row
  recording the creator as the first `admin` (R4), in one flush — a
  concurrent duplicate-name race surfaces as `IntegrityError` at flush
  time (caught by the caller, `app.api.channels`, and mapped to `409`).
- `get_channel_view`: the single point-lookup + membership-probe path
  behind `GET /v1/channels/{id}`'s uniform-404 rule — a private channel a
  non-member cannot see is returned as `None`, exactly like a truly
  missing channel, so the route layer cannot accidentally leak existence.
- `list_public_channels`: the offset-paginated, membership-excluding query
  behind `GET /v1/channels/public`, plus the matching `COUNT(*)` for the
  envelope's `total`.
- `list_my_channels` (T48, F73): the cursor-paginated, membership-*including*
  counterpart — every channel (public and private) the caller belongs to,
  reusing the T07 keyset pagination utility (`app.core.pagination`) over
  `(created_at, id)` for consistency with ADR-0003, and the same
  `ChannelView` projection `get_channel_view` returns (`member_count` +
  the caller's own `my_role`, here always populated since every row comes
  from an inner join on the caller's own membership).
- `get_membership`: the **single reusable server-side membership-check
  primitive** (F34) — a plain point lookup on the `channel_members`
  composite PK. Every T19 membership endpoint below calls this rather
  than re-deriving its own query, and it is deliberately a plain async
  function (not a FastAPI `Depends`) so future non-HTTP callers (WS join,
  message read/write, media fetch) can reuse it identically outside a
  request/response cycle.
- `join_public_channel` / `leave_channel` / `list_channel_members` /
  `add_channel_member` / `change_member_role` / `remove_channel_member`
  (T19, F31-F37): the membership-mutation surface behind `POST
  /{id}/join`, `POST /{id}/leave`, `GET`/`POST /{id}/members`, and
  `PATCH`/`DELETE /{id}/members/{user_id}`.

Does **not** implement the HTTP endpoints themselves, request-body
parsing, or the `400`/`403`/`404`/`409`/`422` status-code mapping — see
`app.api.channels` for that.

`run_sole_admin_succession` implements the F36/F37 (R51) last-admin
succession rule. Originally added for T44 (System Admin deactivation) as
the single shared primitive so that T19's own `POST /leave` and `DELETE
/members/{user_id}` sole-admin paths could reuse it rather than
re-deriving the same rule a second time — now extended with an optional
`channel_id` scope (T19) so a single-channel leave/removal doesn't
inadvertently run succession across every *other* channel the departing
user happens to admin (T44's deactivate flow keeps its original
unscoped, all-channels behavior by omitting `channel_id`). The
sole-admin-count check underneath it now locks the channel's admin rows
`FOR UPDATE` (`_lock_channel_admin_ids`) so two concurrent
leave/removal/deactivation requests targeting the same channel's admin
set can never both observe "I'm the sole admin" and both attempt (or
skip) succession — the design's documented race the zero-admin/succession
logic must serialize against.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import TYPE_CHECKING, cast
from uuid import UUID

from sqlalchemy import Subquery, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import generate_id
from app.core.pagination import CursorKey, Page, apply_keyset, paginate_rows
from app.models.channel import Channel
from app.models.channel_member import ChannelMember, ChannelMemberRole
from app.models.user import User

if TYPE_CHECKING:
    from sqlalchemy import ColumnElement

# Mirrors the shipped `CHECK (name ~ '^[A-Za-z0-9 _-]{1,80}$')` constraint
# (R36) exactly — pre-validated here so a charset/length violation maps to
# the frozen `422` rather than falling through to a raw `IntegrityError`
# (which is reserved for the case-insensitive uniqueness `409`).
CHANNEL_NAME_RE = re.compile(r"^[A-Za-z0-9 _-]{1,80}$")

# Offset-pagination page size (frozen contract: "Page size default and
# maximum are 50"). Reused for `GET /{id}/members` (T19) for the same
# offset-pagination style, since the frozen contract does not specify a
# distinct page size for that endpoint.
PUBLIC_CHANNELS_DEFAULT_LIMIT = 50
PUBLIC_CHANNELS_MAX_LIMIT = 50
CHANNEL_MEMBERS_DEFAULT_LIMIT = 50
CHANNEL_MEMBERS_MAX_LIMIT = 50


def is_valid_channel_name(name: str) -> bool:
    """Return whether `name` satisfies the frozen charset/length rule (1-80, R36)."""

    return bool(CHANNEL_NAME_RE.match(name))


async def count_channel_members(db: AsyncSession, channel_id: UUID) -> int:
    """Return the current member count of `channel_id` (a plain `COUNT(*)`).

    Public (not `_`-prefixed) because `join_public_channel`/
    `add_channel_member` (T49/ADR-0012) call this *pre-commit*, right
    after the new membership row is flushed, to capture the count needed
    for the `channel.member_added` event's `data.channel.member_count`
    without a post-commit re-query (see those functions' docstrings) — the
    same query `get_channel_view`/`list_channel_members` already run for
    their own read paths.
    """

    result = await db.execute(
        select(func.count())
        .select_from(ChannelMember)
        .where(ChannelMember.channel_id == channel_id)
    )
    return int(result.scalar_one())


def _member_count_subquery() -> Subquery:
    """Build the `channel_id -> member_count` derived table shared by every
    channel-list query that needs a per-row member count alongside a page
    of `channels` rows (`list_public_channels`, `list_my_channels`).

    A plain `GROUP BY channel_id` count over the whole `channel_members`
    table; callers `outerjoin` this against `Channel` and
    `func.coalesce(...member_count, 0)` the result, so a channel with zero
    members (not otherwise reachable in practice, since every channel
    always has at least its creator, but defensive regardless) still
    counts as `0` rather than being dropped by an inner join.
    """

    return (
        select(
            ChannelMember.channel_id.label("channel_id"),
            func.count().label("member_count"),
        )
        .group_by(ChannelMember.channel_id)
        .subquery()
    )


async def create_channel(
    db: AsyncSession, *, name: str, is_private: bool, created_by: UUID
) -> Channel:
    """Insert a new channel and record `created_by` as its first admin (R4).

    Caller is responsible for pre-validating `name` via
    `is_valid_channel_name` (the `422` outcome) — this function assumes
    that has already happened and only guards against the case-insensitive
    uniqueness race (`IntegrityError` on `uq_channels_name_lower`, left to
    propagate uncaught so the caller can map it to `409`).
    """

    channel = Channel(id=generate_id(), name=name, is_private=is_private, created_by=created_by)
    db.add(channel)
    await db.flush()

    membership = ChannelMember(
        channel_id=channel.id, user_id=created_by, role=ChannelMemberRole.ADMIN
    )
    db.add(membership)
    await db.flush()

    return channel


@dataclass(frozen=True, slots=True)
class ChannelView:
    """A channel plus the viewer-specific fields `GET /v1/channels/{id}` needs."""

    channel: Channel
    member_count: int
    my_role: ChannelMemberRole | None


async def get_channel_view(
    db: AsyncSession, *, channel_id: UUID, caller_id: UUID
) -> ChannelView | None:
    """Return the caller's view of `channel_id`, or `None` if it must be hidden.

    Collapses two distinct database outcomes — "no such channel" and "a
    private channel the caller is not a member of" — into the same `None`
    result, which the route layer turns into a single uniform `404`
    (non-enumerating: a caller cannot distinguish "doesn't exist" from
    "exists but is private").
    """

    channel = await db.get(Channel, channel_id)
    if channel is None:
        return None

    membership = await db.get(ChannelMember, (channel_id, caller_id))
    if channel.is_private and membership is None:
        return None

    member_count = await count_channel_members(db, channel_id)
    my_role = membership.role if membership is not None else None
    return ChannelView(channel=channel, member_count=member_count, my_role=my_role)


@dataclass(frozen=True, slots=True)
class PublicChannelRow:
    """One row of a public-channel browse page, paired with its member count."""

    channel: Channel
    member_count: int


@dataclass(frozen=True, slots=True)
class PublicChannelPage:
    """The `{items, total}` result of a public-channel browse query."""

    rows: list[PublicChannelRow]
    total: int


async def list_public_channels(
    db: AsyncSession, *, caller_id: UUID, limit: int, offset: int
) -> PublicChannelPage:
    """Offset-paginated browse of public channels the caller is not a member of (F30).

    Excludes any channel with a `channel_members` row for `caller_id`
    (anti-join on `ix_channel_members_user`), ordered by `created_at, id`
    for stable pagination. `total` is a matching `COUNT(*)` over the same
    filter, not merely `len(rows)`.
    """

    member_channel_ids = select(ChannelMember.channel_id).where(ChannelMember.user_id == caller_id)
    base_filter = (Channel.is_private.is_(False)) & (Channel.id.not_in(member_channel_ids))

    total_result = await db.execute(select(func.count()).select_from(Channel).where(base_filter))
    total = int(total_result.scalar_one())

    member_count_subquery = _member_count_subquery()
    rows_result = await db.execute(
        select(Channel, func.coalesce(member_count_subquery.c.member_count, 0))
        .outerjoin(member_count_subquery, member_count_subquery.c.channel_id == Channel.id)
        .where(base_filter)
        .order_by(Channel.created_at, Channel.id)
        .offset(offset)
        .limit(limit)
    )
    rows = [
        PublicChannelRow(channel=channel, member_count=int(member_count))
        for channel, member_count in rows_result.all()
    ]

    return PublicChannelPage(rows=rows, total=total)


async def list_my_channels(
    db: AsyncSession, *, caller_id: UUID, limit: int, cursor: CursorKey | None = None
) -> Page[ChannelView]:
    """Cursor-paginated list of every channel `caller_id` belongs to (F73, T48).

    Unlike `list_public_channels` (which *excludes* the caller's own
    memberships for direct-join browsing), this is the "My channels"
    navigation read: public **and** private channels the caller is
    currently a member of, each paired with the caller's own `my_role` —
    reusing `ChannelView` (the same projection `get_channel_view` returns)
    rather than introducing a parallel shape. Scoped strictly to
    `caller_id`: the inner join on `channel_members` is keyed on
    `caller_id`, served by `ix_channel_members_user`, so no other user's
    memberships are ever reachable through this query.

    Ordered `(created_at, id)` DESC via the T07 keyset utility
    (`app.core.pagination`), matching ADR-0003 and the frozen contract;
    `limit` must already be resolved/clamped by the caller
    (`app.core.pagination.resolve_limit`, default 50 / clamp 100). Every
    returned `ChannelView.my_role` is guaranteed non-`None` — unlike
    `get_channel_view`'s viewer-may-be-a-non-member case — since a row
    only appears here at all because the inner join found the caller's own
    membership.
    """

    member_count_subquery = _member_count_subquery()

    stmt = (
        select(Channel, ChannelMember.role, func.coalesce(member_count_subquery.c.member_count, 0))
        .join(
            ChannelMember,
            (ChannelMember.channel_id == Channel.id) & (ChannelMember.user_id == caller_id),
        )
        .outerjoin(member_count_subquery, member_count_subquery.c.channel_id == Channel.id)
    )
    stmt = apply_keyset(
        stmt,
        created_at_col=cast("ColumnElement[datetime]", Channel.created_at),
        id_col=cast("ColumnElement[UUID]", Channel.id),
        cursor=cursor,
    ).limit(limit + 1)

    result = await db.execute(stmt)
    rows = [
        ChannelView(channel=channel, member_count=int(member_count), my_role=role)
        for channel, role, member_count in result.all()
    ]

    return paginate_rows(
        rows,
        limit=limit,
        cursor_key=lambda view: CursorKey(created_at=view.channel.created_at, id=view.channel.id),
    )


async def get_membership(
    db: AsyncSession, *, channel_id: UUID, user_id: UUID
) -> ChannelMember | None:
    """The single reusable server-side membership-check primitive (F34).

    A plain point lookup on the `channel_members` composite PK — O(log n),
    and the exact same query every T19 endpoint below (and, per the
    frozen contract, every future message/media/WS-join check) must run
    before trusting a client-supplied `channel_id`/`user_id` pair. Never
    trust a client-supplied role claim instead of re-reading this.
    """

    return await db.get(ChannelMember, (channel_id, user_id))


async def _lock_channel_admin_ids(db: AsyncSession, channel_id: UUID) -> list[UUID]:
    """Lock (`FOR UPDATE`) and return every admin's `user_id` for `channel_id`.

    The single serialization point behind both the F36 sole-admin
    succession decision and the F37 zero-admin `409` guard: selecting the
    channel's *current* admin rows `FOR UPDATE` (in a deterministic
    `user_id` order, mirroring `app.services.admin_users
    ._lock_and_count_active_system_admins`'s same anti-deadlock ordering)
    blocks a concurrent transaction racing to mutate the same channel's
    admin set until this one commits or rolls back — so two concurrent
    sole-admin leaves/removals can never both observe "I'm the only
    admin" for the same channel. Must be called inside the caller's
    (uncommitted) transaction, before any admin-count-dependent decision.
    """

    result = await db.execute(
        select(ChannelMember.user_id)
        .where(
            ChannelMember.channel_id == channel_id,
            ChannelMember.role == ChannelMemberRole.ADMIN,
        )
        .order_by(ChannelMember.user_id)
        .with_for_update()
    )
    return list(result.scalars().all())


async def run_sole_admin_succession(
    db: AsyncSession, *, departing_user_id: UUID, channel_id: UUID | None = None
) -> list[UUID]:
    """Promote a successor wherever `departing_user_id` is a channel's *sole* admin (F36/R51).

    For every channel where `departing_user_id` currently holds the
    `admin` role AND is the only admin of that channel, promotes the
    remaining member with the earliest `joined_at` (any role, not just
    `member`) to `admin` — matching F36 exactly ("the longest-standing
    remaining member ... is automatically promoted to admin"). If no
    other member remains, the channel is left with zero admins (F37, a
    valid terminal state) — this function does not itself remove
    `departing_user_id`'s membership row, since callers (deactivation;
    T19's leave/remove-member) own that decision and its timing
    independently.

    `channel_id`, when given, scopes the whole operation to that single
    channel (T19's `leave`/`DELETE /members/{user_id}`, which must never
    touch succession in any *other* channel the departing user happens to
    admin). Omitted entirely, the original T44 deactivation behavior is
    unchanged: every channel the departing user admins is considered.

    The per-channel admin-count check locks that channel's admin rows
    `FOR UPDATE` first (`_lock_channel_admin_ids`) so this decision is
    serialized against any other concurrent mutator of the same channel's
    admin set.

    Returns the ids of every channel where a promotion actually happened,
    so the caller can log a content-free audit line without re-deriving
    which channels changed. Flushes but does not commit — the caller owns
    the transaction boundary (mirrors every other mutator in this module).
    """

    admin_channel_ids_stmt = select(ChannelMember.channel_id).where(
        ChannelMember.user_id == departing_user_id,
        ChannelMember.role == ChannelMemberRole.ADMIN,
    )
    if channel_id is not None:
        admin_channel_ids_stmt = admin_channel_ids_stmt.where(
            ChannelMember.channel_id == channel_id
        )
    admin_channel_ids_result = await db.execute(admin_channel_ids_stmt)
    admin_channel_ids = [row[0] for row in admin_channel_ids_result.all()]

    promoted_channel_ids: list[UUID] = []
    for admin_channel_id in admin_channel_ids:
        locked_admin_ids = await _lock_channel_admin_ids(db, admin_channel_id)
        if len(locked_admin_ids) != 1:
            continue  # not the sole admin — no succession needed

        successor_result = await db.execute(
            select(ChannelMember)
            .where(
                ChannelMember.channel_id == admin_channel_id,
                ChannelMember.user_id != departing_user_id,
            )
            .order_by(ChannelMember.joined_at.asc())
            .limit(1)
        )
        successor = successor_result.scalar_one_or_none()
        if successor is None:
            continue  # F37: no other members — channel persists with zero admins

        successor.role = ChannelMemberRole.ADMIN
        promoted_channel_ids.append(admin_channel_id)

    if promoted_channel_ids:
        await db.flush()

    return promoted_channel_ids


# ── T19: membership mutation (join/leave/list/add/role/remove, F31-F37) ────


class JoinOutcome(Enum):
    """Result of `join_public_channel`."""

    JOINED = auto()
    ALREADY_MEMBER = auto()
    PRIVATE = auto()
    NOT_FOUND = auto()


@dataclass(frozen=True, slots=True)
class JoinResult:
    outcome: JoinOutcome
    membership: ChannelMember | None
    channel: Channel | None = None
    member_count: int | None = None


async def join_public_channel(db: AsyncSession, *, channel_id: UUID, user_id: UUID) -> JoinResult:
    """Join a public channel directly as `member` (F31), idempotently.

    Order of checks: no such channel -> `NOT_FOUND` (uniform with a truly
    missing channel, mirroring `get_channel_view`); already a member ->
    `ALREADY_MEMBER` (idempotent, checked *before* the private check so an
    existing membership of a channel that has since been marked private —
    not currently possible, `is_private` is immutable, but kept ordered
    defensively — still round-trips as a no-op instead of a spurious
    `403`); private and not yet a member -> `PRIVATE` (F32, direct join
    not allowed). A concurrent duplicate-join race is caught via
    `IntegrityError` on the composite PK and resolved by re-reading the
    now-existing row, so this never raises on a legitimate double-submit.

    On the actual `JOINED` outcome, `channel` and `member_count` are
    populated here — *before* the caller commits — so the T49 post-commit
    publish path (`app.api.channels.join_channel_route`) never needs to
    re-query the database after `db.commit()` has returned. That keeps a
    Redis outage the *only* way to lose the `channel.member_added` event;
    a transient DB error can no longer turn an already-durable join into a
    dropped event by failing on a post-commit re-fetch (`count_channel_members`
    is safe to call pre-commit, in the same transaction, since the flush
    below already made the new membership row visible to it).
    """

    channel = await db.get(Channel, channel_id)
    if channel is None:
        return JoinResult(JoinOutcome.NOT_FOUND, None)

    existing = await get_membership(db, channel_id=channel_id, user_id=user_id)
    if existing is not None:
        return JoinResult(JoinOutcome.ALREADY_MEMBER, existing, channel=channel)

    if channel.is_private:
        return JoinResult(JoinOutcome.PRIVATE, None, channel=channel)

    membership = ChannelMember(
        channel_id=channel_id, user_id=user_id, role=ChannelMemberRole.MEMBER
    )
    db.add(membership)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        existing = await get_membership(db, channel_id=channel_id, user_id=user_id)
        if existing is not None:
            return JoinResult(JoinOutcome.ALREADY_MEMBER, existing, channel=channel)
        raise
    member_count = await count_channel_members(db, channel_id)
    return JoinResult(JoinOutcome.JOINED, membership, channel=channel, member_count=member_count)


class LeaveOutcome(Enum):
    """Result of `leave_channel`."""

    LEFT = auto()
    NOT_MEMBER = auto()


async def leave_channel(db: AsyncSession, *, channel_id: UUID, user_id: UUID) -> LeaveOutcome:
    """Leave a channel the caller belongs to, idempotently (F35/F36/F37).

    A missing channel and "not currently a member" collapse to the same
    `NOT_MEMBER` outcome — per the api-reviewer's idempotency ruling, the
    route maps this to a no-op `204` (not `404`): leave is idempotent, and
    treating an absent channel identically keeps the endpoint
    non-enumerating. If the departing member is the channel's sole
    admin, `run_sole_admin_succession` runs (scoped to just this
    `channel_id`) **before** the membership row is removed, in the same
    transaction — promoting the earliest-`joined_at` remaining member
    (F36) or leaving the channel with zero admins if none remain (F37).
    Never raises `409` — per the frozen contract, leaving is always
    allowed regardless of the resulting admin count.
    """

    channel = await db.get(Channel, channel_id)
    if channel is None:
        return LeaveOutcome.NOT_MEMBER

    membership = await get_membership(db, channel_id=channel_id, user_id=user_id)
    if membership is None:
        return LeaveOutcome.NOT_MEMBER

    if membership.role == ChannelMemberRole.ADMIN:
        await run_sole_admin_succession(db, departing_user_id=user_id, channel_id=channel_id)

    await db.delete(membership)
    await db.flush()
    return LeaveOutcome.LEFT


@dataclass(frozen=True, slots=True)
class MemberRow:
    """One row of a member-list page: the user plus their per-channel membership."""

    user: User
    membership: ChannelMember


@dataclass(frozen=True, slots=True)
class MembersPage:
    """The `{items, total}` result of a channel member-list query."""

    rows: list[MemberRow]
    total: int


async def list_channel_members(
    db: AsyncSession, *, channel_id: UUID, limit: int, offset: int
) -> MembersPage:
    """Offset-paginated list of a channel's members and their roles.

    Ordered by `joined_at, user_id` for stable pagination (mirrors
    `list_public_channels`'s `created_at, id` tie-break). `total` is a
    matching `COUNT(*)` over the same channel, not merely `len(rows)`.
    Caller (the route) is responsible for the channel-existence and
    caller-is-a-member checks — this function assumes both already hold.
    """

    total = await count_channel_members(db, channel_id)

    rows_result = await db.execute(
        select(User, ChannelMember)
        .join(ChannelMember, ChannelMember.user_id == User.id)
        .where(ChannelMember.channel_id == channel_id)
        .order_by(ChannelMember.joined_at.asc(), ChannelMember.user_id.asc())
        .offset(offset)
        .limit(limit)
    )
    rows = [MemberRow(user=user, membership=membership) for user, membership in rows_result.all()]
    return MembersPage(rows=rows, total=total)


class AddMemberOutcome(Enum):
    """Result of `add_channel_member`."""

    ADDED = auto()
    ALREADY_MEMBER = auto()
    CHANNEL_NOT_FOUND = auto()
    TARGET_USER_NOT_FOUND = auto()
    CALLER_NOT_ADMIN = auto()
    ZERO_ADMIN = auto()


@dataclass(frozen=True, slots=True)
class AddMemberResult:
    outcome: AddMemberOutcome
    membership: ChannelMember | None
    channel: Channel | None = None
    member_count: int | None = None


async def add_channel_member(
    db: AsyncSession,
    *,
    channel_id: UUID,
    caller_id: UUID,
    target_user_id: UUID,
    role: ChannelMemberRole,
) -> AddMemberResult:
    """A channel admin adds `target_user_id` to the channel (F32/F33), idempotently.

    Order of checks: no such channel -> `CHANNEL_NOT_FOUND`; the channel
    currently has zero admins -> `ZERO_ADMIN` (F37); caller is not
    currently an admin of *this* channel (read from the same `FOR
    UPDATE`-locked admin set) -> `CALLER_NOT_ADMIN`. The caller's own
    authorization (`ZERO_ADMIN`/`CALLER_NOT_ADMIN`) is deliberately
    resolved *before* the target-user existence lookup — a non-admin
    caller must get an identical `403`/`409` regardless of whether
    `target_user_id` exists, so this endpoint never leaks target-user
    existence to a caller who isn't authorized to mutate membership in
    the first place. Only once the caller is confirmed to be an admin do
    we check: no such user (globally, not just "not a member") ->
    `TARGET_USER_NOT_FOUND`; already a member -> `ALREADY_MEMBER` (no
    duplicate row, idempotent); otherwise inserts the new membership at
    `role`.

    On the actual `ADDED` outcome, `channel` and `member_count` are
    populated here — *before* the caller commits — for the same reason as
    `join_public_channel`: the T49 post-commit publish path
    (`app.api.channels.add_channel_member_route`) must not re-query the
    database after `db.commit()` has returned, so that a Redis outage
    remains the only way to lose the `channel.member_added` event.
    """

    channel = await db.get(Channel, channel_id)
    if channel is None:
        return AddMemberResult(AddMemberOutcome.CHANNEL_NOT_FOUND, None)

    admin_ids = await _lock_channel_admin_ids(db, channel_id)
    if not admin_ids:
        return AddMemberResult(AddMemberOutcome.ZERO_ADMIN, None)
    if caller_id not in admin_ids:
        return AddMemberResult(AddMemberOutcome.CALLER_NOT_ADMIN, None)

    target_user = await db.get(User, target_user_id)
    if target_user is None:
        return AddMemberResult(AddMemberOutcome.TARGET_USER_NOT_FOUND, None)

    existing = await get_membership(db, channel_id=channel_id, user_id=target_user_id)
    if existing is not None:
        return AddMemberResult(AddMemberOutcome.ALREADY_MEMBER, existing, channel=channel)

    membership = ChannelMember(channel_id=channel_id, user_id=target_user_id, role=role)
    db.add(membership)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        existing = await get_membership(db, channel_id=channel_id, user_id=target_user_id)
        if existing is not None:
            return AddMemberResult(AddMemberOutcome.ALREADY_MEMBER, existing, channel=channel)
        raise
    member_count = await count_channel_members(db, channel_id)
    return AddMemberResult(
        AddMemberOutcome.ADDED, membership, channel=channel, member_count=member_count
    )


class ChangeRoleOutcome(Enum):
    """Result of `change_member_role`."""

    UPDATED = auto()
    NO_OP = auto()
    CHANNEL_NOT_FOUND = auto()
    TARGET_NOT_MEMBER = auto()
    CALLER_NOT_ADMIN = auto()
    ZERO_ADMIN = auto()


@dataclass(frozen=True, slots=True)
class ChangeRoleResult:
    outcome: ChangeRoleOutcome
    membership: ChannelMember | None


async def change_member_role(
    db: AsyncSession,
    *,
    channel_id: UUID,
    caller_id: UUID,
    target_user_id: UUID,
    role: ChannelMemberRole,
) -> ChangeRoleResult:
    """A channel admin changes `target_user_id`'s per-channel role (F33), idempotently.

    `TARGET_NOT_MEMBER` covers both "no such user" and "user exists but
    isn't currently a member of this channel" — the contract's PATCH
    table has no idempotent not-a-member outcome (unlike `leave`/`DELETE
    /members`), so both collapse to the same `404`. Setting the role
    that's already set is `NO_OP` (still returns the current membership,
    `200`) rather than a no-op mutation that still flushes. Deliberately
    does **not** run sole-admin succession even when this demotes a
    channel's only admin to `member` — the frozen contract scopes
    succession to `leave`/`DELETE /members/{user_id}` only; a role-change
    self-demotion legitimately produces the F37 zero-admin terminal state
    without triggering succession, exactly as specced.
    """

    channel = await db.get(Channel, channel_id)
    if channel is None:
        return ChangeRoleResult(ChangeRoleOutcome.CHANNEL_NOT_FOUND, None)

    admin_ids = await _lock_channel_admin_ids(db, channel_id)
    if not admin_ids:
        return ChangeRoleResult(ChangeRoleOutcome.ZERO_ADMIN, None)
    if caller_id not in admin_ids:
        return ChangeRoleResult(ChangeRoleOutcome.CALLER_NOT_ADMIN, None)

    membership = await get_membership(db, channel_id=channel_id, user_id=target_user_id)
    if membership is None:
        return ChangeRoleResult(ChangeRoleOutcome.TARGET_NOT_MEMBER, None)

    if membership.role == role:
        return ChangeRoleResult(ChangeRoleOutcome.NO_OP, membership)

    membership.role = role
    await db.flush()
    return ChangeRoleResult(ChangeRoleOutcome.UPDATED, membership)


class RemoveMemberOutcome(Enum):
    """Result of `remove_channel_member`."""

    REMOVED = auto()
    NOT_MEMBER = auto()
    CHANNEL_NOT_FOUND = auto()
    TARGET_USER_NOT_FOUND = auto()
    CALLER_NOT_ADMIN = auto()
    ZERO_ADMIN = auto()


async def remove_channel_member(
    db: AsyncSession,
    *,
    channel_id: UUID,
    caller_id: UUID,
    target_user_id: UUID,
) -> RemoveMemberOutcome:
    """A channel admin removes `target_user_id` from the channel (F33), idempotently.

    The caller's own authorization (`ZERO_ADMIN`/`CALLER_NOT_ADMIN`) is
    deliberately resolved *before* the target-user existence lookup — a
    non-admin caller must get an identical `403`/`409` regardless of
    whether `target_user_id` exists, so this endpoint never leaks
    target-user existence to a caller who isn't authorized to mutate
    membership in the first place. Only once the caller is confirmed to
    be an admin do we check: `TARGET_USER_NOT_FOUND` (no such user at
    all) -> `404`; `NOT_MEMBER` (target user exists but isn't currently a
    member of this channel) is idempotent -> `204`, matching the
    contract's distinction between the DELETE table's idempotency clause
    and its `404` row. If the target is the channel's sole admin,
    `run_sole_admin_succession` runs (scoped to `channel_id`) before the
    row is removed (F36); if no successor exists, the channel persists
    with zero admins (F37).
    """

    channel = await db.get(Channel, channel_id)
    if channel is None:
        return RemoveMemberOutcome.CHANNEL_NOT_FOUND

    admin_ids = await _lock_channel_admin_ids(db, channel_id)
    if not admin_ids:
        return RemoveMemberOutcome.ZERO_ADMIN
    if caller_id not in admin_ids:
        return RemoveMemberOutcome.CALLER_NOT_ADMIN

    target_user = await db.get(User, target_user_id)
    if target_user is None:
        return RemoveMemberOutcome.TARGET_USER_NOT_FOUND

    membership = await get_membership(db, channel_id=channel_id, user_id=target_user_id)
    if membership is None:
        return RemoveMemberOutcome.NOT_MEMBER

    if membership.role == ChannelMemberRole.ADMIN:
        await run_sole_admin_succession(db, departing_user_id=target_user_id, channel_id=channel_id)

    await db.delete(membership)
    await db.flush()
    return RemoveMemberOutcome.REMOVED
