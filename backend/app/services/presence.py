"""Redis ref-counted presence + durable `last_seen` (T25, F49-F50).

Implements the frozen contract's presence lifecycle (API contract lines
627-628, functional spec F49/F50):

- **Ref-count, not a boolean.** A user is `online` while >= 1 live
  `/v1/ws` connection exists for them, across tabs *and* app instances
  (F49). `app.core.redis_keys.presence_connection_count_key` is a single
  shared Redis counter per user — `handle_connect` increments it,
  `handle_disconnect` decrements it — so it is correct regardless of
  which of the 1-2 stateless app instances (CLAUDE.md) any particular
  tab happens to be connected to.
- **Heartbeat TTL, not an unbounded counter.** The counter key carries a
  TTL (`settings.presence_ttl_seconds`) refreshed on every connect and
  client `ping` (`handle_heartbeat`). `app.ws.router` already reaps a
  connection whose heartbeats stop within `ws_heartbeat_timeout_seconds`
  (close code 4408) and always runs `handle_disconnect` in its `finally`
  block on the way out — the ordinary path for "ungraceful disconnect
  (missed heartbeats) expires ... and flips presence to offline"
  (contract line 628). The Redis-side TTL here is the backstop for the
  one failure mode that ordinary path cannot cover: the *entire app
  instance* crashing before that `finally` block ever runs. If nothing
  renews the TTL, the key expires on its own and the stale ref-count
  entry disappears without any other instance needing to notice or
  intervene.
- **Never falsely online after a Redis restart (F49/F50's explicit
  correctness bar).** The ref-count lives *only* in Redis, with no
  durable mirror — a full Redis restart wipes the counter key
  unconditionally, which reads as "offline" (a missing key is always
  treated as count 0), never as a stale "online". This is a direct
  consequence of keeping presence Redis-only per the frozen database
  design ("ephemeral state is NOT in Postgres... there is deliberately
  no presence table") — there is no durable value anywhere that could be
  misread as "still online".
- **Durable `last_seen` only on the last disconnect.** `handle_disconnect`
  persists `users.last_seen = now()` (UTC) exactly once ref-count
  reaches zero — never on every disconnect, and never for a Redis-outage
  guess that is likely wrong. See `handle_disconnect`'s docstring for the
  fail-open behavior when Redis itself is unreachable.
- **Known residual trade-off: a Redis restart with multiple genuinely-live
  tabs can still under-count (never over-count) between the restart and
  the next heartbeat.** The ref-count key carries no durable mirror by
  design (see above), so a restart always wipes it to "missing" (read as
  0 connections) even when N tabs are still actually connected.
  `handle_heartbeat` self-heals a *missing* key by re-incrementing it
  (see `_HEARTBEAT_RENEW_SCRIPT`) the next time each surviving
  connection's heartbeat fires, so the counter climbs back toward the
  true live count as each tab's heartbeat lands — but only the first
  heartbeat to observe the key missing recreates it (at 1); a second
  tab's heartbeat arriving after that recreation sees an already-present
  key and only renews its TTL, without adding its own contribution. This
  means the counter can under-count (and a tab disconnecting before every
  surviving tab has independently self-healed can trigger a spurious
  early "offline" + `last_seen` write for a still-online user) rather
  than converge on the exact true count. This is the accepted trade-off:
  it only ever fails toward *undercounting/offline*, never toward the
  disallowed "stale online after a restart" direction the ticket
  requires, so it does not violate F49/F50's correctness bar. Fully
  eliminating the under-count would require per-connection server-side
  bookkeeping (e.g. each `ConnectionState` tracking whether *it
  specifically* has re-asserted itself since the last restart) — a
  larger design change flagged here rather than invented ad hoc; revisit
  as a follow-up/ADR if false-offline flicker after a Redis restart is
  observed in practice.

## Fan-out target — flagged for api-reviewer

`handle_connect`/`handle_disconnect` publish the built `presence` event
(`build_presence_event`) to a dedicated `presence:{user_id}` Redis topic
(`app.core.redis_keys.presence_topic`), and `app.ws.fanout.PubSubRelay`
subscribes to `presence:*` alongside `chan:*`/`dm:*` so this rides the
same cross-instance relay mechanism `message.*` events use (F53,
ADR-0004's "presence ... published ... to a Redis channel").

What the frozen contract does **not** specify is *who* should be
subscribed to a given `presence:{user_id}` topic — the client frame set
(`join`/`leave`/`typing`/`ping`) has no "watch this user's presence"
frame, only `join` for a `channel`/`dm` conversation. This module
therefore builds and publishes a contract-shaped `presence` event on
every online/offline transition (the concretely-specified, testable part
of T25), but does not itself decide which live connections should be
auto-subscribed to receive it (e.g. every member of a channel the user
belongs to, or every past DM peer) — inventing that fan-out policy here
would risk contract drift beyond what T25 was scoped to resolve. Left as
an explicit open question for the api-reviewer/a follow-up task, exactly
like `app.services.message_events`' `media: []` gap for T29.

The published event's `conversation` field is `None`: presence is a
user-scoped event, not a conversation-scoped one like `typing`/
`message.*`, and the frozen contract's worked envelope example is only
shown for `message.created`. Flagged alongside the fan-out-target
question above.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_fail_modes import redis_fail_open
from app.core.redis_keys import presence_connection_count_key, presence_topic
from app.models.user import User

logger = logging.getLogger(__name__)

_EVENT_TYPE = "presence"
_STATE_ONLINE = "online"
_STATE_OFFLINE = "offline"

# Atomically increment-and-set-TTL in a single Redis round trip. Two
# separate calls (`INCR` then `EXPIRE`) would leave a window where, if the
# connection drops between them, the key is left incremented with *no*
# TTL — a permanently un-expiring counter that defeats the TTL backstop
# this whole module relies on for the instance-crash case (code review
# finding 2).
_INCREMENT_AND_EXPIRE_SCRIPT = """
local n = redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], ARGV[1])
return n
"""

# Renew the TTL on a live heartbeat, self-healing a *missing* key (e.g.
# after a Redis restart wiped it while this connection was still live) by
# re-incrementing rather than leaving it permanently gone. `EXISTS` +
# conditional `INCR` + `EXPIRE` all happen atomically in one round trip so
# a connection drop mid-call can never leave a freshly-recreated key
# without a TTL either. See the module docstring's "known residual
# trade-off" note: this heals the *first* heartbeat to observe a missing
# key, not every surviving tab's contribution simultaneously.
_HEARTBEAT_RENEW_SCRIPT = """
local existed = redis.call('EXISTS', KEYS[1])
if existed == 0 then
  redis.call('INCR', KEYS[1])
