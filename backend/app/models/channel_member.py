"""`channel_members` ORM model (T18 — channel create/get/public browse, R4/R51).

Maps the `channel_members` table exactly as authored in
`alembic/versions/0001_initial_schema.py` / the frozen database design doc.
No schema change: this is a read/write mapping over an already-shipped
table. `channel_members` has a **composite primary key** (`channel_id`,
`user_id`) and no surrogate `id` column — `db.get(ChannelMember, (channel_id,
user_id))` is the O(log n) membership-check point lookup this task relies
on for both `GET /v1/channels/{id}` visibility and, later, the "already a
member" exclusion in `GET /v1/channels/public`.

There is deliberately no `succession`/admin-count business logic mapped
here — R51 (earliest admin is the succession heir) is read via
`ix_channel_members_admin_succession` by a later task (membership
mutation, T19), out of scope for T18.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ChannelMemberRole(StrEnum):
    """Mirrors the Postgres `channel_member_role` enum (`member|admin`)."""

    MEMBER = "member"
    ADMIN = "admin"


# `create_type=False`: the `channel_member_role` enum type is already
# created by `alembic/versions/0001_initial_schema.py` — this mapping must
# never attempt to (re)create or drop it. Mirrors
# `app.models.invite._INVITE_STATUS_ENUM`'s exact same pattern.
_CHANNEL_MEMBER_ROLE_ENUM = SAEnum(
    ChannelMemberRole,
    name="channel_member_role",
    native_enum=True,
    create_type=False,
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)


class ChannelMember(Base):
    """Maps the `channel_members` table (composite PK, no surrogate id).

    `role` defaults to `member` at the DB layer; the creator of a channel
    (T18's `POST /v1/channels`) is inserted explicitly with `role=admin`
    in the same transaction as the `channels` INSERT (R4 — creator
    recorded as the first admin).
    """

    __tablename__ = "channel_members"

    channel_id: Mapped[UUID] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    role: Mapped[ChannelMemberRole] = mapped_column(
        _CHANNEL_MEMBER_ROLE_ENUM, nullable=False, server_default=text("'member'")
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
