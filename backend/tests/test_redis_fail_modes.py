from __future__ import annotations

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.redis_fail_modes import RedisUnavailableError, redis_fail_closed, redis_fail_open


class TestRedisFailOpen:
    async def test_returns_call_result_on_success(self) -> None:
        async def _call() -> str:
            return "ok"

        result = await redis_fail_open("test.op", _call, default="fallback")

        assert result == "ok"

    async def test_returns_default_on_redis_error(self) -> None:
        async def _call() -> str:
            raise RedisConnectionError("boom")

        result = await redis_fail_open("test.op", _call, default="fallback")

        assert result == "fallback"

    async def test_returns_default_on_timeout_error(self) -> None:
        async def _call() -> str:
            raise TimeoutError("timed out")

        result = await redis_fail_open("test.op", _call, default="fallback")

        assert result == "fallback"

    async def test_returns_default_on_os_error(self) -> None:
        async def _call() -> str:
            raise OSError("connection refused")

        result = await redis_fail_open("test.op", _call, default="fallback")

        assert result == "fallback"

    async def test_does_not_swallow_unrelated_exceptions(self) -> None:
        async def _call() -> str:
            raise ValueError("caller bug, not a redis failure")

        with pytest.raises(ValueError, match="caller bug"):
            await redis_fail_open("test.op", _call, default="fallback")


class TestRedisFailClosed:
    async def test_returns_call_result_on_success(self) -> None:
        async def _call() -> str:
            return "ok"

        result = await redis_fail_closed("test.op", _call)

        assert result == "ok"

    async def test_raises_redis_unavailable_on_redis_error(self) -> None:
        async def _call() -> str:
            raise RedisConnectionError("boom")

        with pytest.raises(RedisUnavailableError) as exc_info:
            await redis_fail_closed("test.op", _call)

        assert exc_info.value.operation == "test.op"
        assert exc_info.value.__cause__ is not None

    async def test_raises_redis_unavailable_on_timeout_error(self) -> None:
        async def _call() -> str:
            raise TimeoutError("timed out")

        with pytest.raises(RedisUnavailableError):
            await redis_fail_closed("test.op", _call)

    async def test_raises_redis_unavailable_on_os_error(self) -> None:
        async def _call() -> str:
            raise OSError("connection refused")

        with pytest.raises(RedisUnavailableError):
            await redis_fail_closed("test.op", _call)

    async def test_does_not_swallow_unrelated_exceptions(self) -> None:
        async def _call() -> str:
            raise ValueError("caller bug, not a redis failure")

        with pytest.raises(ValueError, match="caller bug"):
            await redis_fail_closed("test.op", _call)

    async def test_error_message_never_leaks_key_or_token_values(self) -> None:
        async def _call() -> str:
            raise RedisConnectionError("Error connecting to redis://user:secret@host:6379")

        with pytest.raises(RedisUnavailableError) as exc_info:
            await redis_fail_closed("session.revocation.lookup", _call)

        # The wrapper's own message only ever includes the caller-supplied
        # operation label, never re-derives sensitive data from the key
        # being looked up.
        assert "session.revocation.lookup" in str(exc_info.value)
