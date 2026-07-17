from __future__ import annotations

import socket
from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest
from redis.asyncio import Redis

from app.db.redis import (
    build_client_kwargs,
    create_redis_client,
    dispose_redis_client,
    get_redis_client,
)

if TYPE_CHECKING:
    from app.core.config import Settings


def _find_closed_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(autouse=True)
def _reset_redis_cache() -> Iterator[None]:
    """Ensure each test starts with no cached settings/client from a prior test."""

    from app.core.config import get_settings

    get_settings.cache_clear()
    get_redis_client.cache_clear()
    yield
    get_settings.cache_clear()
    get_redis_client.cache_clear()


def _build_settings(**overrides: object) -> Settings:
    from app.core.config import Settings

    defaults: dict[str, object] = {
        "database_url": "postgresql+asyncpg://user:pass@240.0.0.1:5432/does-not-exist",
        "redis_url": "redis://localhost:6380/1",
        "jwt_signing_key": "test",
        "smtp_host": "localhost",
        "smtp_port": 1025,
        "smtp_username": "test",
        "smtp_password": "test",
        "smtp_from_address": "no-reply@chatspace.example",
        "s3_endpoint_url": "http://localhost:9000",
        "s3_bucket_name": "bucket",
        "s3_access_key_id": "key",
        "s3_secret_access_key": "secret",
        "bootstrap_admin_email": "admin@chatspace.example",
        "bootstrap_admin_password": "pw",
        "bootstrap_admin_username": "admin",
        "bootstrap_admin_first_name": "System",
        "bootstrap_admin_last_name": "Admin",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


class TestClientConfiguration:
    def test_kwargs_decode_responses_and_timeouts(self) -> None:
        settings = _build_settings()

        kwargs = build_client_kwargs(settings)

        assert kwargs["decode_responses"] is True
        assert kwargs["socket_connect_timeout"] > 0
        assert kwargs["socket_timeout"] > 0

    def test_creating_client_does_not_connect(self) -> None:
        """Constructing the client must never block on a live connection.

        `Redis.from_url` is lazy, mirroring `create_async_engine` — this
        must succeed even with an unreachable host, proving client
        construction alone can't hang application startup.
        """

        settings = _build_settings(redis_url="redis://240.0.0.1:6379/0")

        client = create_redis_client(settings)

        assert isinstance(client, Redis)


class TestGetRedisClientCaching:
    def test_returns_the_same_instance_across_calls(self, configured_env: None) -> None:
        first = get_redis_client()
        second = get_redis_client()

        assert first is second

    async def test_dispose_clears_the_cache(self, configured_env: None) -> None:
        first = get_redis_client()

        await dispose_redis_client()

        second = get_redis_client()
        assert first is not second

    async def test_dispose_is_a_noop_when_never_constructed(self, configured_env: None) -> None:
        # No prior `get_redis_client()` call in this test — must not raise
        # or construct a client just to dispose it.
        await dispose_redis_client()


class TestClientAgainstRealRedis:
    async def test_ping_succeeds_against_local_redis(
        self, configured_env: None, redis_available: bool
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        client = get_redis_client()
        assert await client.ping() is True

        await dispose_redis_client()

    async def test_ping_raises_fast_against_unreachable_redis(
        self, monkeypatch: pytest.MonkeyPatch, configured_env: None
    ) -> None:
        from redis.exceptions import RedisError

        closed_port = _find_closed_port()
        monkeypatch.setenv("REDIS_URL", f"redis://127.0.0.1:{closed_port}/0")

        from app.core.config import get_settings

        get_settings.cache_clear()
        get_redis_client.cache_clear()

        client = get_redis_client()
        with pytest.raises((RedisError, OSError)):
            await client.ping()

        await dispose_redis_client()
