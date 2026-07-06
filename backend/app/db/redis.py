"""Async Redis client construction and process-wide lifecycle.

Mirrors `app.db.engine` / `app.db.session`: one client (and its bounded
connection pool) per process, constructed lazily and cached, disposed on
shutdown. `redis.asyncio.Redis.from_url` is lazy — like
`create_async_engine` — so building the client at import/startup time
never blocks even if Redis is unreachable; connections are opened on
first use.

This module is intentionally minimal (T05 scope): shared client + lifecycle
only. It does **not** implement pub/sub, presence, rate limiting, or
session-revocation population — those are separate consumers built on top
of `get_redis_client()` (see `app.core.redis_keys` for the namespaced key
helpers they use, and `app.core.redis_fail_modes` for the fail-open /
fail-closed wrappers they should apply around their own operations).
"""

from __future__ import annotations

from functools import lru_cache

from redis.asyncio import Redis

from app.core.config import Settings, get_settings

# Bounds how long a single Redis command may block before raising, so a
# wedged/unreachable Redis fails fast instead of piling up requests — the
# same "fail fast, don't hang" posture as the Postgres engine's connect /
# statement timeouts (see `app.db.engine`).
_SOCKET_CONNECT_TIMEOUT_SECONDS = 2.0
_SOCKET_TIMEOUT_SECONDS = 2.0


def build_client_kwargs(settings: Settings) -> dict[str, object]:
    """Compute the `Redis.from_url` kwargs from settings.

    Split out from `create_redis_client` so tests can assert the
    timeout/pool wiring without instantiating a real client (which, like
    `create_engine`, is cheap but should still be exercised in isolation).
    """

    return {
        "socket_connect_timeout": _SOCKET_CONNECT_TIMEOUT_SECONDS,
        "socket_timeout": _SOCKET_TIMEOUT_SECONDS,
        # Decode to `str` at the client boundary — every namespaced key and
        # value this codebase writes is text (ids, counters-as-strings,
        # JSON-encoded payloads), never raw bytes callers need to manage.
        "decode_responses": True,
        # Verify pooled connections are alive before handing them to a
        # caller, matching the Postgres engine's `pool_pre_ping=True`.
        "health_check_interval": 30,
    }


def create_redis_client(settings: Settings) -> Redis:
    """Create the process-wide async Redis client from settings.

    Callers own the returned client's lifecycle (`await client.aclose()`
    on shutdown). Construction does not open a connection — the
    connection pool is populated lazily on first command — so this cannot
    itself hang application startup even if Redis is unreachable.
    """

    return Redis.from_url(
        settings.redis_url.get_secret_value(),
        **build_client_kwargs(settings),  # type: ignore[arg-type]
    )


@lru_cache
def get_redis_client() -> Redis:
    """Return the process-wide async Redis client, creating it on first access.

    Cached for the same reason `get_engine` is: one shared connection pool
    per process, not one per request or per caller.
    """

    return create_redis_client(get_settings())


async def dispose_redis_client() -> None:
    """Close the pooled Redis client and clear the cache.

    Called on application shutdown and by tests between cases, so a fresh
    client (bound to whatever `REDIS_URL` is current) is built next time
    `get_redis_client()` is called.
    """

    if get_redis_client.cache_info().currsize:
        await get_redis_client().aclose()
    get_redis_client.cache_clear()
