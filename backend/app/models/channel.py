"""`channels` ORM model (T18 — channel create/get/public browse, F29-F31).

Maps the `channels` table exactly as authored in
`alembic/versions/0001_initial_schema.py` / the frozen database design doc
(channels table). No schema change: this is a read/write mapping over an
already-shipped table.

`id` is app-generated UUIDv7 (`app.core.ids.generate_id`), never a DB
default (see that module's docstring). Case-insensitive name uniqueness is
enforced by the shipped `uq_channels_name_lower` unique *index* (not a
table-level unique *constraint* SQLAlchemy would infer), so a name
collision surfaces as an `IntegrityError` at flush time, not a mapped
`unique=True` here — mirrors `Invite.token_hash`/`User.email`'s existing
convention.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Channel(Base):
    """Maps the `channels` table (see database design doc, T18 slice).

    `created_by` is the creating user (`users.id`, `ON DELETE RESTRICT` —
    a creator's account can never be deleted out from under a channel they
    own). `is_private` is immutable at this layer (T18 is create/get/
    browse only; membership mutation is T19, out of scope here).
    """

    __tablename__ = "channels"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_private: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
