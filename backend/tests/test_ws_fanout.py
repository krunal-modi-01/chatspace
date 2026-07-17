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
import json
from typing import Any
from uuid import uuid4

import pytest
from starlette.websockets import WebSocketState

from app.core.ids import generate_id
from app.core.redis_keys import channel_topic, dm_topic, presence_topic, user_topic
from app.services.message_events import build_created_event
from app.ws.connection_manager import ConnectionManager
from app.ws.fanout import PubSubRelay, _typing_typer_id
from app.ws.frames import ChannelConversation
from app.ws.typing_events import build_typing_event

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


def _register_as(manager: ConnectionManager, websocket: _FakeWebSocket, *, user_id: Any) -> Any:
    return manager.register(websocket, user_id=user_id, session_id=uuid4())  # type: ignore[arg-type]


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

    async def test_exclude_user_id_skips_every_connection_of_that_user(self) -> None:
        """`exclude_user_id` (T26) must skip *all* of the excluded user's
        connections (every tab/instance), not just one — a `typing`
        event must never bounce back to any of the typer's own tabs.
        """

        manager = ConnectionManager()
        typer_user_id = uuid4()
        ws_typer_tab_1 = _FakeWebSocket()
        ws_typer_tab_2 = _FakeWebSocket()
        ws_other_user = _FakeWebSocket()
        for state in (
            _register_as(manager, ws_typer_tab_1, user_id=typer_user_id),
            _register_as(manager, ws_typer_tab_2, user_id=typer_user_id),
            _register(manager, ws_other_user),
        ):
            manager.subscribe(state, "chan:abc")

        await manager.broadcast_to_topic(
            "chan:abc", {"type": "typing"}, exclude_user_id=typer_user_id
        )

        assert ws_typer_tab_1.received == []
        assert ws_typer_tab_2.received == []
        assert ws_other_user.received == [{"type": "typing"}]

    async def test_no_exclude_user_id_delivers_to_the_sender_too(self) -> None:
        """No regression for `message.*`: omitting `exclude_user_id`
        delivers to every subscribed connection, including one belonging
        to whichever user "sent" the event.
        """

        manager = ConnectionManager()
        sender_user_id = uuid4()
        ws_sender = _FakeWebSocket()
        state = _register_as(manager, ws_sender, user_id=sender_user_id)
        manager.subscribe(state, "chan:abc")

        await manager.broadcast_to_topic("chan:abc", {"type": "message.created"})

        assert ws_sender.received == [{"type": "message.created"}]


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

    async def test_presence_event_published_reaches_a_subscriber_relay(
        self, redis_client: Any
    ) -> None:
        """Regression for code review finding 1 (T25): `PubSubRelay` must
        actually subscribe to `presence:*`, not just define the pattern
        constant — otherwise every presence online/offline event is
        silently dropped by Redis (no matching subscriber) and never
        reaches any connected client.
        """

        manager = ConnectionManager()
        ws = _FakeWebSocket()
        state = _register(manager, ws)
        user_id = uuid4()
        topic = presence_topic(user_id)
        manager.subscribe(state, topic)

        relay = PubSubRelay(redis_client, manager=manager)
        await relay.start()
        try:
            event = {
                "type": "presence",
                "conversation": None,
                "data": {"user_id": str(user_id), "state": "online", "last_seen": None},
            }
            await redis_client.publish(topic, json.dumps(event))

            await _wait_until(lambda: len(ws.received) == 1)
            assert ws.received[0]["type"] == "presence"
            assert ws.received[0]["data"]["user_id"] == str(user_id)
            assert ws.received[0]["data"]["state"] == "online"
        finally:
            await relay.stop()

    async def test_member_added_event_published_on_user_topic_reaches_a_subscriber_relay(
        self, redis_client: Any
    ) -> None:
        """T49/ADR-0012: `PubSubRelay` must actually subscribe to `user:*` —
        otherwise every `channel.member_added`/`channel.member_removed`
        event is silently dropped by Redis (no matching subscriber) and
        never reaches any connected client, mirroring the T25 presence
        regression this test file already guards against.
        """

        manager = ConnectionManager()
        ws = _FakeWebSocket()
        state = _register(manager, ws)
        user_id = uuid4()
        topic = user_topic(user_id)
        manager.subscribe(state, topic)

        relay = PubSubRelay(redis_client, manager=manager)
        await relay.start()
        try:
            event = {
                "type": "channel.member_added",
                "conversation": {"kind": "channel", "channel_id": str(uuid4())},
                "data": {
                    "channel": {
                        "id": str(uuid4()),
                        "name": "engineering",
                        "is_private": False,
                        "created_by": str(uuid4()),
                        "created_at": "2026-07-02T14:31:07.482000+00:00",
                        "member_count": 2,
                    },
                    "user_id": str(user_id),
                    "role": "member",
                    "joined_at": "2026-07-03T09:00:00+00:00",
                },
            }
            await redis_client.publish(topic, json.dumps(event))

            await _wait_until(lambda: len(ws.received) == 1)
            assert ws.received[0]["type"] == "channel.member_added"
            assert ws.received[0]["data"]["user_id"] == str(user_id)
        finally:
            await relay.stop()

    async def test_only_the_subscribed_users_own_connection_receives_the_event(
        self, redis_client: Any
    ) -> None:
        """Privacy: an event published on one user's `user:{id}` topic must
        never reach a connection subscribed to a *different* user's topic
        — delivery is per-user, never per-channel (F74/F75 isolation).
        """

        manager = ConnectionManager()
        ws_target = _FakeWebSocket()
        ws_other = _FakeWebSocket()
        target_user_id = uuid4()
        other_user_id = uuid4()
        manager.subscribe(_register(manager, ws_target), user_topic(target_user_id))
        manager.subscribe(_register(manager, ws_other), user_topic(other_user_id))

        relay = PubSubRelay(redis_client, manager=manager)
        await relay.start()
        try:
            event = {
                "type": "channel.member_removed",
                "conversation": {"kind": "channel", "channel_id": str(uuid4())},
                "data": {"channel_id": str(uuid4()), "user_id": str(target_user_id)},
            }
            await redis_client.publish(user_topic(target_user_id), json.dumps(event))

            await _wait_until(lambda: len(ws_target.received) == 1)
            assert ws_other.received == []
        finally:
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

    async def test_typing_event_is_not_relayed_back_to_the_typers_own_connection(
        self, redis_client: Any
    ) -> None:
        """T26: a `typing` event fans out to *other* participants only —
        the relay must exclude the typer's own connection even though it
        is subscribed to the same topic (contract: "fans out ... to
        other participants of the same channel/DM only").
        """

        manager = ConnectionManager()
        typer_user_id = uuid4()
        other_user_id = uuid4()
        ws_typer = _FakeWebSocket()
        ws_other = _FakeWebSocket()
        topic = channel_topic(uuid4())
        manager.subscribe(_register_as(manager, ws_typer, user_id=typer_user_id), topic)
        manager.subscribe(_register_as(manager, ws_other, user_id=other_user_id), topic)

        event = build_typing_event(
            user_id=typer_user_id,
            conversation=ChannelConversation(kind="channel", channel_id=uuid4()),
        )

        relay = PubSubRelay(redis_client, manager=manager)
        await relay.start()
        try:
            import json

            await redis_client.publish(topic, json.dumps(event))

            await _wait_until(lambda: len(ws_other.received) == 1)
            assert ws_other.received[0] == event
            assert ws_typer.received == []
        finally:
            await relay.stop()

    async def test_message_created_still_relays_to_the_senders_own_connection(
        self, redis_client: Any
    ) -> None:
        """No regression: only `typing` self-excludes — `message.*` events
        must still reach every subscribed connection, including one
        belonging to the sender.
        """

        manager = ConnectionManager()
        sender_user_id = uuid4()
        ws_sender = _FakeWebSocket()
        topic = channel_topic(uuid4())
        manager.subscribe(_register_as(manager, ws_sender, user_id=sender_user_id), topic)

        relay = PubSubRelay(redis_client, manager=manager)
        await relay.start()
        try:
            await redis_client.publish(
                topic, '{"type": "message.created", "data": {"sender_id": "irrelevant-here"}}'
            )

            await _wait_until(lambda: len(ws_sender.received) == 1)
        finally:
            await relay.stop()


