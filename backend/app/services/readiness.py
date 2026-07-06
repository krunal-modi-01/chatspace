"""Readiness probes for downstream dependencies.

The Postgres probe (T03) runs a real `SELECT 1` against the async
SQLAlchemy engine, bounded by an explicit timeout so an unreachable or
wedged Postgres fails the probe fast rather than hanging the request
(technical spec §Risks: "the app returns fast errors rather than
hanging"). The Redis probe (T05) runs a real `PING` against the shared
async client the same way: Redis being down must *degrade* the readyz
response (503, `unavailable`) rather than crash the process — per the
"Redis down/slow" failure mode in the technical spec, live delivery,
presence, and rate limiting degrade while REST/history keep working from
Postgres.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import StrEnum

from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.db.redis import get_redis_client
from app.db.session import get_engine

logger = logging.getLogger(__name__)


class ReadinessStatus(StrEnum):
    OK = "ok"
    STUBBED = "stubbed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ReadinessCheck:
    name: str
    status: ReadinessStatus
    detail: str


async def check_database() -> ReadinessCheck:
    """Probe Postgres reachability with a bounded `SELECT 1`.

    The engine's own `db_connect_timeout_seconds` already bounds new
    connection attempts; `asyncio.wait_for` adds a second, outer bound
    (using the same setting) so a pooled-but-wedged connection — or any
    other unexpected stall — cannot hang the readyz probe either.

    Never includes the connection string or driver-level exception text
    in the returned detail — only a generic, non-sensitive message —
    since this response is not authenticated and must not leak
    infrastructure internals.
    """

    settings = get_settings()
    timeout = settings.db_connect_timeout_seconds

    try:
        engine = get_engine()

        async def _probe() -> None:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))

        await asyncio.wait_for(_probe(), timeout=timeout)
    except TimeoutError:
        logger.warning("readyz database probe timed out", extra={"timeout_seconds": timeout})
        return ReadinessCheck(
            name="database",
            status=ReadinessStatus.UNAVAILABLE,
            detail="Postgres did not respond within the probe timeout.",
        )
    except (SQLAlchemyError, OSError):
        # `OSError` also covers driver-level failures SQLAlchemy does not
        # wrap, e.g. asyncpg raising a bare `ConnectionRefusedError` when
        # the host is up but the Postgres port is closed, or
        # `socket.gaierror` on DNS failure. Without this, those outcomes
        # escape as an unhandled exception (500) instead of the documented
        # 503 readiness response.
        logger.warning("readyz database probe failed", exc_info=False)
        return ReadinessCheck(
            name="database",
            status=ReadinessStatus.UNAVAILABLE,
            detail="Postgres is unreachable.",
        )

    return ReadinessCheck(
        name="database",
        status=ReadinessStatus.OK,
        detail="Postgres reachable.",
    )


async def check_redis() -> ReadinessCheck:
    """Probe Redis reachability with a bounded `PING`.

    Mirrors `check_database`'s "fail fast, don't hang" posture: an outer
    `asyncio.wait_for` bounds the probe so an unreachable or wedged Redis
    reports `unavailable` promptly rather than hanging the `/v1/readyz`
    request. Redis being unavailable degrades this readiness check only —
    it must never crash the process (technical spec §Risks "Redis
    down/slow": live delivery/presence/rate-limiting degrade, REST/history
    keep working from Postgres).

    Never includes the connection string or driver-level exception text
    in the returned detail, for the same reason as `check_database`: this
    response is unauthenticated and must not leak infrastructure
    internals.
    """

    settings = get_settings()
    timeout = settings.redis_connect_timeout_seconds

    try:
        client = get_redis_client()
        await asyncio.wait_for(client.ping(), timeout=timeout)
    except TimeoutError:
        logger.warning("readyz redis probe timed out", extra={"timeout_seconds": timeout})
        return ReadinessCheck(
            name="redis",
            status=ReadinessStatus.UNAVAILABLE,
            detail="Redis did not respond within the probe timeout.",
        )
    except (RedisError, OSError):
        # `OSError` covers transport-level failures redis-py does not
        # always wrap (e.g. a bare `ConnectionRefusedError`/DNS failure),
        # matching the equivalent branch in `check_database`.
        logger.warning("readyz redis probe failed", exc_info=False)
        return ReadinessCheck(
            name="redis",
            status=ReadinessStatus.UNAVAILABLE,
            detail="Redis is unreachable.",
        )

    return ReadinessCheck(
        name="redis",
        status=ReadinessStatus.OK,
        detail="Redis reachable.",
    )
