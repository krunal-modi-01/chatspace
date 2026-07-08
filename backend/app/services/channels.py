"""Channel create/get/public-browse business logic (T18, F29-F31).

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

Does **not** implement the HTTP endpoints themselves, request-body
parsing, or the `400`/`422`/`409` status-code mapping — see
`app.api.channels` for that.

`run_sole_admin_succession` implements the F36/F37 (R51) last-admin
succession rule that T19 (membership mutation: join/leave/add/remove/role
endpoints) was scoped to own. At the time this function was added (T44,
System Admin deactivation), **T19 had not yet been implemented** — this
module has no `leave_channel`/`remove_member` yet — so T44's deactivate
flow is the first real caller. This function is written as the single
shared primitive so that when T19 lands its own `POST /leave` and
`DELETE /members/{user_id}` sole-admin paths, it reuses this exact
function rather than re-deriving the same rule a second time. Flagged for
the architect/api-reviewer to confirm alignment once T19 is scheduled.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import generate_id
from app.models.channel import Channel
from app.models.channel_member import ChannelMember, ChannelMemberRole

# Mirrors the shipped `CHECK (name ~ '^[A-Za-z0-9 _-]{1,80}$')` constraint
# (R36) exactly — pre-validated here so a charset/length violation maps to
# the frozen `422` rather than falling through to a raw `IntegrityError`
# (which is reserved for the case-insensitive uniqueness `409`).
CHANNEL_NAME_RE = re.compile(r"^[A-Za-z0-9 _-]{1,80}$")

# Offset-pagination page size (frozen contract: "Page size default and
# maximum are 50").
PUBLIC_CHANNELS_DEFAULT_LIMIT = 50
PUBLIC_CHANNELS_MAX_LIMIT = 50


def is_valid_channel_name(name: str) -> bool:
    """Return whether `name` satisfies the frozen charset/length rule (1-80, R36)."""

    return bool(CHANNEL_NAME_RE.match(name))


async def _count_members(db: AsyncSession, channel_id: UUID) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(ChannelMember)
        .where(ChannelMember.channel_id == channel_id)
    )
    return int(result.scalar_one())


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

    member_count = await _count_members(db, channel_id)
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

    member_count_subquery = (
        select(
            ChannelMember.channel_id.label("channel_id"),
            func.count().label("member_count"),
        )
        .group_by(ChannelMember.channel_id)
        .subquery()
    )
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


async def run_sole_admin_succession(db: AsyncSession, *, departing_user_id: UUID) -> list[UUID]:
    """Promote a successor wherever `departing_user_id` is a channel's *sole* admin (F36/R51).

    For every channel where `departing_user_id` currently holds the
    `admin` role AND is the only admin of that channel, promotes the
    remaining member with the earliest `joined_at` (any role, not just
    `member`) to `admin` — matching F36 exactly ("the longest-standing
    remaining member ... is automatically promoted to admin"). If no
    other member remains, the channel is left with zero admins (F37, a
    valid terminal state) — this function does not itself remove
    `departing_user_id`'s membership row, since callers (deactivation
    today; leave/remove-member once T19 lands) own that decision and its
    timing independently.

    Read via `ix_channel_members_admin_succession` (`(channel_id,
    joined_at) WHERE role='admin'`) for the admin-count check; the
    successor lookup itself scans all roles or a given channel, ordered
    by `joined_at`, which the plain composite PK/`ix_channel_members_user`
    indexes already serve at this scale.

    Returns the ids of every channel where a promotion actually happened,
    so the caller can log a content-free audit line without re-deriving
    which channels changed. Flushes but does not commit — the caller owns
    the transaction boundary (mirrors every other mutator in this module).
    """

    admin_channel_ids_result = await db.execute(
        select(ChannelMember.channel_id).where(
            ChannelMember.user_id == departing_user_id,
            ChannelMember.role == ChannelMemberRole.ADMIN,
        )
    )
    admin_channel_ids = [row[0] for row in admin_channel_ids_result.all()]

    promoted_channel_ids: list[UUID] = []
    for channel_id in admin_channel_ids:
        admin_count_result = await db.execute(
            select(func.count())
            .select_from(ChannelMember)
            .where(
                ChannelMember.channel_id == channel_id,
                ChannelMember.role == ChannelMemberRole.ADMIN,
            )
        )
        if int(admin_count_result.scalar_one()) != 1:
            continue  # not the sole admin — no succession needed

        successor_result = await db.execute(
            select(ChannelMember)
            .where(
                ChannelMember.channel_id == channel_id,
                ChannelMember.user_id != departing_user_id,
            )
            .order_by(ChannelMember.joined_at.asc())
            .limit(1)
        )
        successor = successor_result.scalar_one_or_none()
        if successor is None:
            continue  # F37: no other members — channel persists with zero admins

        successor.role = ChannelMemberRole.ADMIN
        promoted_channel_ids.append(channel_id)

    if promoted_channel_ids:
        await db.flush()

    return promoted_channel_ids
