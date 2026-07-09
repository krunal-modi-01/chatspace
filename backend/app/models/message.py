"""`messages` ORM model (T21 — message send/edit/delete/history, F38-F45).

Maps the `messages` table exactly as authored in
`alembic/versions/0001_initial_schema.py` / the frozen database design doc.
No schema change: this is a read/write mapping over an already-shipped
table (`messages` table only. Model only, no new migration).

`id` is app-generated UUIDv7 (`app.core.ids.generate_id`) — this mapping
deliberately does **not** declare a server default (no
`gen_random_uuid()`), matching the frozen design's explicit prohibition:
"A `gen_random_uuid()` default is explicitly excluded." Callers must
always pass `id=generate_id()` when constructing a `Message`.

`channel_id`/`recipient_id` are XOR per `ck_messages_target_xor` — T21
(channel messages) always sets `channel_id` and leaves `recipient_id`
`None`; DM messages (`recipient_id` set) are a different task's (T22)
concern and out of scope here, though the column is mapped for
completeness since both live in the same table.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Message(Base):
    """Maps the `messages` table (see database design doc, T21 slice).

    `created_at` carries a DB `server_default=now()` as a safety net, but
    T21's service layer relies on SQLAlchemy's post-INSERT `RETURNING` to
    read the authoritative value back on the same round-trip (mirrors
    `app.models.channel.Channel.created_at` / `app.services.channels
    .create_channel`'s identical pattern) rather than setting it
    app-side, since Postgres's clock is the single source of truth for
    ordering (R39).

    Soft delete: `deleted_at` is set (not the row removed) by `DELETE
    /v1/messages/{id}` (F43); `edited_at` is set (id/order unchanged) by
    `PATCH /v1/messages/{id}` (F42/R9). Both start `NULL`.
    """

    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    channel_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("channels.id", ondelete="RESTRICT"), nullable=True
    )
    recipient_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    sender_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
