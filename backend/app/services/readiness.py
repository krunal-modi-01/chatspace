"""Readiness probes for downstream dependencies.

Per T01 scope, the Postgres and Redis probes are **stubbed**: no live
connection is attempted here. Real connectivity checks land with the DB
session (T03) and Redis client (T05) wiring, which will replace these
stub implementations without changing the `/v1/readyz` response shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


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
    """Stub Postgres readiness probe.

    TODO(T03): replace with a real `SELECT 1` against the async SQLAlchemy
    engine once the DB session module exists.
    """

    return ReadinessCheck(
        name="database",
        status=ReadinessStatus.STUBBED,
        detail="Postgres connectivity probe not yet wired (see T03).",
    )


async def check_redis() -> ReadinessCheck:
    """Stub Redis readiness probe.

    TODO(T05): replace with a real `PING` against the Redis client once
    the Redis integration module exists.
    """

    return ReadinessCheck(
        name="redis",
        status=ReadinessStatus.STUBBED,
        detail="Redis connectivity probe not yet wired (see T05).",
    )
