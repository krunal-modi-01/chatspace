"""Fail-open vs. fail-closed wrappers around a Redis operation.

Redis is a single-instance SPOF at chatspace's scale (CLAUDE.md
ARCHITECTURE NOTES; technical spec §Risks "Redis down/slow"), and it is
load-bearing for four unrelated things at once: pub/sub fan-out,
presence, rate limiting, and session-revocation caching. When Redis is
down or slow, each role needs a **different** answer to "what happens to
the caller":

- **Fail-open** (`redis_fail_open`) — on Redis error/timeout, return a
  caller-supplied default and let the operation proceed as if Redis had
  said "no problem here". Appropriate where availability matters more
  than the guarantee Redis would have enforced, and Postgres or best-effort
  degradation is an acceptable fallback:
    - **Pub/sub publish** — a failed publish only delays live delivery;
      the message is already durably persisted and reconnect catch-up
      recovers it (ADR-0004). Fail open (swallow, log, move on).
    - **Presence** — if Redis is down, presence goes stale/unavailable,
      but "no user falsely shows online" and durable `last_seen` in
      Postgres is unaffected (spec §Risks). Fail open to "unknown/offline"
      rather than blocking the request that triggered the presence update.
    - **Rate limiting** — the spec explicitly prefers **fail-closed on
      abuse-sensitive endpoints where feasible** (see `redis_fail_closed`
      below) but allows degrading gracefully otherwise; callers choose per
      endpoint class. A non-abuse-sensitive limiter check may fail open to
      avoid an outage turning into a full service denial.

- **Fail-closed** (`redis_fail_closed`) — on Redis error/timeout, treat the
  operation as failed/denied rather than guessing a permissive default.
  Appropriate where the Redis-backed check is a security control and a
  wrong guess would be unsafe:
    - **Session-revocation cache** — ADR-0006: correctness must be
      preserved even if Redis is unreachable. Callers should not treat a
      Redis outage on the *cache* as "not revoked" — the documented
      fallback is to re-check Postgres (the durable source of truth), not
      to fail open and honor a potentially-revoked session. This module
      does not implement that Postgres fallback (out of T05 scope); it
      only ensures a Redis outage surfaces as a explicit failure the
      caller must handle, instead of silently returning a permissive
      default.
    - **Auth rate limiting** — per spec line 39/§Risks, abuse-sensitive
      endpoints (login, password reset) should fail closed (reject /
      `429`) when the limiter itself is unavailable, to avoid opening a
      brute-force window during a Redis outage.

Both wrappers catch `redis.exceptions.RedisError` (the base class for
every Redis client exception, including connection/timeout errors) plus
`TimeoutError`/`OSError` for transport-level failures the client may not
wrap. They deliberately do **not** catch arbitrary exceptions, so a bug
in the wrapped callable's own logic still propagates.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

# Transport-level failures the redis-py client does not always wrap in a
# `RedisError` subclass (e.g. a bare socket timeout/connection reset).
_TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (RedisError, TimeoutError, OSError)


class RedisUnavailableError(Exception):
    """Raised by `redis_fail_closed` when Redis is unreachable/erroring.

    Wraps the underlying transport error so callers can log/handle it
    without needing to know redis-py's specific exception hierarchy.
    """

    def __init__(self, operation: str, cause: BaseException) -> None:
        super().__init__(f"Redis unavailable during {operation!r}: {cause}")
        self.operation = operation
        self.__cause__ = cause


async def redis_fail_open[T](
    operation: str,
    call: Callable[[], Awaitable[T]],
    *,
    default: T,
) -> T:
    """Run `call`; on Redis failure, log and return `default` instead of raising.

    Use for roles where availability outranks correctness of the
    Redis-backed check (pub/sub publish, presence, non-abuse-sensitive
    rate limits) — see module docstring for the per-role rationale.

    `operation` is a short, non-sensitive label (e.g. "presence.incr")
    used only in the log line — never include key values, tokens, or
    message content here (CLAUDE.md: no PII/secrets in logs).
    """

    try:
        return await call()
    except _TRANSPORT_ERRORS as exc:
        logger.warning(
            "redis operation failed; failing open",
            extra={"redis_operation": operation, "fail_mode": "open"},
            exc_info=False,
        )
        _ = exc
        return default


async def redis_fail_closed[T](
    operation: str,
    call: Callable[[], Awaitable[T]],
) -> T:
    """Run `call`; on Redis failure, log and raise `RedisUnavailableError`.

    Use for roles where a permissive guess would be unsafe (session
    revocation checks, abuse-sensitive rate limits) — see module docstring
    for the per-role rationale. Callers are expected to catch
    `RedisUnavailableError` and apply their own documented fallback (e.g.
    the revocation check falling back to Postgres per ADR-0006), not to
    let it become an unhandled 500 by default.

    `operation` is a short, non-sensitive label used only in the log line
    — never include key values, tokens, or message content here.
    """

    try:
        return await call()
    except _TRANSPORT_ERRORS as exc:
        logger.warning(
            "redis operation failed; failing closed",
            extra={"redis_operation": operation, "fail_mode": "closed"},
            exc_info=False,
        )
        raise RedisUnavailableError(operation, exc) from exc
