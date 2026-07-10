"""Tests for T24's fan-out relay: `ConnectionManager.broadcast_to_topic`
and `app.ws.fanout.PubSubRelay`.

Two layers:

- `TestBroadcastToTopic` — pure in-process unit tests of the last hop
  (filtering by topic + connection state, best-effort per connection).
- `TestPubSubRelayCrossInstance` — integration tests against real Redis
  (skipped when unreachable) proving the actual "instance A publishes,
  instance B's independent subscriber relays to its own local sockets"
  behavior (F53, no session affinity), using two separate
  `ConnectionManager`/`PubSubRelay` pairs to stand in for two app
  instances sharing one Redis.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest
from starlette.websockets import WebSocketState

from app.core.ids import generate_id
from app.core.redis_keys import channel_topic, dm_topic
from app.services.message_events import build_created_event
from app.ws.connection_manager import ConnectionManager
from app.ws.fanout import PubSubRelay

pytestmark = pytest.mark.usefixtures("configured_env")


class _FakeWebSocket:
    """A minimal stand-in for `starlette.websockets.WebSocket` in these tests.

    Only implements what `ConnectionManager.broadcast_to_topic` touches:
    `application_state` and `send_json`.
    """

    def __init__(self, *, connected: bool = True, fail: bool = False) -> None:
        self.application_state = (
            WebSocketState.CONNECTED if connected else WebSocketState.DISCONNECTED
        )
        self._fail = fail
        self.received: list[dict[str, Any]] = []

    async def send_json(self, payload: dict[str, Any]) -> None:
        if self._fail:
            raise RuntimeError("simulated send failure")
        self.received.append(payload)


def _register(manager: ConnectionManager, websocket: _FakeWebSocket) -> Any:
    return manager.register(websocket, user_id=uuid4(), session_id=uuid4())  # type: ignore[arg-type]


class TestBroadcastToTopic:
    async def test_delivers_only_to_connections_subscribed_to_the_topic(self) -> None:
        manager = ConnectionManager()
        ws_subscribed = _FakeWebSocket()
        ws_unsubscribed = _FakeWebSocket()
        state_subscribed = _register(manager, ws_subscribed)
        _register(manager, ws_unsubscribed)
        manager.subscribe(state_subscribed, "chan:abc")

        await manager.broadcast_to_topic("chan:abc", {"type": "message.created"})

        assert ws_subscribed.received == [{"type": "message.created"}]
        assert ws_unsubscribed.received == []

    async def test_delivers_to_every_connection_subscribed_regardless_of_count(self) -> None:
        manager = ConnectionManager()
        sockets = [_FakeWebSocket() for _ in range(3)]
        for ws in sockets:
            state = _register(manager, ws)
            manager.subscribe(state, "chan:fanout")

        await manager.broadcast_to_topic(
            "chan:fanout", {"type": "message.created", "data": {"id": "1"}}
        )

        for ws in sockets:
            assert ws.received == [{"type": "message.created", "data": {"id": "1"}}]

    async def test_skips_a_disconnected_socket(self) -> None:
        manager = ConnectionManager()
        ws = _FakeWebSocket(connected=False)
        state = _register(manager, ws)
        manager.subscribe(state, "chan:abc")

        await manager.broadcast_to_topic("chan:abc", {"type": "message.created"})

        assert ws.received == []

    async def test_one_failing_socket_does_not_block_delivery_to_the_rest(self) -> None:
        manager = ConnectionManager()
        ws_failing = _FakeWebSocket(fail=True)
        ws_ok = _FakeWebSocket()
        state_failing = _register(manager, ws_failing)
        state_ok = _register(manager, ws_ok)
        manager.subscribe(state_failing, "chan:abc")
        manager.subscribe(state_ok, "chan:abc")

        # Must not raise despite `ws_failing.send_json` raising internally.
        await manager.broadcast_to_topic("chan:abc", {"type": "message.created"})

        assert ws_ok.received == [{"type": "message.created"}]

    async def test_no_matching_connections_is_a_safe_no_op(self) -> None:
        manager = ConnectionManager()

        await manager.broadcast_to_topic("chan:nobody-here", {"type": "message.created"})


@pytest.fixture
def redis_client(redis_available: bool):  # type: ignore[no-untyped-def]
    """A fresh `get_redis_client()` bound to *this* test's event loop.

    Mirrors the identical fixture in `tests/test_ws_connection_manager.py`
    — the process-wide `lru_cache`d client must not be reused across
    `pytest-asyncio`'s per-test event loops.
    """

    if not redis_available:
        pytest.skip("local Redis not reachable on localhost:6379")

    from app.db.redis import get_redis_client

    get_redis_client.cache_clear()
    yield get_redis_client()
    get_redis_client.cache_clear()


async def _wait_until(predicate: Any, *, timeout_seconds: float = 3.0) -> None:
    """Poll `predicate()` until it's truthy or `timeout_seconds` elapse.

    The relay's read loop is a genuinely async background task racing
    this test's own `publish` call, so delivery isn't synchronous with
    `redis.publish` returning — this bounds how long a test waits for the
    relay to catch up before failing.
    """

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"condition not met within {timeout_seconds}s")


class TestPubSubRelayCrossInstance:
    """Real-Redis proof of "sent on instance A, received by instance B" (F53)."""

    async def test_message_published_on_one_topic_reaches_a_subscriber_relay(
        self, redis_client: Any
    ) -> None:
        manager = ConnectionManager()
        ws = _FakeWebSocket()
        state = _register(manager, ws)
        topic = channel_topic(uuid4())
        manager.subscribe(state, topic)

        relay = PubSubRelay(redis_client, manager=manager)
        await relay.start()
        try:
            await redis_client.publish(topic, '{"type": "message.created", "data": {"id": "1"}}')

            await _wait_until(lambda: len(ws.received) == 1)
            assert ws.received[0] == {"type": "message.created", "data": {"id": "1"}}
        finally:
            await relay.stop()

    async def test_two_independent_instances_both_receive_the_same_publish(
        self, redis_client: Any
    ) -> None:
        """Two separate `ConnectionManager`/`PubSubRelay` pairs simulate two
        app instances sharing one Redis — "instance A publishes, instance
        B's own relay delivers to its own local sockets", with instance A
        (which has no matching local connection here) also *not* getting
        a spurious delivery to some other connection — proving there is
        no session affinity: delivery is purely a function of which
        connections are locally subscribed to the topic, on whichever
        instance they happen to be connected to.
        """

        manager_a = ConnectionManager()  # "instance A": the sender, no local subscriber
        manager_b = ConnectionManager()  # "instance B": has the subscriber

        ws_b = _FakeWebSocket()
        state_b = _register(manager_b, ws_b)
        topic = channel_topic(uuid4())
        manager_b.subscribe(state_b, topic)

        relay_a = PubSubRelay(redis_client, manager=manager_a)
        relay_b = PubSubRelay(redis_client, manager=manager_b)
        await relay_a.start()
        await relay_b.start()
        try:
            await redis_client.publish(
                topic, '{"type": "message.created", "data": {"id": "cross-instance"}}'
            )

            await _wait_until(lambda: len(ws_b.received) == 1)
            assert ws_b.received[0]["data"]["id"] == "cross-instance"
        finally:
            await relay_a.stop()
            await relay_b.stop()

    async def test_dm_topic_publish_reaches_both_participants_regardless_of_join_order(
        self, redis_client: Any
    ) -> None:
        manager = ConnectionManager()
        user_a, user_b = uuid4(), uuid4()
        topic = dm_topic(user_a, user_b)

        ws_1 = _FakeWebSocket()
        ws_2 = _FakeWebSocket()
        state_1 = _register(manager, ws_1)
        state_2 = _register(manager, ws_2)
        # Both participants' connections join the same canonical topic,
        # regardless of the order the two ids are supplied in.
        manager.subscribe(state_1, dm_topic(user_a, user_b))
        manager.subscribe(state_2, dm_topic(user_b, user_a))

        relay = PubSubRelay(redis_client, manager=manager)
        await relay.start()
        try:
            await redis_client.publish(topic, '{"type": "message.created", "data": {"id": "dm-1"}}')

            await _wait_until(lambda: len(ws_1.received) == 1 and len(ws_2.received) == 1)
            assert ws_1.received[0]["data"]["id"] == "dm-1"
            assert ws_2.received[0]["data"]["id"] == "dm-1"
        finally:
            await relay.stop()

    async def test_start_is_idempotent(self, redis_client: Any) -> None:
        manager = ConnectionManager()
        relay = PubSubRelay(redis_client, manager=manager)
        await relay.start()
        try:
            first_task = relay._task  # noqa: SLF001
            await relay.start()
            assert relay._task is first_task  # noqa: SLF001
        finally:
            await relay.stop()

    async def test_stop_is_idempotent(self, redis_client: Any) -> None:
        manager = ConnectionManager()
        relay = PubSubRelay(redis_client, manager=manager)
        await relay.start()
        await relay.stop()
        # Must not raise on a second stop.
        await relay.stop()

    async def test_non_json_payload_on_topic_is_dropped_not_raised(self, redis_client: Any) -> None:
        """A malformed payload on a subscribed topic must not crash the relay
        or the test — it's dropped, and the relay keeps relaying
        subsequent, well-formed events.
        """

        manager = ConnectionManager()
        ws = _FakeWebSocket()
        state = _register(manager, ws)
        topic = channel_topic(uuid4())
        manager.subscribe(state, topic)

        relay = PubSubRelay(redis_client, manager=manager)
        await relay.start()
        try:
            await redis_client.publish(topic, "not-json{{{")
            await redis_client.publish(topic, '{"type": "message.created", "data": {"id": "ok"}}')

            await _wait_until(lambda: len(ws.received) == 1)
            assert ws.received[0]["data"]["id"] == "ok"
        finally:
            await relay.stop()


class _FlakyPubSub:
    """Stands in for `redis.asyncio.client.PubSub`, failing `psubscribe`
    a configurable number of times before succeeding.
    """

    def __init__(self, parent: _FlakySubscribeRedis) -> None:
        self._parent = parent

    async def psubscribe(self, *patterns: str) -> None:
        self._parent.attempts += 1
        if self._parent.attempts <= self._parent.fail_times:
            raise ConnectionError("simulated redis outage")

    async def get_message(self, *, ignore_subscribe_messages: bool, timeout: float) -> None:
        await asyncio.sleep(0)
        return None

    async def aclose(self) -> None:
        return None


class _FlakySubscribeRedis:
    """Stands in for `redis.asyncio.Redis`: unreachable for its first
    `fail_times` subscribe attempts, then reachable — simulating a Redis
    restart/blip racing this process's boot (T24 code review finding 1).
    """

    def __init__(self, *, fail_times: int) -> None:
        self.fail_times = fail_times
        self.attempts = 0

    def pubsub(self) -> _FlakyPubSub:
        return _FlakyPubSub(self)


class _AlwaysFailingRedis:
    """Stands in for a Redis that is entirely unreachable."""

    def pubsub(self) -> Any:
        raise ConnectionError("simulated redis outage")


class TestPubSubRelaySubscribeRetry:
    """Unit-level proof that a failed *initial* subscribe is not terminal
    (code review finding 1): `PubSubRelay` must keep retrying with backoff
    in the background rather than leaving the process permanently
    unsubscribed for the rest of its lifetime.
    """

    async def test_start_never_raises_when_redis_is_entirely_unreachable(self) -> None:
        manager = ConnectionManager()
        relay = PubSubRelay(_AlwaysFailingRedis(), manager=manager)  # type: ignore[arg-type]

        # Must not raise even though every subscribe attempt fails.
        await relay.start()
        try:
            assert relay._task is not None  # noqa: SLF001
            assert not relay._task.done()  # noqa: SLF001 - still retrying in the background
        finally:
            await relay.stop()

    async def test_relay_recovers_and_subscribes_after_a_failed_initial_attempt(
        self, monkeypatch: Any
    ) -> None:
        import app.ws.fanout as fanout_module

        # Speed up the retry backoff so this test doesn't wait on the
        # production 1s interval.
        monkeypatch.setattr(fanout_module, "_ERROR_BACKOFF_SECONDS", 0.01)

        redis = _FlakySubscribeRedis(fail_times=2)
        manager = ConnectionManager()
        relay = PubSubRelay(redis, manager=manager)  # type: ignore[arg-type]

        await relay.start()
        try:
            # The relay must keep retrying past the first (and second)
            # failed attempt rather than giving up after `start()` returns.
            await _wait_until(lambda: redis.attempts >= 3, timeout_seconds=2.0)
            await _wait_until(lambda: relay._pubsub is not None, timeout_seconds=2.0)  # noqa: SLF001
        finally:
            await relay.stop()

    async def test_start_still_subscribes_synchronously_when_redis_is_up(self) -> None:
        """No regression: the common case (Redis reachable) still subscribes
        before `start()` returns, so a publish immediately after `start()`
        is never lost to this race.
        """

        redis = _FlakySubscribeRedis(fail_times=0)
        manager = ConnectionManager()
        relay = PubSubRelay(redis, manager=manager)  # type: ignore[arg-type]

        await relay.start()
        try:
            assert redis.attempts == 1
            assert relay._pubsub is not None  # noqa: SLF001
        finally:
            await relay.stop()


class TestBuildCreatedEventPublishedThroughRelay:
    """Sanity check that the actual envelope builder round-trips through the relay."""

    async def test_full_envelope_survives_publish_and_relay(self, redis_client: Any) -> None:
        from datetime import UTC, datetime

        from app.models.message import Message

        message = Message(
            id=generate_id(),
            channel_id=uuid4(),
            recipient_id=None,
            sender_id=uuid4(),
            content="shipping the release now",
            created_at=datetime.now(UTC),
        )
        event = build_created_event(message)

        manager = ConnectionManager()
        ws = _FakeWebSocket()
        state = _register(manager, ws)
        topic = channel_topic(message.channel_id)
        manager.subscribe(state, topic)

        relay = PubSubRelay(redis_client, manager=manager)
        await relay.start()
        try:
            import json

            await redis_client.publish(topic, json.dumps(event))

            await _wait_until(lambda: len(ws.received) == 1)
            assert ws.received[0] == event
        finally:
            await relay.stop()
