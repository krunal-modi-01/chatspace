"""Redis pub/sub fan-out for `message.created`/`edited`/`deleted` (T24).

Builds the frozen server -> client WS envelope (API contract lines
651-673) from a persisted `Message` row and publishes it to the
canonical conversation topic (`app.core.redis_keys.channel_topic` /
`dm_topic`, ADR-0004) so every app instance's per-process subscriber
(`app.ws.fanout.PubSubRelay`) can relay it to whichever local
connections have joined that topic (F53) — cross-instance, no session
affinity.

**Persist-then-publish**: every `publish_message_*` call here must only
ever be invoked by `app.services.messages` *after* its own `db.commit()`
has returned — never before, and never for a call that only observed an
existing row (an idempotent replay) rather than creating one, since
that call did not itself commit anything new. This module has no
opinion on *when* to call it; that ordering is enforced by the caller.

**Media (T29)**: the frozen envelope's `data.media[]` array is part of
the contract shape (line 662) and is therefore always present — never
dropped. `build_created_event`/`build_edited_event` (and their
`publish_*` wrappers) take an optional `media: Sequence[Attachment]`
(default `()`, matching T24's original "always an empty array" shape
for any caller that does not pass one) and serialize it to the exact
same `{media_id, kind, filename, size}` element shape as
`app.schemas.messages.MediaDescriptor` — the WS envelope and the REST
`message` object's `media[]` must never drift from each other.
`app.services.messages` passes the message's just-bound (create) /
currently-bound (edit) attachments through; `message.deleted` never
carries `media` at all (unchanged from T24 — the field is omitted
outright, not emptied, per the contract's delete-event shape).

**Fail-open on publish**: per ADR-0004 and the technical spec's Redis
risk register, a failed publish only delays live delivery — the row is
already durably committed, so a client recovers it via reconnect
catch-up (history-since-last-id, F55). `publish_message_event` therefore
never raises; a Redis error is logged (no message content, no PII) and
swallowed via `app.core.redis_fail_modes.redis_fail_open`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

from redis.asyncio import Redis

from app.core.redis_fail_modes import redis_fail_open
from app.core.redis_keys import channel_topic, dm_topic
from app.models.attachment import Attachment, AttachmentKind
from app.models.message import Message

logger = logging.getLogger(__name__)

_CHANNEL_KIND = "channel"
_DM_KIND = "dm"

_MESSAGE_CREATED = "message.created"
_MESSAGE_EDITED = "message.edited"
_MESSAGE_DELETED = "message.deleted"


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _conversation_for(message: Message) -> dict[str, Any]:
    """The envelope's `conversation` discriminator (mirrors `app.ws.frames`'
    `ChannelConversation`/`DMConversation` client-frame shapes).

    For a DM, `user_id` is the message's own persisted `recipient_id` —
    a fixed value on the row itself, not "the other party relative to
    whoever receives this" (a single published payload is relayed
    as-is to both participants' connections on the shared `dm:{a}:{b}`
    topic, so there is no single "self" perspective to encode here; a
    receiving client already knows its own id and can derive which side
    of `data.sender_id`/`data.recipient_id` is "the other person").
    Flagged for api-reviewer confirmation since the frozen contract's
    example envelope only shows the channel variant.
    """

    if message.channel_id is not None:
        return {"kind": _CHANNEL_KIND, "channel_id": str(message.channel_id)}

    assert message.recipient_id is not None, "DM message must have recipient_id set (XOR)"
    return {"kind": _DM_KIND, "user_id": str(message.recipient_id)}


def _topic_for(message: Message) -> str:
    """The canonical pub/sub topic this message's events publish to (ADR-0004)."""

    if message.channel_id is not None:
        return channel_topic(message.channel_id)

    assert message.recipient_id is not None, "DM message must have recipient_id set (XOR)"
    return dm_topic(message.sender_id, message.recipient_id)


