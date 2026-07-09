"""`attachments` ORM model (T21 — required for message-send media binding, F39).

Maps the `attachments` table exactly as authored in
`alembic/versions/0001_initial_schema.py` / the frozen database design doc.
No schema change: this is a read/write mapping over an already-shipped
table. Added alongside `app.models.message` because `POST
/v1/channels/{channel_id}/messages`'s `media_ids` validation ("belongs to
sender and is unbound", F39) and the response `media[]` array both need to
query/mutate this table — a future media-upload task owns *creating*
orphaned attachment rows, but this mapping is the shared primitive both
tasks read/write through.

`id` is app-generated UUIDv7 (`app.core.ids.generate_id`), matching every
other table's id convention — not modeled here since T21 never inserts an
`attachments` row itself, only reads/binds existing ones.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Text, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AttachmentKind(StrEnum):
    """Mirrors the Postgres `attachment_kind` enum (`image|file|video`)."""

    IMAGE = "image"
    FILE = "file"
    VIDEO = "video"


# `create_type=False`: the `attachment_kind` enum type is already created by
# `alembic/versions/0001_initial_schema.py` — this mapping must never
# attempt to (re)create or drop it. Mirrors
# `app.models.channel_member._CHANNEL_MEMBER_ROLE_ENUM`'s exact same
# pattern.
_ATTACHMENT_KIND_ENUM = SAEnum(
    AttachmentKind,
    name="attachment_kind",
    native_enum=True,
    create_type=False,
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)


class Attachment(Base):
    """Maps the `attachments` table (see database design doc, T21 slice).

    `message_id` is nullable — an attachment is uploaded (orphaned) before
    it is bound to a message on send (two-phase upload-then-send, F39).
    "Unbound" means `message_id IS NULL`; binding sets it to the sending
    message's id inside the same transaction as the message INSERT (see
    `app.services.messages.send_channel_message`).
    """

    __tablename__ = "attachments"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=True
    )
    uploader_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[AttachmentKind] = mapped_column(_ATTACHMENT_KIND_ENUM, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
