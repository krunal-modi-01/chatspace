"""Unit tests for `app.services.session_revocation` (T10, ADR-0006).

Uses a minimal in-process fake Redis client (not a new dependency — just
enough surface, `get`/`set`/`delete`, to exercise cache-hit, cold-cache,
and Redis-outage behavior deterministically without a live Redis).
Postgres-backed assertions use the real local test database (skipped when
unreachable), matching the rest of the suite's convention.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import generate_id
from app.core.redis_keys import session_revocation_key
from app.models.session import Session
from app.models.user import User
from app.services.session_revocation import invalidate_session_cache, is_session_active

pytestmark = pytest.mark.usefixtures("configured_env")

_CACHE_TTL = 30
_PLACEHOLDER_HASH_VALUE = "not-a-real-hash-value"


class FakeRedis:
    """A trivial in-memory stand-in for the `get`/`set`/`delete` surface used here."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)


class BrokenRedis:
    """A fake Redis whose every operation raises, simulating an outage."""

    async def get(self, key: str) -> str | None:
        raise RedisConnectionError("Redis is down")

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        raise RedisConnectionError("Redis is down")

    async def delete(self, key: str) -> None:
        raise RedisConnectionError("Redis is down")


async def _make_user(db: AsyncSession) -> User:
    user = User(
        id=generate_id(),
        username="alice",
        email="alice@example.com",
        hashed_password=_PLACEHOLDER_HASH_VALUE,
        first_name="A",
        last_name="Lice",
        is_active=True,
        is_system_admin=False,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_session(
    db: AsyncSession, user: User, *, revoked: bool = False, expired: bool = False
) -> Session:
    now = datetime.now(UTC)
    session = Session(
        id=generate_id(),
        user_id=user.id,
        refresh_token_hash=f"hash-{generate_id()}",
        issued_at=now,
        expires_at=(now - timedelta(days=1)) if expired else (now + timedelta(days=30)),
        revoked_at=now if revoked else None,
    )
    db.add(session)
    await db.flush()
    return session


class TestHotPathCacheHit:
    async def test_cached_active_short_circuits_without_touching_postgres(
        self, db_session: AsyncSession
    ) -> None:
        # No matching `sessions` row at all — proves the cache hit alone
        # decides the outcome (a cold lookup would return False for a
        # nonexistent session).
        redis = FakeRedis()
        session_id = generate_id()
        await redis.set(session_revocation_key(session_id), "active")

        active = await is_session_active(
            redis, db_session, session_id=session_id, cache_ttl_seconds=_CACHE_TTL
        )

        assert active is True

    async def test_cached_revoked_short_circuits_to_false(self, db_session: AsyncSession) -> None:
        redis = FakeRedis()
        session_id = generate_id()
        await redis.set(session_revocation_key(session_id), "revoked")

        active = await is_session_active(
            redis, db_session, session_id=session_id, cache_ttl_seconds=_CACHE_TTL
        )

        assert active is False


class TestColdCacheFallback:
    async def test_cold_cache_reads_active_session_from_postgres_and_populates_cache(
        self, db_session: AsyncSession
    ) -> None:
        user = await _make_user(db_session)
        session = await _make_session(db_session, user)
        await db_session.commit()
        redis = FakeRedis()

        active = await is_session_active(
            redis, db_session, session_id=session.id, cache_ttl_seconds=_CACHE_TTL
        )

        assert active is True
        assert await redis.get(session_revocation_key(session.id)) == "active"

    async def test_cold_cache_reads_revoked_session_from_postgres(
        self, db_session: AsyncSession
    ) -> None:
        user = await _make_user(db_session)
        session = await _make_session(db_session, user, revoked=True)
        await db_session.commit()
        redis = FakeRedis()

        active = await is_session_active(
            redis, db_session, session_id=session.id, cache_ttl_seconds=_CACHE_TTL
        )

        assert active is False
        assert await redis.get(session_revocation_key(session.id)) == "revoked"

    async def test_cold_cache_reads_expired_session_as_inactive(
        self, db_session: AsyncSession
    ) -> None:
        user = await _make_user(db_session)
        session = await _make_session(db_session, user, expired=True)
        await db_session.commit()
        redis = FakeRedis()

        active = await is_session_active(
            redis, db_session, session_id=session.id, cache_ttl_seconds=_CACHE_TTL
        )

        assert active is False

    async def test_nonexistent_session_id_is_inactive(self, db_session: AsyncSession) -> None:
        redis = FakeRedis()

        active = await is_session_active(
            redis, db_session, session_id=generate_id(), cache_ttl_seconds=_CACHE_TTL
        )

        assert active is False


class TestRedisDownFallback:
    """Correctness must be preserved when Redis is unreachable (ADR-0006)."""

    async def test_redis_error_on_read_falls_back_to_postgres_for_active_session(
        self, db_session: AsyncSession
    ) -> None:
        user = await _make_user(db_session)
        session = await _make_session(db_session, user)
        await db_session.commit()
        redis = BrokenRedis()

        active = await is_session_active(
            redis, db_session, session_id=session.id, cache_ttl_seconds=_CACHE_TTL
        )

        assert active is True

    async def test_redis_error_on_read_falls_back_to_postgres_for_revoked_session(
        self, db_session: AsyncSession
    ) -> None:
        user = await _make_user(db_session)
        session = await _make_session(db_session, user, revoked=True)
        await db_session.commit()
        redis = BrokenRedis()

        active = await is_session_active(
            redis, db_session, session_id=session.id, cache_ttl_seconds=_CACHE_TTL
        )

        assert active is False


class TestInvalidateSessionCache:
    async def test_removes_a_cached_entry(self) -> None:
        redis = FakeRedis()
        session_id = generate_id()
        await redis.set(session_revocation_key(session_id), "active")

        await invalidate_session_cache(redis, session_id)

        assert await redis.get(session_revocation_key(session_id)) is None

    async def test_is_a_noop_on_a_redis_outage_rather_than_raising(self) -> None:
        redis = BrokenRedis()

        # Must not raise — invalidation fails open since Postgres remains
        # the source of truth for the next cold-cache lookup.
        await invalidate_session_cache(redis, generate_id())
