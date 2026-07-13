"""Typing indicator relay — no persistence (T26).

Builds the frozen `typing` server -> client WS envelope (API contract
line 671) from an authorized `typing` client frame and publishes it to
the conversation's canonical pub/sub topic (`app.core.redis_keys.
channel_topic`/`dm_topic`, ADR-0004) so every app instance's
`app.ws.fanout.PubSubRelay` can relay it to local connections — the same
cross-instance fan-out T24 built for `message.*` events, reused verbatim
here rather than re-implemented.

Ephemeral, relay-only, by design (technical spec's ephemeral-state
ruling; database design lines 13/112-113): nothing here is persisted —
no row, no Redis key beyond the transient pub/sub publish itself. The
client owns the whole "stop typing" lifecycle via a **5s client-side
auto-expire** since the last received `typing` frame (F56); there is
deliberately **no** `typing.stop`/explicit-stop frame, and this module
must never grow one without routing that change through the
api-reviewer (it would extend the frozen wire contract).

**Self-exclusion**: unlike `message.*` (delivered to every local
subscriber including the sender's own connection — the sender's own
send already confirms delivery client-side), a `typing` event must
reach *other participants only* (contract: "fans out ... to other
participants of the same channel/DM only") — the typer must never see
their own typing indicator echoed back to any of their own tabs.
`app.ws.fanout.PubSubRelay` implements this by excluding every local
connection belonging to the *typer's* `user_id` (not merely the one
connection that sent the frame) from `ConnectionManager.
broadcast_to_topic` whenever the relayed envelope's `type` is
`"typing"`.

**Fail-open**: exactly like `app.services.message_events.
publish_message_event` — a publish failure here only means a live
typing indicator is missed. Unlike `message.*`, there is no reconnect
catch-up to recover it (there is deliberately no durable history of
typing events), but that only makes the miss cheaper to accept, not a
reason to fail closed: a missed typing indicator is never a security or
data-integrity concern, so failing open (log + swallow) is strictly
correct here, not merely convenient.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from redis.asyncio import Redis

from app.core.redis_fail_modes import redis_fail_open
from app.ws.frames import Conversation

logger = logging.getLogger(__name__)

TYPING_EVENT_TYPE = "typing"


def build_typing_event(*, user_id: UUID, conversation: Conversation) -> dict[str, Any]:
    """The `typing` envelope (contract line 671): `data = {user_id, conversation}`.

    `conversation` is relayed exactly as the client sent it on the
    `typing` frame — a fixed value taken from the originating frame, not
    recomputed relative to whichever connection ends up receiving it.
    This mirrors the same convention
    `app.services.message_events._conversation_for` documents for DM
    envelopes (there is no single "self" perspective to encode server
    side; a receiving client already knows its own id).
    """

    conversation_payload = conversation.model_dump(mode="json")
    return {
        "type": TYPING_EVENT_TYPE,
        "conversation": conversation_payload,
        "data": {"user_id": str(user_id), "conversation": conversation_payload},
    }


async def publish_typing_event(redis: Redis, event: dict[str, Any], *, topic: str) -> None:
    """Publish an already-built `typing` envelope to `topic`, failing open on error.

    Never raises. `topic` and the event type are safe to log; the
    serialized payload is never logged.
    """

    payload = json.dumps(event)

    async def _do_publish() -> None:
        await redis.publish(topic, payload)

    await redis_fail_open("typing.publish", _do_publish, default=None)
