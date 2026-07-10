"""Pydantic schemas for `/v1/channels/{id}/messages` + `/v1/messages/{id}` (T21)
and `/v1/dms/{user_id}/messages` (T22).

T22 reuses every schema here unchanged: `MessageSendRequest` is the DM
send body too (`content` + `media_ids`), and `MessageObject`/
`MessageHistoryResponse` are already the canonical wire shape for a
`recipient_id`-set (DM) row exactly as much as a `channel_id`-set
(channel) row — no new schema needed for the DM endpoints.

`MessageSendRequest`/`MessageEditRequest` are validated manually via
`app.core.request_body.parse_body` (not typed FastAPI body parameters),
so a missing/wrong-type field maps to the contract's `400` — mirrors
`app.schemas.channels`'s existing convention. Semantic content validation
(non-whitespace, `<= 4000` chars) and media-id ownership/unbound checks
are separate, business-rule `422`s the route/service layer perform after
structural parsing succeeds.

`MessageObject` is the single canonical wire shape shared by the `201`/
`200` create-or-replay response, the `200` edit response, and each entry
of the history page's `items[]` — matches the frozen contract's `message`
object schema exactly (`recipient_id: null` for a channel message).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.attachment import Attachment, AttachmentKind
from app.models.message import Message


class MessageSendRequest(BaseModel):
    """Body of `POST /v1/channels/{channel_id}/messages`.

    `content`'s non-whitespace/length validation is deliberately *not*
    enforced here (only structural presence/type) — the frozen contract
    distinguishes a malformed body (`400`) from an invalid content value
    (`422`), and only the route/service layer can tell the two apart by
    running the semantic check after this structural parse succeeds.
    """

    content: str
    media_ids: list[UUID] = []


class MessageEditRequest(BaseModel):
    """Body of `PATCH /v1/messages/{message_id}`."""

    content: str


class MediaDescriptor(BaseModel):
    """One entry of a `message` object's `media[]` array."""

    media_id: UUID
    kind: str
    filename: str
    size: int

    @classmethod
    def from_attachment(cls, attachment: Attachment) -> MediaDescriptor:
        kind = attachment.kind
        return cls(
            media_id=attachment.id,
            kind=kind.value if isinstance(kind, AttachmentKind) else str(kind),
            filename=attachment.filename,
            size=attachment.byte_size,
        )


class MessageObject(BaseModel):
    """The canonical `message` object (frozen contract's wire shape).

    Exactly one of `channel_id`/`recipient_id` is set per the shipped
    `ck_messages_target_xor` (ADR-0002): `channel_id` set + `recipient_id
    null` for a channel message (T21), `recipient_id` set + `channel_id
    null` for a DM (T22).
    """

    id: UUID
    channel_id: UUID | None
    recipient_id: UUID | None
    sender_id: UUID
    content: str
    media: list[MediaDescriptor]
    created_at: datetime
    edited_at: datetime | None
    deleted_at: datetime | None

    @classmethod
    def from_message(cls, message: Message, *, media: list[Attachment]) -> MessageObject:
        return cls(
            id=message.id,
            channel_id=message.channel_id,
            recipient_id=message.recipient_id,
            sender_id=message.sender_id,
            content=message.content,
            media=[MediaDescriptor.from_attachment(a) for a in media],
            created_at=message.created_at,
            edited_at=message.edited_at,
            deleted_at=message.deleted_at,
        )


class MessageHistoryResponse(BaseModel):
    """`200` envelope of `GET /v1/channels/{channel_id}/messages` — cursor pagination shape."""

    items: list[MessageObject]
    next_cursor: str | None
