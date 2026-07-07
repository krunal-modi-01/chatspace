"""`invites` ORM model (T13 — invite service, F1, R45).

Maps the `invites` table exactly as authored in
`alembic/versions/0001_initial_schema.py` / the frozen database design doc
(invites table lines 75-84, 201-211, 404-416). No schema change: this is a
read/write mapping over an already-shipped table.

`token_hash` is the **only** persisted form of the single-use invite
token — the raw value is minted and returned once by
`app.services.invites.create_invite`/`rotate_invite_token` and never
stored, logged, or re-derivable from this column (see
`app.core.token_hash.hash_invite_token`).

There is deliberately no `expired` member of `InviteStatus` — expiry is
derived at read time from `expires_at` (frozen database design F7), never
stored as a status transition.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Text, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# All timestamps on `invites` are `timestamptz` (UTC) per the frozen
# database design — mirrors `app.models.session`/`PasswordResetToken`'s
# same convention.
_TIMESTAMPTZ = DateTime(timezone=True)


class InviteStatus(StrEnum):
    """Mirrors the Postgres `invite_status` enum (`pending|accepted|revoked`)."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"


# `create_type=False`: the `invite_status` enum type is already created by
# `alembic/versions/0001_initial_schema.py` — this mapping must never
# attempt to (re)create or drop it.
_INVITE_STATUS_ENUM = SAEnum(
    InviteStatus,
    name="invite_status",
    native_enum=True,
    create_type=False,
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)


class Invite(Base):
    """Maps the `invites` table (single-use System Admin invite, T13).

    `created_by` is the issuing System Admin (`users.id`, `ON DELETE
    RESTRICT` — an issuer's account can never be deleted out from under an
    audit trail). `status` transitions `pending -> accepted` (via
    registration redemption, T14) or `pending -> revoked` (via `DELETE
    /v1/invites/{id}`); there is no transition back to `pending`.
    """

    __tablename__ = "invites"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    # No `unique=True` here for the same reason as `Session.refresh_token_hash`
    # / `PasswordResetToken.token_hash`: uniqueness is already enforced by the
    # shipped `uq_invites_token_hash` unique *index*, not a table-level unique
    # *constraint* SQLAlchemy would infer.
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[InviteStatus] = mapped_column(
        _INVITE_STATUS_ENUM, nullable=False, server_default=text("'pending'")
    )
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(_TIMESTAMPTZ, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(_TIMESTAMPTZ, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        _TIMESTAMPTZ, nullable=False, server_default=text("now()")
    )