end
redis.call('EXPIRE', KEYS[1], ARGV[1])
return existed
"""

# Atomically decrement-and-floor-at-zero the ref-count key, deleting it
# once (or if already) at zero rather than ever writing/leaving a
# negative or lingering-zero value. `KEEPTTL` preserves whatever TTL
# `handle_connect`/`handle_heartbeat` most recently set — a decrement
# must never reset the expiry clock on its own. A missing key (already
# expired via TTL, or a duplicate/late disconnect call racing a prior one
# down to zero) is treated as already at 0, never decremented negative.
_DECREMENT_AND_FLOOR_SCRIPT = """
local raw = redis.call('GET', KEYS[1])
if not raw then
  return 0
end
local n = tonumber(raw) - 1
if n <= 0 then
  redis.call('DEL', KEYS[1])
  return 0
else
  redis.call('SET', KEYS[1], n, 'KEEPTTL')
  return n
end
"""


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def build_presence_event(
    *, user_id: UUID, state: str, last_seen: datetime | None
) -> dict[str, Any]:
    """The frozen `presence` envelope (contract line 672).

    `data` = `{user_id, state, last_seen}` exactly per the contract;
    `conversation` is `None` — see the module docstring's flagged
    api-reviewer question on presence's (non-)conversation scoping.
    """

    return {
        "type": _EVENT_TYPE,
        "conversation": None,
        "data": {
            "user_id": str(user_id),
            "state": state,
            "last_seen": _iso(last_seen),
        },
    }


async def _publish(redis: Redis, event: dict[str, Any], *, user_id: UUID) -> None:
    """Publish `event` to `presence:{user_id}`, failing open on Redis error.

    Mirrors `app.services.message_events.publish_message_event`: never
    raises (presence is not a security control — see
    `app.core.redis_fail_modes` module docstring), and never logs the
    serialized payload itself (it carries no secrets, but stays
    consistent with the rest of the codebase's log-hygiene posture).
    """

    payload = json.dumps(event)
    topic = presence_topic(user_id)

    async def _do_publish() -> None:
        await redis.publish(topic, payload)

    await redis_fail_open(
        f"presence.publish.{event.get('type', 'unknown')}", _do_publish, default=None
    )


async def is_online(redis: Redis, user_id: UUID) -> bool:
    """Whether `user_id` currently has >= 1 live tracked connection.

    Fails open to `False` ("unknown/offline") on a Redis error — per
    CLAUDE.md/spec: "no user falsely shows online" is the correctness bar
    that matters, not availability of this specific read.
    """

    async def _do() -> bool:
        raw = await redis.get(presence_connection_count_key(user_id))
        return raw is not None and int(raw) > 0

    return await redis_fail_open("presence.is_online", _do, default=False)


async def handle_connect(redis: Redis, *, user_id: UUID, ttl_seconds: int) -> None:
    """Ref-count a newly-registered live connection for `user_id`.

    Increments the shared counter and (re)sets its TTL. Only the
    connection that takes the count from 0 -> 1 is an actual
    offline->online transition — every other concurrent tab/instance
    connecting for the same user increments the count without emitting a
    duplicate `online` event (F49: "ref-counted across tabs/instances").

    Never raises: a Redis error here fails open (the connection itself
    must never be refused or dropped over a presence-bookkeeping
    failure) and simply does not observe/emit an online transition.

    The increment and TTL-set happen atomically in one Redis round trip
    (`_INCREMENT_AND_EXPIRE_SCRIPT`) — see code review finding 2: two
    separate calls could leave the counter incremented with no TTL if the
    connection dropped in between, defeating the crash backstop.
    """

    async def _do() -> int:
        script = redis.register_script(_INCREMENT_AND_EXPIRE_SCRIPT)
        result = await script(keys=[presence_connection_count_key(user_id)], args=[ttl_seconds])
        return int(result)

    count = await redis_fail_open("presence.connect", _do, default=0)
    if count == 1:
        event = build_presence_event(user_id=user_id, state=_STATE_ONLINE, last_seen=None)
        await _publish(redis, event, user_id=user_id)
        logger.info("presence: user online", extra={"user_id": str(user_id)})


async def handle_heartbeat(redis: Redis, *, user_id: UUID, ttl_seconds: int) -> None:
    """Renew the ref-count key's TTL on a live client `ping`, self-healing if missing.

    If the key is still present, this is a plain TTL renewal (never
    raises; a Redis error fails open the same as every other presence
    operation). If the key is *missing* — e.g. a Redis restart wiped it
    while this connection was still live — this re-increments it rather
    than leaving a live connection's presence permanently lost, per code
    review finding 3. See the module docstring's "known residual
    trade-off" note: this heals the first surviving heartbeat to notice
    the key is gone, but does not by itself restore every other
    concurrently-live tab's individual contribution to the count.
    """

    async def _do() -> None:
        script = redis.register_script(_HEARTBEAT_RENEW_SCRIPT)
        await script(keys=[presence_connection_count_key(user_id)], args=[ttl_seconds])

    await redis_fail_open("presence.heartbeat", _do, default=None)


async def handle_disconnect(redis: Redis, db: AsyncSession, *, user_id: UUID) -> None:
    """Decrement the ref count; on the last disconnect, persist `last_seen` + emit offline.

    Only the disconnect that takes the count to 0 is the user's *last*
    connection closing (F50) — persists `users.last_seen = now()` (UTC)
    and publishes the `offline` presence event. Every other concurrent
    tab/instance disconnecting while >= 1 connection remains for this
    user does neither.

    Redis-outage behavior on the decrement itself deliberately fails open
    toward *this* disconnect being treated as the last one (count = 0)
    rather than assuming the opposite: per CLAUDE.md/spec, presence must
    never falsely show a user online, and eagerly persisting `last_seen`
    an extra time when Redis is unreachable is harmless (it only updates
    a timestamp), unlike the reverse mistake of skipping the write and
    leaving a user's true last-connection moment unrecorded.

    Caller owns `db`'s transaction boundary the same way every other
    short-lived WS-operation session does (`app.ws.router._db_session`);
    this function commits its own single-row update before returning.
    """

    async def _do() -> int:
        script = redis.register_script(_DECREMENT_AND_FLOOR_SCRIPT)
        result = await script(keys=[presence_connection_count_key(user_id)])
        return int(result)

    count = await redis_fail_open("presence.disconnect", _do, default=0)
    if count > 0:
        return

    last_seen = datetime.now(UTC)
    await db.execute(update(User).where(User.id == user_id).values(last_seen=last_seen))
    await db.commit()

    event = build_presence_event(user_id=user_id, state=_STATE_OFFLINE, last_seen=last_seen)
    await _publish(redis, event, user_id=user_id)
    logger.info("presence: user offline; last_seen persisted", extra={"user_id": str(user_id)})
