"""Session-revocation check: Redis hot-path cache + Postgres fallback (ADR-0006).

This is the O(1) check `require_auth` (`app.core.deps`) re-runs on **every**
protected request: "is this `sid` still an active, non-expired session?"

Design (per the frozen database design's T10 slice):

- The Redis cache (`app.core.redis_keys.session_revocation_key`) stores
  only the **session-level** verdict (`revoked_at IS NULL AND expires_at >
  now()`) — it deliberately does **not** fold in `users.is_active`.
  `is_active` is a per-user, not per-session, fact and revoking/deactivating
  a user does not necessarily know every cached `sid` to invalidate; per
  the design note "the auth dependency must re-check is_active every
  request", `app.core.deps.require_auth` always re-reads `users.is_active`
  directly from Postgres, uncached, so a deactivation takes effect on the
  very next request without needing a cache-busting step here.
- On a cache **hit**, the cached verdict is trusted directly (no Postgres
  round-trip) — the hot path.
- On a cache **miss** (cold cache) or a Redis failure, this module falls
  back to a direct Postgres read via `sessions.id` (the primary key —
  `ix_sessions_user_active` serves the *list-by-user* path in
  `app.services.sessions`, not this by-id lookup) and repopulates the
  cache so the next request is a hit again.
- `revoke_session` (`app.services.sessions`) does not touch this cache, so
  callers that revoke a session must call `invalidate_session_cache`
  immediately afterward — this is what makes "a revoked sid fails within
  one request" true without waiting for the TTL to lapse.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_fail_modes import RedisUnavailableError, redis_fail_closed, redis_fail_open
from app.core.redis_keys import session_revocation_key
from app.models.session import Session

logger = logging.getLogger(__name__)

_CACHE_VALUE_ACTIVE = "active"
_CACHE_VALUE_REVOKED = "revoked"


async def _read_session_active_from_db(db: AsyncSession, session_id: UUID) -> bool:
    """Postgres fallback: the durable source of truth (ADR-0006).

    A missing session row (e.g. a forged/garbage `sid`) is treated as
    inactive, not an error.
    """

    session = await db.get(Session, session_id)
    if session is None:
        return False

    now = datetime.now(UTC)
    return session.revoked_at is None and session.expires_at > now


async def is_session_active(
    redis: Redis,
    db: AsyncSession,
    *,
    session_id: UUID,
    cache_ttl_seconds: int,
) -> bool:
    """Return True iff `session_id` is not revoked and not expired.

    Hot path: a Redis cache hit answers directly. Cold cache or a Redis
    outage both fall back to Postgres (`_read_session_active_from_db`),
    preserving correctness at the cost of latency (ADR-0006) — this
    function never guesses "active" just because Redis is unreachable.
    """

    key = session_revocation_key(session_id)

    async def _read() -> str | None:
        # The client is always constructed with `decode_responses=True`
        # (`app.db.redis.build_client_kwargs`), so this is a `str` at
        # runtime; the stub's broader `bytes | str | None` return type is
        # narrowed here rather than weakening this function's signature.
        value = await redis.get(key)
        return value if value is None else str(value)

    try:
        cached = await redis_fail_closed(f"session_revocation.read:{session_id}", _read)
    except RedisUnavailableError:
        logger.warning(
            "session revocation cache unavailable; falling back to postgres",
            extra={"session_id": str(session_id)},
        )
        return await _read_session_active_from_db(db, session_id)

    if cached is not None:
        return cached == _CACHE_VALUE_ACTIVE

    # Cold cache: recompute from Postgres and repopulate, fail-open on the
    # repopulate write (a failed cache write must not fail the request —
    # the caller already has a correct, freshly computed answer).
    active = await _read_session_active_from_db(db, session_id)
    await _write_cache(redis, session_id, active, cache_ttl_seconds=cache_ttl_seconds)
    return active


async def _write_cache(
    redis: Redis, session_id: UUID, active: bool, *, cache_ttl_seconds: int
) -> None:
    key = session_revocation_key(session_id)
    value = _CACHE_VALUE_ACTIVE if active else _CACHE_VALUE_REVOKED

    async def _write() -> None:
        await redis.set(key, value, ex=cache_ttl_seconds)

    await redis_fail_open(f"session_revocation.write:{session_id}", _write, default=None)


async def invalidate_session_cache(redis: Redis, session_id: UUID) -> None:
    """Evict the cached verdict for `session_id`.

    Must be called immediately after any operation that flips a session
    from active to revoked (`app.services.sessions.revoke_session`), so a
    concurrent or subsequent request on *this* instance re-derives the
    now-revoked state from Postgres rather than serving a stale "active"
    hit for up to `cache_ttl_seconds`. Fails open: if Redis is down, the
    Postgres row is already the source of truth and the next cold-cache
    lookup will read it correctly anyway.
    """

    key = session_revocation_key(session_id)

    async def _delete() -> None:
        await redis.delete(key)

    await redis_fail_open(f"session_revocation.invalidate:{session_id}", _delete, default=None)
