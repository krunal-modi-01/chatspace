"""Async SQLAlchemy engine over `asyncpg`.

One engine (and its bounded connection pool) is created per process — not
per request — per the technical spec's "asyncpg connection pooling per
instance" design and CLAUDE.md's 1,000-user scale guidance (no PgBouncer,
no sharding). Pool size and the Postgres `statement_timeout` are entirely
config-driven (`Settings`), so operators can tune them per-environment
without a code change.

Two timeouts are deliberately layered so a failure surfaces fast instead
of a request hanging (technical spec §Risks, "PostgreSQL down/slow"):

- `db_connect_timeout_seconds` bounds how long asyncpg will wait to
  *establish* a TCP/handshake connection (covers "Postgres unreachable").
- `db_statement_timeout_ms` is set as a Postgres session GUC on every new
  connection via `asyncpg`'s `server_settings`, bounding how long any one
  *statement* may run once connected (covers "Postgres slow").
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import Settings


def build_engine_kwargs(settings: Settings) -> dict[str, object]:
    """Compute the `create_async_engine` kwargs from settings.

    Split out from `create_engine` so tests can assert the pool/timeout
    wiring without instantiating a real engine (which would require a
    valid URL and, on `.dispose()`, may touch the network).
    """

    return {
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_timeout": settings.db_pool_timeout_seconds,
        # Recycle idle pooled connections periodically so long-lived
        # connections don't outlive a Postgres-side idle/firewall timeout
        # and surface as a mysterious mid-request disconnect.
        "pool_recycle": 1800,
        # Fail fast on a stale pooled connection rather than handing the
        # caller a broken socket.
        "pool_pre_ping": True,
        "connect_args": {
            "timeout": settings.db_connect_timeout_seconds,
            "server_settings": {
                "statement_timeout": str(settings.db_statement_timeout_ms),
                # Force UTC on every connection — all persisted timestamps
                # are `timestamptz` per the database design; interpreting
                # them in a non-UTC session timezone would be a silent
                # correctness bug.
                "timezone": "UTC",
            },
        },
    }


def create_engine(settings: Settings) -> AsyncEngine:
    """Create the process-wide async engine from settings.

    Callers own the returned engine's lifecycle (`await engine.dispose()`
    on shutdown). `create_async_engine` itself does not open a connection
    — the pool is populated lazily on first use — so constructing this at
    startup cannot itself hang even if Postgres is unreachable.
    """

    return create_async_engine(
        settings.database_url.get_secret_value(),
        **build_engine_kwargs(settings),
    )
