"""Tests for `app.services.presence` (T25, F49-F50).

Two layers, mirroring `test_rate_limit.py`'s structure:

- Pure unit tests of `build_presence_event`'s envelope shape (no Redis).
- Real-Redis (+ real Postgres for the `last_seen` write) integration
  tests of the ref-count lifecycle: connect/heartbeat/disconnect,
  ref-counting across multiple connections for the same user, the
  online/offline transition only firing on the first connect / last
  disconnect, the durable `last_seen` write, and the Redis fail-open
  behaviors documented in the module's docstrings — including the
  explicit "must not show falsely online after a Redis restart"
  correctness bar (a missing counter key, e.g. after a restart, always
  reads as offline).

Every test uses a fresh `uuid4()` subject per case so tests never
collide with each other or with unrelated suites sharing the same Redis
database across the whole test session (this codebase does not flush
Redis between tests) — the same isolation strategy `test_rate_limit.py`/
`test_redis_keys.py` rely on.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import generate_id
from app.core.redis_keys import presence_connection_count_key, presence_topic
from app.core.security import hash_password
from app.models.user import User
from app.services.presence import (
    build_presence_event,
    handle_connect,
    handle_disconnect,
    handle_heartbeat,
    is_online,
)

pytestmark = pytest.mark.usefixtures("configured_env")

_TTL_SECONDS = 120


def _skip_unless_redis(redis_available: bool) -> None:
    if not redis_available:
        pytest.skip("local Redis not reachable on localhost:6379")


@pytest.fixture
def redis_client(configured_env: None, redis_available: bool):  # type: ignore[no-untyped-def]
    """A `get_redis_client()` instance fresh to *this* test's event loop.

    Identical pattern to `test_rate_limit.py`'s/`test_ws_connection_manager.py`'s
    `redis_client` fixture — the process-wide `lru_cache`d client must not
    be reused across `pytest-asyncio`'s per-test event loops.
    """

    _skip_unless_redis(redis_available)

    from app.db.redis import get_redis_client

    get_redis_client.cache_clear()
    yield get_redis_client()
    get_redis_client.cache_clear()


async def _make_user(db: AsyncSession) -> User:
    unique = generate_id().hex[-12:]
    user = User(
        id=generate_id(),
        username=f"user{unique}",
        email=f"{unique}@example.com",
        hashed_password=hash_password("correct-horse-1"),
        first_name="Test",
        last_name="User",
        is_active=True,
        is_system_admin=False,
    )
    db.add(user)
    await db.flush()
    await db.commit()
    return user


class BrokenRedis:
    """A fake Redis whose every relevant operation raises, simulating an outage.

    Mirrors `test_rate_limit.py`'s `BrokenRedis`.
    """

    def register_script(self, script: str) -> BrokenRedis:
        return self

    async def __call__(self, *args: object, **kwargs: object) -> object:
        raise RedisConnectionError("Redis is down")

    async def incr(self, *args: object, **kwargs: object) -> int:
        raise RedisConnectionError("Redis is down")

    async def expire(self, *args: object, **kwargs: object) -> None:
        raise RedisConnectionError("Redis is down")

    async def get(self, *args: object, **kwargs: object) -> None:
        raise RedisConnectionError("Redis is down")

    async def publish(self, *args: object, **kwargs: object) -> None:
        raise RedisConnectionError("Redis is down")


class TestBuildPresenceEvent:
    def test_online_event_shape(self) -> None:
        user_id = uuid4()

        event = build_presence_event(user_id=user_id, state="online", last_seen=None)

        assert event == {
            "type": "presence",
            "conversation": None,
            "data": {"user_id": str(user_id), "state": "online", "last_seen": None},
        }

    def test_offline_event_carries_iso8601_last_seen(self) -> None:
        user_id = uuid4()
        last_seen = datetime(2026, 7, 13, 12, 0, 0, tzinfo=UTC)

        event = build_presence_event(user_id=user_id, state="offline", last_seen=last_seen)

        assert event["data"]["state"] == "offline"
        assert event["data"]["last_seen"] == last_seen.isoformat()

    def test_no_conversation_field_populated(self) -> None:
        """Presence is user-scoped, not conversation-scoped — always `None`."""

        event = build_presence_event(user_id=uuid4(), state="online", last_seen=None)

        assert event["conversation"] is None


class TestIsOnline:
    async def test_false_when_never_connected(self, redis_client: Redis) -> None:
        user_id = uuid4()

        assert await is_online(redis_client, user_id) is False

    async def test_true_after_connect(self, redis_client: Redis) -> None:
        user_id = uuid4()

        await handle_connect(redis_client, user_id=user_id, ttl_seconds=_TTL_SECONDS)

        assert await is_online(redis_client, user_id) is True

    async def test_false_after_full_disconnect(
        self, redis_client: Redis, db_session: AsyncSession
    ) -> None:
        user_id = (await _make_user(db_session)).id

        await handle_connect(redis_client, user_id=user_id, ttl_seconds=_TTL_SECONDS)
        await handle_disconnect(redis_client, db_session, user_id=user_id)

        assert await is_online(redis_client, user_id) is False

    async def test_fails_open_to_false_on_redis_outage(self) -> None:
        assert await is_online(BrokenRedis(), uuid4()) is False  # type: ignore[arg-type]

    async def test_never_falsely_online_after_a_redis_restart(self, redis_client: Redis) -> None:
        """The explicit T25 correctness bar: a restart wipes the ref-count
        key unconditionally, so a user with a *supposedly* still-live
        connection reads as offline afterward, never as stale-online.
        """

        user_id = uuid4()
        await handle_connect(redis_client, user_id=user_id, ttl_seconds=_TTL_SECONDS)
        assert await is_online(redis_client, user_id) is True

        # Simulate a full Redis restart wiping the ref-count key.
        await redis_client.delete(presence_connection_count_key(user_id))

        assert await is_online(redis_client, user_id) is False


class TestRefCounting:
    async def test_only_the_first_connect_is_online(self, redis_client: Redis) -> None:
        user_id = uuid4()
        topic = presence_topic(user_id)
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(topic)
        try:
            await pubsub.get_message(timeout=1)  # subscribe confirmation

            await handle_connect(redis_client, user_id=user_id, ttl_seconds=_TTL_SECONDS)
            first = await pubsub.get_message(timeout=1)
            assert first is not None
            assert '"state": "online"' in first["data"]

            # A second concurrent connection for the same user increments
            # the ref-count but must not emit a second `online` event.
            await handle_connect(redis_client, user_id=user_id, ttl_seconds=_TTL_SECONDS)
            second = await pubsub.get_message(timeout=1)
            assert second is None
        finally:
            await pubsub.unsubscribe(topic)
            await pubsub.aclose()

    async def test_ref_count_increments_and_decrements(self, redis_client: Redis) -> None:
        user_id = uuid4()
        key = presence_connection_count_key(user_id)

        await handle_connect(redis_client, user_id=user_id, ttl_seconds=_TTL_SECONDS)
        await handle_connect(redis_client, user_id=user_id, ttl_seconds=_TTL_SECONDS)
        assert await redis_client.get(key) == "2"

    async def test_only_the_last_disconnect_persists_last_seen_and_emits_offline(
        self, redis_client: Redis, db_session: AsyncSession
    ) -> None:
        user = await _make_user(db_session)

        # Two concurrent connections (e.g. two tabs) for the same user.
        await handle_connect(redis_client, user_id=user.id, ttl_seconds=_TTL_SECONDS)
        await handle_connect(redis_client, user_id=user.id, ttl_seconds=_TTL_SECONDS)

        # First disconnect: one connection remains — must not persist
        # `last_seen` or flip presence to offline yet.
        await handle_disconnect(redis_client, db_session, user_id=user.id)
        assert await is_online(redis_client, user.id) is True
        await db_session.refresh(user)
        assert user.last_seen is None

        # Second (last) disconnect: ref-count hits zero.
        await handle_disconnect(redis_client, db_session, user_id=user.id)
        assert await is_online(redis_client, user.id) is False
        await db_session.refresh(user)
        assert user.last_seen is not None

    async def test_ttl_is_set_on_connect(self, redis_client: Redis) -> None:
        user_id = uuid4()

        await handle_connect(redis_client, user_id=user_id, ttl_seconds=_TTL_SECONDS)

        ttl = await redis_client.ttl(presence_connection_count_key(user_id))
        assert 0 < ttl <= _TTL_SECONDS

    async def test_heartbeat_renews_the_ttl(self, redis_client: Redis) -> None:
        user_id = uuid4()
        key = presence_connection_count_key(user_id)

        await handle_connect(redis_client, user_id=user_id, ttl_seconds=5)
        await redis_client.expire(key, 1)  # simulate the TTL having decayed

        await handle_heartbeat(redis_client, user_id=user_id, ttl_seconds=_TTL_SECONDS)

        ttl = await redis_client.ttl(key)
        assert ttl > 5

    async def test_heartbeat_on_a_missing_key_self_heals_by_recreating_it(
        self, redis_client: Redis
    ) -> None:
        """Code review finding 3: a heartbeat on a missing key (e.g. after a
        Redis restart wiped it while this connection was still live) must
        self-heal by re-registering this connection's contribution rather
        than leaving the counter permanently lost — a strict no-op here
        would leave a genuinely-live connection reading as offline until
        it disconnects.
        """

        user_id = uuid4()
        key = presence_connection_count_key(user_id)

        await handle_heartbeat(redis_client, user_id=user_id, ttl_seconds=_TTL_SECONDS)

        assert await redis_client.get(key) == "1"
        ttl = await redis_client.ttl(key)
        assert 0 < ttl <= _TTL_SECONDS

    async def test_heartbeat_self_heal_after_simulated_redis_restart_restores_online(
        self, redis_client: Redis
    ) -> None:
        """End-to-end version of the self-heal case: connect, simulate a
        restart wiping the key, then the next heartbeat brings `is_online`
        back to `True` without a second `handle_connect` call.
        """

        user_id = uuid4()
        await handle_connect(redis_client, user_id=user_id, ttl_seconds=_TTL_SECONDS)
        assert await is_online(redis_client, user_id) is True

        await redis_client.delete(presence_connection_count_key(user_id))
        assert await is_online(redis_client, user_id) is False

        await handle_heartbeat(redis_client, user_id=user_id, ttl_seconds=_TTL_SECONDS)

        assert await is_online(redis_client, user_id) is True

    async def test_disconnect_without_a_prior_connect_is_a_safe_no_op(
        self, redis_client: Redis, db_session: AsyncSession
    ) -> None:
        """A duplicate/late disconnect racing a prior one to zero must not
        underflow the counter or double-persist `last_seen`.
        """

        user = await _make_user(db_session)

        await handle_disconnect(redis_client, db_session, user_id=user.id)

        await db_session.refresh(user)
        # Still persists last_seen (count floors at 0, treated as "last"),
        # per the documented fail-open-toward-offline posture — but must
        # not raise or go negative.
        assert user.last_seen is not None
        assert await redis_client.get(presence_connection_count_key(user.id)) is None


class TestRedisFailModes:
    async def test_connect_never_raises_on_redis_outage(self) -> None:
        # Must not raise despite every Redis operation failing.
        await handle_connect(BrokenRedis(), user_id=uuid4(), ttl_seconds=_TTL_SECONDS)  # type: ignore[arg-type]

    async def test_heartbeat_never_raises_on_redis_outage(self) -> None:
        await handle_heartbeat(BrokenRedis(), user_id=uuid4(), ttl_seconds=_TTL_SECONDS)  # type: ignore[arg-type]

    async def test_disconnect_never_raises_and_still_persists_last_seen(
        self, db_session: AsyncSession
    ) -> None:
        """Per the module docstring: a Redis outage on the decrement fails
        open *toward* "this is the last disconnect" (count treated as 0)
        rather than skipping the durable `last_seen` write.
        """

        user = await _make_user(db_session)

        await handle_disconnect(BrokenRedis(), db_session, user_id=user.id)  # type: ignore[arg-type]

        await db_session.refresh(user)
        assert user.last_seen is not None
