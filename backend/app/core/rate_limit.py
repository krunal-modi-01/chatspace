"""Redis token-bucket rate limiter (T27, spec line 39, F62-F64).

Enforces the three Redis-backed, per-subject rate limits the frozen
contract requires. This is distinct from the connection-local WS
frame-rate guard (`app.ws.rate_limit`, T23) — see that module's
docstring for why the two are independent and both may apply.

## Scopes (`app.core.redis_keys.RateLimitScope`)

- `MESSAGE_SEND` — 10 tokens / 10s, burst (capacity) 20, per **user**.
  Applies to `POST /v1/channels/{channel_id}/messages` and
  `POST /v1/dms/{user_id}/messages`.
- `AUTH` — 5 tokens / 5 min, per **IP + attempted identifier**,
  non-enumerating. Applies to `POST /v1/auth/login`, `/register`,
  `/refresh`, and `/password-reset` (the *request*, not `/confirm`).
- `MEDIA_UPLOAD` — 20 tokens / min, per **user**. A **hook point only**
  in T27 — `POST /v1/media` itself lands in T28; nothing calls this scope
  from a live route yet.

## Algorithm

A classic token bucket, implemented as a single atomic Lua script
(`EVAL`/`EVALSHA` via `redis.asyncio.Redis.register_script`, which
transparently handles the SHA-cache/`NOSCRIPT` fallback) so the
read-refill-consume-write sequence never races across concurrent
requests hitting the same bucket key, including across the two FastAPI
instances chatspace runs at this scale sharing one Redis (CLAUDE.md
ARCHITECTURE NOTES).

"Now" is supplied by the calling application server's own wall clock
(`time.time()`), not `redis.call('TIME')` from inside the script. At
chatspace's 1-2 instance scale, clock skew between them is negligible;
using the caller's clock instead of Redis's own keeps the limiter
trivially unit-testable (a caller can inject a fixed `now` and assert
exact refill behavior) without depending on Redis's own time/debug
primitives.

## Fail-open vs. fail-closed

Per-scope Redis-outage behavior is the *caller's* choice via
`enforce_rate_limit(..., fail_closed=...)`, layered on top of
`app.core.redis_fail_modes`:

- `fail_closed=True` (message-send, auth): a Redis error/timeout raises
  `RateLimitUnavailableError` rather than guessing permissive — an outage
  must never open a spam/brute-force window on an abuse-sensitive
  endpoint (task T27; CLAUDE.md "required even at small scale").
- `fail_closed=False` (media-upload hook point): a Redis error/timeout
  degrades to "allowed" (`RateLimitDecision(allowed=True, ...)`) — this
  scope is not abuse-sensitive enough to justify blocking every request
  during an outage.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from redis.asyncio import Redis

from app.core.redis_fail_modes import RedisUnavailableError, redis_fail_closed, redis_fail_open
from app.core.redis_keys import RateLimitScope, rate_limit_bucket_key
from app.core.token_hash import hash_rate_limit_identifier

logger = logging.getLogger(__name__)

# KEYS[1] = bucket key (`app.core.redis_keys.rate_limit_bucket_key`)
# ARGV[1] = capacity (max tokens the bucket can hold / burst size)
# ARGV[2] = refill_rate_per_second (tokens regenerated per elapsed second)
# ARGV[3] = now (float seconds, caller-supplied wall clock — see module docstring)
# ARGV[4] = requested tokens for this call (always 1 for a single request)
# ARGV[5] = key TTL seconds (so an idle bucket eventually expires)
#
# Stored as a Redis hash `{tokens, ts}`; a missing/cold key is treated as
# a full bucket at `now` (a brand-new subject starts with a full burst
# allowance, not an empty one). Runs entirely inside Redis so the
# read-refill-consume-write sequence is atomic under concurrent callers.
_TOKEN_BUCKET_SCRIPT = """
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])

local bucket = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(bucket[1])
local ts = tonumber(bucket[2])

if tokens == nil or ts == nil then
  tokens = capacity
  ts = now
end

local elapsed = now - ts
if elapsed < 0 then
  elapsed = 0
end

tokens = math.min(capacity, tokens + (elapsed * refill_rate))

local allowed = 0
local retry_after = 0

if tokens >= requested then
  allowed = 1
  tokens = tokens - requested
else
  local deficit = requested - tokens
  if refill_rate > 0 then
    retry_after = math.ceil(deficit / refill_rate)
  else
    retry_after = -1
  end
end

redis.call('HSET', KEYS[1], 'tokens', tostring(tokens), 'ts', tostring(now))
redis.call('EXPIRE', KEYS[1], ttl)

return {allowed, retry_after}
"""


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    """One scope's token-bucket parameters (frozen contract, spec line 39)."""

    capacity: int
    refill_rate_per_second: float
    # Idle-bucket TTL: comfortably longer than the time to fully refill
    # from empty, so a bucket never expires mid-throttle for a caller
    # actively being rate-limited, while still not accumulating Redis
    # keys forever for callers who stop entirely.
    ttl_seconds: int