class TestTypingTyperId:
    """Unit tests for `app.ws.fanout._typing_typer_id`."""

    def test_extracts_user_id_from_a_typing_event(self) -> None:
        typer_id = uuid4()
        payload = {"type": "typing", "data": {"user_id": str(typer_id)}}

        assert _typing_typer_id(payload) == typer_id

    def test_returns_none_for_non_typing_event_types(self) -> None:
        payload = {"type": "message.created", "data": {"user_id": str(uuid4())}}

        assert _typing_typer_id(payload) is None

    def test_returns_none_when_data_is_missing_or_not_an_object(self) -> None:
        assert _typing_typer_id({"type": "typing"}) is None
        assert _typing_typer_id({"type": "typing", "data": "not-an-object"}) is None

    def test_returns_none_when_user_id_is_missing_or_malformed(self) -> None:
        assert _typing_typer_id({"type": "typing", "data": {}}) is None
        assert _typing_typer_id({"type": "typing", "data": {"user_id": 123}}) is None
        assert _typing_typer_id({"type": "typing", "data": {"user_id": "not-a-uuid"}}) is None


class TestDeliveryLagMs:
    """Unit tests for `app.ws.fanout._delivery_lag_ms` (T39 delivery-lag SLI)."""

    def test_computes_a_non_negative_lag_for_message_created(self) -> None:
        from datetime import UTC, datetime, timedelta

        from app.ws.fanout import _delivery_lag_ms

        created_at = (datetime.now(UTC) - timedelta(milliseconds=250)).isoformat()
        payload = {"type": "message.created", "data": {"created_at": created_at}}

        lag_ms = _delivery_lag_ms(payload)

        assert lag_ms is not None
        assert lag_ms >= 200  # allow scheduling jitter, comfortably below the 250ms floor

    def test_returns_none_for_non_created_event_types(self) -> None:
        from app.ws.fanout import _delivery_lag_ms

        assert _delivery_lag_ms({"type": "message.edited", "data": {"created_at": "x"}}) is None
        assert _delivery_lag_ms({"type": "presence", "data": {}}) is None

    def test_returns_none_when_created_at_is_missing_or_malformed(self) -> None:
        from app.ws.fanout import _delivery_lag_ms

        assert _delivery_lag_ms({"type": "message.created", "data": {}}) is None
        assert _delivery_lag_ms({"type": "message.created"}) is None
        assert (
            _delivery_lag_ms({"type": "message.created", "data": {"created_at": "not-a-date"}})
            is None
        )

    def test_naive_datetime_is_treated_as_utc(self) -> None:
        from datetime import UTC, datetime, timedelta

        from app.ws.fanout import _delivery_lag_ms

        naive = (datetime.now(UTC) - timedelta(milliseconds=100)).replace(tzinfo=None)
        payload = {"type": "message.created", "data": {"created_at": naive.isoformat()}}

        lag_ms = _delivery_lag_ms(payload)

        assert lag_ms is not None
        assert lag_ms >= 0

    async def test_relaying_a_message_created_event_observes_the_histogram(self) -> None:
        from datetime import UTC, datetime, timedelta

        from app.core import metrics as metrics_module
        from app.ws.fanout import PubSubRelay

        metrics_module.reset_metrics()
        manager = ConnectionManager()
        relay = PubSubRelay(object(), manager=manager)  # type: ignore[arg-type]

        created_at = (datetime.now(UTC) - timedelta(milliseconds=10)).isoformat()
        payload = {
            "type": "message.created",
            "conversation": {"kind": "channel", "channel_id": str(uuid4())},
            "data": {"created_at": created_at},
        }
        message = {"channel": "chan:x", "data": json.dumps(payload)}

        await relay._handle_message(message)

        stats = metrics_module.snapshot()["histograms"]["message_delivery_lag_ms"]["_total"]
        assert stats["count"] == 1


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