def _media_payload(media: Sequence[Attachment]) -> list[dict[str, Any]]:
    """Serialize bound attachments to the frozen WS `media[]` element shape (T29).

    `{media_id, kind, filename, size}` — deliberately the same fields, in
    the same order, as `app.schemas.messages.MediaDescriptor.from_attachment`
    (no `content_type`/`url`; a presigned URL is fetched separately via
    `GET /v1/media/{media_id}/url`, T35). Kept as a plain dict builder
    (not the Pydantic schema) so this module has no import-time
    dependency on `app.schemas`.
    """

    payload: list[dict[str, Any]] = []
    for attachment in media:
        kind = attachment.kind
        payload.append(
            {
                "media_id": str(attachment.id),
                "kind": kind.value if isinstance(kind, AttachmentKind) else str(kind),
                "filename": attachment.filename,
                "size": attachment.byte_size,
            }
        )
    return payload


def _full_data(message: Message, *, media: Sequence[Attachment] = ()) -> dict[str, Any]:
    """The `data` object shared by `message.created`/`message.edited` (contract line 656-666)."""

    return {
        "id": str(message.id),
        "channel_id": str(message.channel_id) if message.channel_id is not None else None,
        "recipient_id": str(message.recipient_id) if message.recipient_id is not None else None,
        "sender_id": str(message.sender_id),
        "content": message.content,
        # Always present per the frozen envelope shape — never dropped.
        # Populated (T29) from the message's bound attachments; empty
        # when the caller passes none (the T24 default, still correct
        # for a message with no media).
        "media": _media_payload(media),
        "created_at": _iso(message.created_at),
        "edited_at": _iso(message.edited_at),
        "deleted_at": _iso(message.deleted_at),
    }


def build_created_event(message: Message, *, media: Sequence[Attachment] = ()) -> dict[str, Any]:
    """The `message.created` envelope (contract lines 651-667)."""

    return {
        "type": _MESSAGE_CREATED,
        "conversation": _conversation_for(message),
        "data": _full_data(message, media=media),
    }


def build_edited_event(message: Message, *, media: Sequence[Attachment] = ()) -> dict[str, Any]:
    """The `message.edited` envelope — same shape as created (contract line 669)."""

    return {
        "type": _MESSAGE_EDITED,
        "conversation": _conversation_for(message),
        "data": _full_data(message, media=media),
    }


def build_deleted_event(message: Message) -> dict[str, Any]:
    """The `message.deleted` envelope: `data` = `{id, conversation, deleted_at}`,
    content omitted (contract line 670).
    """

    conversation = _conversation_for(message)
    return {
        "type": _MESSAGE_DELETED,
        "conversation": conversation,
        "data": {
            "id": str(message.id),
            "conversation": conversation,
            "deleted_at": _iso(message.deleted_at),
        },
    }


async def publish_message_event(redis: Redis, event: dict[str, Any], *, topic: str) -> None:
    """Publish `event` (already-built envelope) to `topic`, failing open on error.

    Never raises. `topic`/event-type are safe to log (no message content
    or PII); the serialized payload itself is never logged.
    """

    payload = json.dumps(event)

    async def _do_publish() -> None:
        await redis.publish(topic, payload)

    await redis_fail_open(
        f"messages.publish.{event.get('type', 'unknown')}", _do_publish, default=None
    )


async def publish_message_created(
    redis: Redis, message: Message, *, media: Sequence[Attachment] = ()
) -> None:
    """Publish `message.created` for a just-committed row (persist-then-publish).

    `media` (T29) is the message's just-bound attachments — pass the same
    list the send call bound in the same transaction so the WS payload
    never lags the REST `message.media[]` response for the same send.
    """

    await publish_message_event(
        redis, build_created_event(message, media=media), topic=_topic_for(message)
    )


async def publish_message_edited(
    redis: Redis, message: Message, *, media: Sequence[Attachment] = ()
) -> None:
    """Publish `message.edited` for a just-committed edit (persist-then-publish).

    `media` (T29) is the message's currently-bound attachments (unchanged
    by an edit, but still part of the envelope's `data` shape).
    """

    await publish_message_event(
        redis, build_edited_event(message, media=media), topic=_topic_for(message)
    )


async def publish_message_deleted(redis: Redis, message: Message) -> None:
    """Publish `message.deleted` for a just-committed soft-delete (persist-then-publish)."""

    await publish_message_event(redis, build_deleted_event(message), topic=_topic_for(message))