_POLICIES: dict[RateLimitScope, RateLimitPolicy] = {
    # 10 tokens / 10s, burst (capacity) 20.
    RateLimitScope.MESSAGE_SEND: RateLimitPolicy(
        capacity=20, refill_rate_per_second=10 / 10, ttl_seconds=60
    ),
    # 5 / 5 min (300s); the contract documents no separate burst for this
    # scope, so capacity equals the steady-state limit itself.
    RateLimitScope.AUTH: RateLimitPolicy(
        capacity=5, refill_rate_per_second=5 / 300, ttl_seconds=600
    ),
    # 20 / min (60s). Hook point only — no live route calls this scope
    # until T28 wires up `POST /v1/media`.
    RateLimitScope.MEDIA_UPLOAD: RateLimitPolicy(
        capacity=20, refill_rate_per_second=20 / 60, ttl_seconds=120
    ),
    # 60 / min (60s), burst (capacity) 60 — a general authenticated-read
    # policy (T73, `GET /v1/users/search`). No specific number is pinned
    # by the functional/technical spec for this class (unlike
    # MESSAGE_SEND/AUTH/MEDIA_UPLOAD, which the contract enumerates
    # exactly); this is a conservative ceiling generous enough for normal
    # member-/DM-picker typeahead use (a few requests per keystroke) while
    # still bounding a single caller's repeated-seq-scan cost against the
    # ~1,000-row `users` table (constitution #7).
    RateLimitScope.GENERAL_READ: RateLimitPolicy(
        capacity=60, refill_rate_per_second=60 / 60, ttl_seconds=120
    ),
}


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """The token-bucket verdict for one request against one scope+subject."""

    allowed: bool
    # Seconds the caller should wait before retrying; always 0 when
    # `allowed` is True.
    retry_after_seconds: int


class RateLimitExceededError(Exception):
    """Raised when a bucket has no tokens left for the requested consumption.

    Carries `retry_after_seconds` for the frozen contract's `Retry-After`
    header (spec line 39: "Over-limit responses are 429 ... with a
    Retry-After header"). `app.core.errors.rate_limit_exceeded_handler`
    renders the `429` problem+json envelope.
    """

    def __init__(self, retry_after_seconds: int) -> None:
        # Always at least 1: a caller told to retry "after 0 seconds"
        # would just hammer the endpoint again immediately.
        self.retry_after_seconds = max(1, retry_after_seconds)
        super().__init__("Rate limit exceeded.")


class RateLimitUnavailableError(Exception):
    """Raised when a fail-closed rate-limit check could not reach Redis.

    Distinct from `RateLimitExceededError`: this is an infra outage on
    the check itself, not an actual over-limit verdict.
    `app.core.errors.rate_limit_unavailable_handler` renders this as a
    `503` + short fixed `Retry-After`, per task T27's "fail-closed
    (reject) on abuse-sensitive endpoints ... when Redis is unavailable".
    """


async def _consume(
    redis: Redis,
    *,
    key: str,
    policy: RateLimitPolicy,
    now: float,
    requested: int = 1,
) -> RateLimitDecision:
    script = redis.register_script(_TOKEN_BUCKET_SCRIPT)
    allowed_raw, retry_after_raw = await script(
        keys=[key],
        args=[policy.capacity, policy.refill_rate_per_second, now, requested, policy.ttl_seconds],
    )
    return RateLimitDecision(
        allowed=bool(int(allowed_raw)),
        retry_after_seconds=max(0, int(retry_after_raw)),
    )


async def check_rate_limit(
    redis: Redis,
    *,
    scope: RateLimitScope,
    subject: str,
    now: float | None = None,
) -> RateLimitDecision:
    """Consume one token from `scope`'s bucket for `subject`.

    `subject` is caller-supplied per `app.core.redis_keys
    .rate_limit_bucket_key`'s documented per-scope keying: a user id for
    `MESSAGE_SEND`/`MEDIA_UPLOAD`, or the pre-composed non-enumerating
    `"{ip}:{hashed identifier}"` string `auth_rate_limit_subject` builds
    for `AUTH`. `now` defaults to the real wall clock; tests may inject an
    explicit value to assert refill behavior deterministically without
    waiting real time.
    """

    policy = _POLICIES[scope]
    key = rate_limit_bucket_key(scope, subject)
    current_time = now if now is not None else time.time()
    return await _consume(redis, key=key, policy=policy, now=current_time)


async def enforce_rate_limit(
    redis: Redis,
    *,
    scope: RateLimitScope,
    subject: str,
    fail_closed: bool,
    now: float | None = None,
) -> RateLimitDecision:
    """Run `check_rate_limit`, applying the scope's Redis-outage policy.

    See the module docstring's "Fail-open vs. fail-closed" section.
    Raises `RateLimitUnavailableError` only when `fail_closed=True` and
    Redis is unreachable/erroring; otherwise always returns a decision
    (never raises for an ordinary over-limit verdict — callers check
    `.allowed` themselves and raise `RateLimitExceededError`).
    """

    operation = f"rate_limit.{scope.value}"

    async def _check() -> RateLimitDecision:
        return await check_rate_limit(redis, scope=scope, subject=subject, now=now)

    if fail_closed:
        try:
            return await redis_fail_closed(operation, _check)
        except RedisUnavailableError as exc:
            raise RateLimitUnavailableError(str(exc)) from exc

    return await redis_fail_open(
        operation, _check, default=RateLimitDecision(allowed=True, retry_after_seconds=0)
    )


def auth_rate_limit_subject(*, client_ip: str, identifier: str) -> str:
    """Build the non-enumerating composite subject for `RateLimitScope.AUTH`.

    Always the same shape regardless of whether `identifier` (an email,
    invite token, or refresh token — whichever credential the specific
    auth endpoint attempts against) turns out to be valid: this is a pure
    function that never looks anything up, so the bucket key can never
    differ based on account/token existence (F11/F15/F64,
    "non-enumerating"). Callers must call this — and the resulting
    `enforce_rate_limit` — *before* any DB lookup of `identifier`.

    `identifier` is hashed (`app.core.token_hash.hash_rate_limit_identifier`)
    rather than embedded verbatim: an email/refresh-token/invite-token is
    sensitive (PII or a bearer secret), and the raw client IP alongside a
    hashed identifier keeps the key legible for operational debugging
    (which IP is being throttled) without putting a secret/PII value in
    the Redis keyspace in the clear.
    """

    return f"{client_ip}:{hash_rate_limit_identifier(identifier)}"
