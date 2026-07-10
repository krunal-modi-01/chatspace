"""Unit/integration tests for `app.core.rate_limit` (T27).

The token-bucket engine's atomicity guarantee comes from a Lua script
run *inside* Redis, so its actual behavior (not just the Python-side
wrapper logic) needs a real Redis to exercise — these tests use the
shared `redis_available`/`configured_env` fixtures and are skipped (not
failed) when no local Redis is reachable, matching every other
Redis-backed test in this suite (see `test_redis_client.py`,
`test_session_revocation.py`).

Every test uses a fresh, random subject (`uuid4()`) per bucket so tests
never collide with each other or with unrelated suites sharing the same
Redis database across the whole test session (this codebase does not
flush Redis between tests) — the same isolation strategy
`test_redis_keys.py`/`test_session_revocation.py` rely on.

Refill behavior is asserted by passing an explicit `now` to
`check_rate_limit`/`enforce_rate_limit` rather than sleeping real time —
`app.core.rate_limit`'s module docstring explains why the engine accepts
a caller-supplied clock instead of `redis.call('TIME')`.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.rate_limit import (
    RateLimitDecision,
    RateLimitUnavailableError,
    auth_rate_limit_subject,
    check_rate_limit,
    enforce_rate_limit,
)
from app.core.redis_keys import RateLimitScope, rate_limit_bucket_key
from app.core.token_hash import hash_rate_limit_identifier

pytestmark = pytest.mark.usefixtures("configured_env")

_BASE_NOW = 1_700_000_000.0


def _skip_unless_redis(redis_available: bool) -> None:
    if not redis_available:
        pytest.skip("local Redis not reachable on localhost:6379")


@pytest.fixture
def redis_client(configured_env: None, redis_available: bool):  # type: ignore[no-untyped-def]
    """A `get_redis_client()` instance fresh to *this* test's event loop.

    Reuses `app.db.redis.get_redis_client()` (rather than hardcoding a
    connection string) so this test targets the same per-worktree Redis
    index `conftest.py`'s `configured_env` fixture derives. Not an `async
    def` fixture, and clears the process-wide cache before/after: with
    `asyncio_mode = "auto"`, every async test gets its own event loop, and
    a cached client from a previous test's now-closed loop raises
    "attached to a different loop" — the identical pattern
    `test_ws_connection_manager.py`'s `redis_client` fixture uses.
    """

    _skip_unless_redis(redis_available)

    from app.db.redis import get_redis_client

    get_redis_client.cache_clear()
    yield get_redis_client()
    get_redis_client.cache_clear()


class BrokenRedis:
    """A fake Redis whose every relevant operation raises, simulating an outage."""

    def register_script(self, script: str) -> BrokenRedis:
        return self

    async def __call__(self, *args: object, **kwargs: object) -> object:
        raise RedisConnectionError("Redis is down")


class TestTokenBucketAlgorithm:
    async def test_allows_requests_up_to_capacity(self, redis_client: Redis) -> None:
        subject = str(uuid4())

        # capacity 3 via MEDIA_UPLOAD-shaped policy would require overriding
        # the module's fixed policy table, so instead drive the scope with
        # its real MESSAGE_SEND capacity (20) directly through `_consume`'s
        # public entry point (`check_rate_limit`) at a fixed `now`.
        decisions = [
            await check_rate_limit(
                redis_client, scope=RateLimitScope.MESSAGE_SEND, subject=subject, now=_BASE_NOW
            )
            for _ in range(20)
        ]

        assert all(d.allowed for d in decisions)

    async def test_denies_the_request_beyond_capacity(self, redis_client: Redis) -> None:
        subject = str(uuid4())

        for _ in range(20):
            decision = await check_rate_limit(
                redis_client, scope=RateLimitScope.MESSAGE_SEND, subject=subject, now=_BASE_NOW
            )
            assert decision.allowed

        over_limit = await check_rate_limit(
            redis_client, scope=RateLimitScope.MESSAGE_SEND, subject=subject, now=_BASE_NOW
        )

        assert over_limit.allowed is False
        assert over_limit.retry_after_seconds >= 1

    async def test_refills_over_time_and_allows_again(self, redis_client: Redis) -> None:
        subject = str(uuid4())

        for _ in range(20):
            decision = await check_rate_limit(
                redis_client, scope=RateLimitScope.MESSAGE_SEND, subject=subject, now=_BASE_NOW
            )
            assert decision.allowed

        denied = await check_rate_limit(
            redis_client, scope=RateLimitScope.MESSAGE_SEND, subject=subject, now=_BASE_NOW
        )
        assert denied.allowed is False

        # MESSAGE_SEND refills at 1 token/second; 5 seconds later there
        # should be 5 tokens available again.
        for _ in range(5):
            decision = await check_rate_limit(
                redis_client,
                scope=RateLimitScope.MESSAGE_SEND,
                subject=subject,
                now=_BASE_NOW + 5.0,
            )
            assert decision.allowed

        still_denied = await check_rate_limit(
            redis_client, scope=RateLimitScope.MESSAGE_SEND, subject=subject, now=_BASE_NOW + 5.0
        )
        assert still_denied.allowed is False

    async def test_retry_after_reflects_refill_rate(self, redis_client: Redis) -> None:
        subject = str(uuid4())

        # AUTH: capacity 5, refill 5/300s (~0.0166667 tokens/sec).
        for _ in range(5):
            decision = await check_rate_limit(
                redis_client, scope=RateLimitScope.AUTH, subject=subject, now=_BASE_NOW
            )
            assert decision.allowed

        denied = await check_rate_limit(
            redis_client, scope=RateLimitScope.AUTH, subject=subject, now=_BASE_NOW
        )

        assert denied.allowed is False
        # One token at that refill rate takes 60s to regenerate from empty.
        assert denied.retry_after_seconds == 60

    async def test_different_subjects_have_independent_buckets(self, redis_client: Redis) -> None:
        subject_a, subject_b = str(uuid4()), str(uuid4())

        for _ in range(20):
            decision = await check_rate_limit(
                redis_client, scope=RateLimitScope.MESSAGE_SEND, subject=subject_a, now=_BASE_NOW
            )
            assert decision.allowed

        # subject_a is now exhausted, subject_b must be unaffected.
        exhausted = await check_rate_limit(
            redis_client, scope=RateLimitScope.MESSAGE_SEND, subject=subject_a, now=_BASE_NOW
        )
        fresh = await check_rate_limit(
            redis_client, scope=RateLimitScope.MESSAGE_SEND, subject=subject_b, now=_BASE_NOW
        )

        assert exhausted.allowed is False
        assert fresh.allowed is True

    async def test_different_scopes_for_the_same_subject_are_independent(
        self, redis_client: Redis
    ) -> None:
        subject = str(uuid4())

        for _ in range(20):
            decision = await check_rate_limit(
                redis_client, scope=RateLimitScope.MESSAGE_SEND, subject=subject, now=_BASE_NOW
            )
            assert decision.allowed

        message_send_exhausted = await check_rate_limit(
            redis_client, scope=RateLimitScope.MESSAGE_SEND, subject=subject, now=_BASE_NOW
        )
        media_upload_fresh = await check_rate_limit(
            redis_client, scope=RateLimitScope.MEDIA_UPLOAD, subject=subject, now=_BASE_NOW
        )

        assert message_send_exhausted.allowed is False
        assert media_upload_fresh.allowed is True

    async def test_writes_to_the_documented_bucket_key(self, redis_client: Redis) -> None:
        subject = str(uuid4())

        await check_rate_limit(
            redis_client, scope=RateLimitScope.MESSAGE_SEND, subject=subject, now=_BASE_NOW
        )

        key = rate_limit_bucket_key(RateLimitScope.MESSAGE_SEND, subject)
        assert await redis_client.exists(key) == 1
        await redis_client.delete(key)


class TestEnforceRateLimitFailModes:
    async def test_fail_closed_raises_on_redis_outage(self) -> None:
        with pytest.raises(RateLimitUnavailableError):
            await enforce_rate_limit(
                BrokenRedis(),  # type: ignore[arg-type]
                scope=RateLimitScope.MESSAGE_SEND,
                subject=str(uuid4()),
                fail_closed=True,
                now=_BASE_NOW,
            )

    async def test_fail_open_degrades_to_allowed_on_redis_outage(self) -> None:
        decision = await enforce_rate_limit(
            BrokenRedis(),  # type: ignore[arg-type]
            scope=RateLimitScope.MEDIA_UPLOAD,
            subject=str(uuid4()),
            fail_closed=False,
            now=_BASE_NOW,
        )

        assert decision == RateLimitDecision(allowed=True, retry_after_seconds=0)

    async def test_fail_closed_still_returns_the_real_decision_when_redis_is_up(
        self, redis_client: Redis
    ) -> None:
        subject = str(uuid4())

        decision = await enforce_rate_limit(
            redis_client,
            scope=RateLimitScope.MESSAGE_SEND,
            subject=subject,
            fail_closed=True,
            now=_BASE_NOW,
        )

        assert decision.allowed is True


class TestAuthRateLimitSubject:
    def test_same_shape_regardless_of_identifier_validity(self) -> None:
        """Non-enumeration: the subject-building function never looks anything up."""

        valid_looking = auth_rate_limit_subject(
            client_ip="203.0.113.7", identifier="real@example.com"
        )
        made_up = auth_rate_limit_subject(
            client_ip="203.0.113.7", identifier="does-not-exist@example.com"
        )

        # Different identifiers naturally produce different buckets (each
        # gets its own quota), but the *construction* is identical: a
        # fixed-shape "ip:hash" string, never branching on validity.
        assert valid_looking != made_up
        assert valid_looking.startswith("203.0.113.7:")
        assert made_up.startswith("203.0.113.7:")

    def test_never_embeds_the_raw_identifier(self) -> None:
        identifier = "someone-sensitive@example.com"

        subject = auth_rate_limit_subject(client_ip="203.0.113.7", identifier=identifier)

        assert identifier not in subject
        assert hash_rate_limit_identifier(identifier) in subject

    def test_is_deterministic(self) -> None:
        first = auth_rate_limit_subject(client_ip="203.0.113.7", identifier="alice@example.com")
        second = auth_rate_limit_subject(client_ip="203.0.113.7", identifier="alice@example.com")

        assert first == second
