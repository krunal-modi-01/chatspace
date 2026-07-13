"""Per-instance Redis pub/sub subscriber relaying fan-out events to local sockets (T24).

`app.services.message_events` publishes `message.created`/`edited`/
`deleted` envelopes to the canonical `chan:{channel_id}` / `dm:{a}:{b}`
topics (ADR-0004) after each service-layer commit. Something on *every*
app instance must be subscribed to those topics and hand matching
events to `app.ws.connection_manager.ConnectionManager` so a message
sent on one instance reaches a client connected to a different instance
— "cross-instance delivery with no session affinity" (F53).

`PubSubRelay` is that subscriber: one Redis pattern-subscription
(`chan:*` + `dm:*` + `presence:*`) per process, rather than one Redis
subscription per joined topic — simpler to run and to reason about at
chatspace's scale (CLAUDE.md: "a couple of app instances", no cluster),
and it means a connection joining/leaving a topic is pure in-process
bookkeeping (`ConnectionManager.subscribe`/`unsubscribe`) with no
matching Redis `SUBSCRIBE`/`UNSUBSCRIBE` round-trip needed.

`presence:*` (T25, `app.core.redis_keys.presence_topic`) rides this same
relay so a `presence` online/offline event fans out cross-instance
exactly like `message.*` (F53) — it does not overlap with the *other*
`presence:`-prefixed Redis keys (`presence:conn_count:*`,
`presence:state:*`, `presence:typing:*`): those are plain GET/SET/EXPIRE
keys, never `PUBLISH`ed to, so they never arrive here regardless of this
pattern subscription.

Delivery here is the live half of the contract's at-least-once model —
a relay that is down, restarting, or briefly disconnected from Redis
simply misses the events published during that window; a reconnecting
client's own history-since-last-id catch-up (F55) is what recovers
them, not this class. `_run` therefore never lets a single read error
kill the relay: it logs and retries after a short backoff instead.

The same posture applies to the *initial* subscribe: if Redis is
unreachable at the exact moment a process boots (a Redis restart/blip
during deploy or autoscale), `start()` does not give up permanently.
When the first `psubscribe` attempt fails, `_run_until_subscribed`
keeps retrying with backoff in the background until it succeeds or the
relay is stopped, so a transient outage at boot degrades to "not yet
subscribed for a few seconds" rather than "never subscribed for the
rest of this process's life" — the failure mode a one-shot, unretried
subscribe attempt would otherwise have.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from app.ws.connection_manager import ConnectionManager, connection_manager

logger = logging.getLogger(__name__)

# One pattern subscription covers every channel/DM/presence topic
# (`app.core.redis_keys.channel_topic`/`dm_topic`/`presence_topic`)
# without the relay needing to track which literal topics currently have
# a joined local connection — `ConnectionManager.broadcast_to_topic`
# already filters to only the topics with a live subscriber.
_CHANNEL_PATTERN = "chan:*"
_DM_PATTERN = "dm:*"
_PRESENCE_PATTERN = "presence:*"

# How long a single `get_message` poll blocks waiting for the next
# fan-out event before returning `None` and looping again. Bounds how
# quickly `stop()` (cancelling `_task`) can interrupt the read loop;
# short enough that shutdown/tests are never left waiting long, without
# busy-polling Redis.
_POLL_TIMEOUT_SECONDS = 1.0

# Backoff after an unexpected read error (e.g. a transient Redis
# disconnect) before retrying, so a wedged/flapping Redis cannot spin
# this loop at full CPU.
_ERROR_BACKOFF_SECONDS = 1.0


class PubSubRelay:
    """One process's Redis pub/sub subscriber, relaying to its own `ConnectionManager`.

    Not a process-wide singleton like `connection_manager` — the
    application lifespan (`app.main`) owns exactly one instance bound to
    the process-wide Redis client, started before the app begins serving
    and stopped on shutdown. Tests construct their own instances (bound
    to their own `ConnectionManager`) to simulate independent app
    instances sharing one Redis.
    """

    def __init__(self, redis: Redis, *, manager: ConnectionManager | None = None) -> None:
        self._redis = redis
        self._manager = manager if manager is not None else connection_manager
        self._pubsub: PubSub | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Subscribe and start the background relay loop.

        Idempotent — a no-op if this relay is already running. Never
        raises: if Redis is reachable right now, this behaves exactly as
        before — `psubscribe` completes before `start()` returns, so a
        caller (or a test) that publishes immediately after `await
        relay.start()` is guaranteed the subscription is already live.

        If the *initial* `psubscribe` fails (Redis unreachable at this
        exact moment — a restart/blip racing this process's boot),
        `start()` still returns without raising, but it does not give up
        permanently: a background task keeps retrying the subscribe with
        backoff (`_run_until_subscribed`) until it succeeds, so this
        process becomes a live subscriber as soon as Redis comes back
        rather than staying silently unsubscribed for its whole
        lifetime — the gap a one-shot, unretried subscribe attempt would
        otherwise leave.
        """

        if self._task is not None:
            return

        if await self._try_subscribe():
            self._task = asyncio.create_task(self._run(), name="ws-pubsub-relay")
            logger.info("ws pub/sub relay started")
            return

        logger.warning(
            "ws pub/sub relay could not subscribe on startup; retrying in the background"
        )
        self._task = asyncio.create_task(self._run_until_subscribed(), name="ws-pubsub-relay")

    async def stop(self) -> None:
        """Cancel the relay loop and close the pub/sub connection (idempotent)."""

        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

        if self._pubsub is not None:
            with contextlib.suppress(Exception):
                await self._pubsub.aclose()
            self._pubsub = None

        logger.info("ws pub/sub relay stopped")

    async def _try_subscribe(self) -> bool:
        """Attempt `psubscribe` once. Returns whether it succeeded; never raises."""

        try:
            self._pubsub = self._redis.pubsub()
            await self._pubsub.psubscribe(_CHANNEL_PATTERN, _DM_PATTERN, _PRESENCE_PATTERN)
            return True
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - report failure to the caller, never let it be terminal
            logger.exception("ws pub/sub relay failed to subscribe")
            self._pubsub = None
            return False

    async def _run_until_subscribed(self) -> None:
        """Retry `_try_subscribe` with backoff until it succeeds, then read forever.

        The background task `start()` falls back to when the initial
        subscribe attempt fails. No retry cap: at chatspace's scale (a
        couple of app instances, one Redis, CLAUDE.md) an instance that
        cannot reach Redis at all has nothing better to fall back to, and
        every attempt already fails open elsewhere (publish side:
        `message_events.redis_fail_open`; client side: reconnect
        catch-up, F55) — so retrying indefinitely here rather than giving
        up after N tries is the correct trade-off, not an oversight.
        """

        while not await self._try_subscribe():
            await asyncio.sleep(_ERROR_BACKOFF_SECONDS)

        logger.info("ws pub/sub relay started (subscribed after retrying)")
        await self._run()

    async def _run(self) -> None:
        assert self._pubsub is not None
        while True:
            try:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=_POLL_TIMEOUT_SECONDS
                )
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - never let a transient Redis error kill the relay
                logger.exception("ws pub/sub relay read failed; retrying")
                await asyncio.sleep(_ERROR_BACKOFF_SECONDS)
                continue

            if message is None:
                continue

            await self._handle_message(message)

    async def _handle_message(self, message: dict[str, object]) -> None:
        topic = message.get("channel")
        raw_data = message.get("data")
        if not isinstance(topic, str) or not isinstance(raw_data, str):
            # Subscribe confirmations and any non-string payload are not
            # a fan-out event this relay understands — drop silently.
            return

        try:
            payload = json.loads(raw_data)
        except json.JSONDecodeError:
            logger.warning(
                "ws pub/sub relay received a non-JSON payload; dropping",
                extra={"topic": topic},
            )
            return

        if not isinstance(payload, dict):
            logger.warning(
                "ws pub/sub relay received a non-object payload; dropping",
                extra={"topic": topic},
            )
            return

        await self._manager.broadcast_to_topic(topic, payload)
