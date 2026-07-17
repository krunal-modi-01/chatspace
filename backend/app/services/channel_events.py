"""Redis pub/sub fan-out for `channel.member_added`/`channel.member_removed` (T49, ADR-0012).

Builds the frozen server -> client WS envelope (API contract lines
721-722) and publishes it to the affected user's own per-user topic
(`app.core.redis_keys.user_topic`, ADR-0012) so every app instance's
per-process subscriber (`app.ws.fanout.PubSubRelay`, `user:*` pattern)
can relay it to whichever of that user's *own* connections are locally
subscribed — delivery is per-user, never per-channel: no other user's
connection is ever a subscriber of `user:{user_id}`.

**Persist-then-publish**: every `publish_member_*` call here must only
ever be invoked by `app.api.channels` *after* its own `db.commit()` has
returned, and only for the branch that actually mutated a
`channel_members` row (a real insert for `member_added`, a real delete
for `member_removed`) — never for an idempotent no-op (already a member,
already not a member), which committed nothing new to publish about.

**No replay**: unlike `message.*` (which a reconnecting client recovers
via history-since-last-id catch-up, F55), membership events have no
durable replay log — a client that missed one while disconnected must
refetch `GET /v1/channels` on reconnect (contract line 725, Flow L).
This module has no opinion on that; it only builds and publishes the
live event.

**Fail-open on publish**: per ADR-0004, a failed publish only loses a
live UI update — the membership row is already durably committed, so
the mutation itself must never fail because Redis is down.
`publish_channel_event` therefore never raises; a Redis error is logged
(no PII) and swallowed via `app.core.redis_fail_modes.redis_fail_open`.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from redis.asyncio import Redis

from app.core.redis_fail_modes import redis_fail_open
from app.core.redis_keys import user_topic
from app.models.channel import Channel
from app.models.channel_member import ChannelMemberRole

logger = logging.getLogger(__name__)

_MEMBER_ADDED = "channel.member_added"
_MEMBER_REMOVED = "channel.member_removed"


def _iso(value: datetime) -> str:
    return value.isoformat()


def _channel_conversation(channel_id: UUID) -> dict[str, Any]:
    """The envelope's `conversation` discriminator — "the channel" (contract lines 721-722)."""

    return {"kind": "channel", "channel_id": str(channel_id)}


def _channel_summary(channel: Channel, *, member_count: int) -> dict[str, Any]:
    """The `data.channel` full summary carried by `channel.member_added` only.

    Exactly the six frozen fields (contract line 721) — deliberately no
    `my_role`, unlike a `GET /v1/channels` row.
    """

    return {
        "id": str(channel.id),
        "name": channel.name,
        "is_private": channel.is_private,
        "created_by": str(channel.created_by),
        "created_at": _iso(channel.created_at),
        "member_count": member_count,
    }


def build_member_added_event(
    channel: Channel,
    *,
    user_id: UUID,
    role: ChannelMemberRole,
    joined_at: datetime,
    member_count: int,
) -> dict[str, Any]:
    """The `channel.member_added` envelope (contract line 721)."""

    return {
        "type": _MEMBER_ADDED,
        "conversation": _channel_conversation(channel.id),
        "data": {
            "channel": _channel_summary(channel, member_count=member_count),
            "user_id": str(user_id),
            "role": role.value,
            "joined_at": _iso(joined_at),
        },
    }


def build_member_removed_event(*, channel_id: UUID, user_id: UUID) -> dict[str, Any]:
    """The `channel.member_removed` envelope (contract line 722) — no channel metadata."""

    return {
        "type": _MEMBER_REMOVED,
        "conversation": _channel_conversation(channel_id),
        "data": {
            "channel_id": str(channel_id),
            "user_id": str(user_id),
        },
    }


async def publish_channel_event(redis: Redis, event: dict[str, Any], *, topic: str) -> None:
    """Publish `event` (already-built envelope) to `topic`, failing open on error.

    Never raises. `topic`/event-type are safe to log (no PII); the
    serialized payload itself is never logged.
    """

    payload = json.dumps(event)

    async def _do_publish() -> None:
        await redis.publish(topic, payload)

    await redis_fail_open(
        f"channels.publish.{event.get('type', 'unknown')}", _do_publish, default=None
    )


async def publish_member_added(
    redis: Redis,
    channel: Channel,
    *,
    user_id: UUID,
    role: ChannelMemberRole,
    joined_at: datetime,
    member_count: int,
) -> None:
    """Publish `channel.member_added` to the added user's own `user:{user_id}` topic (F74).

    Delivered only to `user_id`'s own connections — never to any other
    member of `channel`, and never to any connection of any other user.
    """

    event = build_member_added_event(
        channel, user_id=user_id, role=role, joined_at=joined_at, member_count=member_count
    )
    await publish_channel_event(redis, event, topic=user_topic(user_id))


async def publish_member_removed(redis: Redis, *, channel_id: UUID, user_id: UUID) -> None:
    """Publish `channel.member_removed` to the removed user's own `user:{user_id}` topic (F75).

    Delivered only to `user_id`'s own connections — never to any other
    member of `channel_id`, and never to any connection of any other user.
    """

    event = build_member_removed_event(channel_id=channel_id, user_id=user_id)
    await publish_channel_event(redis, event, topic=user_topic(user_id))
