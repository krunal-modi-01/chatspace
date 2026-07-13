"""Route-facing wiring of `app.core.rate_limit` (T27).

Three consumers of the token-bucket engine:

- `enforce_message_send_rate_limit` — a `Depends()` target for the two
  message-send routes (`app.api.messages`): `RateLimitScope.MESSAGE_SEND`,
  keyed per authenticated user, fail-closed on a Redis outage.
- `enforce_media_upload_rate_limit` — a `Depends()` target for
  `RateLimitScope.MEDIA_UPLOAD`, keyed per authenticated user, fail-open
  on a Redis outage. Wired to `POST /v1/media` (T28, `app.api.media`) via
  `Depends(enforce_media_upload_rate_limit)` on that route.
- `enforce_auth_rate_limit` — a plain async helper (not a bare
  `Depends()`) for `RateLimitScope.AUTH`. Every auth route it applies to
  (`app.api.auth`'s `login`/`register`/`refresh`, `app.api.password`'s
  `request_password_reset`) parses its own raw JSON body manually
  (`app.core.request_body`) to get at the "attempted identifier" the
  composite key needs, so it cannot be a bare parameter-level dependency
  — each route calls this explicitly right after a successful body parse
  and before any account/token lookup, preserving F11/F15/F64's
  non-enumeration guarantee (the rate-limit check never varies by
  identifier validity) and, for password-reset specifically, the existing
  timing-attack mitigation documented in `app.api.password` (this
  function does the same Redis round-trip regardless of whether
  `identifier` matches a real account).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.core.client_ip import extract_client_ip
from app.core.deps import AuthenticatedUser, require_auth
from app.core.rate_limit import (
    RateLimitExceededError,
    auth_rate_limit_subject,
    enforce_rate_limit,
)
from app.core.redis_keys import RateLimitScope
from app.db.redis import get_redis_client

_CurrentUser = Annotated[AuthenticatedUser, Depends(require_auth)]

# Fallback subject-IP literal when the connecting host isn't a parseable
# IP (e.g. an unconventional proxy, or the test client's `"testclient"`
# host) — groups all such unparseable-IP callers into one shared bucket
# rather than dropping the IP half of the key entirely. In production,
# behind a real load balancer/TLS terminator, the connecting IP is always
# present; this only matters for local/dev/test ergonomics.
_UNKNOWN_CLIENT_IP = "unknown"


async def enforce_message_send_rate_limit(current: _CurrentUser) -> None:
    """`Depends()` target: per-user `RateLimitScope.MESSAGE_SEND` (10/10s, burst 20).

    Fail-closed: a Redis outage raises `RateLimitUnavailableError`
    (`app.core.errors` renders this as `503` + `Retry-After`) rather than
    letting message-send abuse through during an outage.
    """

    decision = await enforce_rate_limit(
        get_redis_client(),
        scope=RateLimitScope.MESSAGE_SEND,
        subject=str(current.user_id),
        fail_closed=True,
    )
    if not decision.allowed:
        raise RateLimitExceededError(decision.retry_after_seconds)


async def enforce_media_upload_rate_limit(current: _CurrentUser) -> None:
    """`Depends()` target: per-user `RateLimitScope.MEDIA_UPLOAD` (20/min).

    Wired to `POST /v1/media` (T28, `app.api.media`). Fail-open: a Redis
    outage degrades to "allowed" rather than blocking uploads, since this
    scope is not abuse-sensitive enough to justify a hard fail-closed like
    auth/message-send.
    """

    decision = await enforce_rate_limit(
        get_redis_client(),
        scope=RateLimitScope.MEDIA_UPLOAD,
        subject=str(current.user_id),
        fail_closed=False,
    )
    if not decision.allowed:
        raise RateLimitExceededError(decision.retry_after_seconds)


async def enforce_auth_rate_limit(request: Request, *, identifier: str) -> None:
    """Enforce `RateLimitScope.AUTH` (5/5min per IP + attempted identifier).

    Call *after* successfully parsing the request body (so `identifier`
    is available) and *before* any account/token lookup — the subject key
    is built by `app.core.rate_limit.auth_rate_limit_subject`, which never
    varies based on whether `identifier` turns out to be valid
    (F11/F15/F64, non-enumerating). Fail-closed: a Redis outage raises
    `RateLimitUnavailableError` (rendered `503` + `Retry-After`), matching
    every other abuse-sensitive scope in T27.
    """

    client_ip = extract_client_ip(request) or _UNKNOWN_CLIENT_IP
    subject = auth_rate_limit_subject(client_ip=client_ip, identifier=identifier)

    decision = await enforce_rate_limit(
        get_redis_client(),
        scope=RateLimitScope.AUTH,
        subject=subject,
        fail_closed=True,
    )
    if not decision.allowed:
        raise RateLimitExceededError(decision.retry_after_seconds)
