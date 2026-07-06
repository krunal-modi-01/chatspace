"""AsyncSession lifecycle: engine cache, sessionmaker, and FastAPI dependency.

The engine is a process-wide singleton (cached, like `get_settings`) so the
connection pool is created once per instance, not once per request — the
whole point of pooling. Tests reset the cache the same way they reset
`get_settings.cache_clear()` (see `tests/conftest.py`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.engine import create_engine


@lru_cache
def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, creating it on first access.

    Cached for the same reason `get_settings` is: constructing the engine
    is cheap and non-blocking (no connection is opened at construction
    time), but it must be a singleton so every request shares the one
    bounded pool rather than each request spinning up its own.
    """

    return create_engine(get_settings())


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide `AsyncSession` factory."""

    return async_sessionmaker(
        bind=get_engine(),
        expire_on_commit=False,
        autoflush=False,
    )


async def dispose_engine() -> None:
    """Dispose the pooled engine and clear the caches.

    Called on application shutdown and by tests between cases, so a fresh
    engine (bound to whatever `DATABASE_URL` is current) is built next
    time `get_engine()` is called.
    """

    # `get_engine.cache_info().currsize` avoids constructing an engine just
    # to dispose one that was never built (e.g. a unit test that never
    # touched the DB layer).
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped `AsyncSession`.

    Commits on clean exit, rolls back on any exception (so a raised
    `HTTPException` from a route never leaves a half-written transaction
    committed), and always closes the session to return its connection to
    the pool.
    """

    session_factory = get_sessionmaker()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
