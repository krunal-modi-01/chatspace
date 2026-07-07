"""`require_auth` — the FastAPI dependency every protected route depends on.

Per the frozen API contract (Conventions → Auth) and ADR-0006:

    Authorization: Bearer <access_token> ... on every protected route.
    Every authenticated REST request re-runs the session-revocation check
    (Redis-cached, Postgres-backed): a logged-out, password-changed,
    reset, or deactivated `sid` fails with 401 near-immediately.

This module owns exactly that: decode + verify the JWT (T09,
`app.core.jwt`), then re-run both halves of the revocation check on every
single call — session-level (`app.services.session_revocation`, Redis-cached
with Postgres fallback) and user-level (`users.is_active`, always read
fresh from Postgres, never cached — see `session_revocation`'s module
docstring for why). Any failure raises `HTTPException(401, ...)`, which
`app.core.errors.http_exception_handler` turns into the frozen
`problem+json` envelope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.jwt import ExpiredTokenError, InvalidTokenError, decode_access_token
from app.db.redis import get_redis_client
from app.db.session import get_db_session
from app.models.user import User
from app.services.session_revocation import is_session_active

# `auto_error=False` so a missing/malformed Authorization header is turned
# into the same 401 problem+json shape as every other auth failure here,
# rather than FastAPI's default (a bare 403 with a plain-text body) —
# the contract reserves 403 for authorization failures, not missing auth.
_bearer_scheme = HTTPBearer(auto_error=False)

_UNAUTHORIZED_DETAIL = "Authentication failed. Provide a valid access token."


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """The verified identity of the caller of a protected route."""

    user_id: UUID
    session_id: UUID


def _unauthorized() -> HTTPException:
    # A single, deliberately generic detail message for every failure mode
    # (missing header, malformed/expired/invalid token, revoked session,
    # deactivated user) — the contract's `401 | Auth | problem+json` line
    # does not distinguish sub-reasons on the wire, and a more specific
    # message per case would let a caller enumerate which of "no such
    # session" / "wrong signature" / "user deactivated" applies.
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_UNAUTHORIZED_DETAIL)


async def require_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthenticatedUser:
    """Verify the bearer access token and its session, or raise 401.

    Every call re-runs the full revocation check — there is no per-request
    caching *above* this dependency, so it is safe (and required) to
    depend on this from every protected route.
    """

    has_bearer_token = (
        credentials is not None
        and credentials.scheme.lower() == "bearer"
        and bool(credentials.credentials)
    )
    if not has_bearer_token:
        raise _unauthorized()
    assert credentials is not None  # narrowed by has_bearer_token for type-checkers

    try:
        payload = decode_access_token(credentials.credentials, settings=settings)
    except (ExpiredTokenError, InvalidTokenError):
        raise _unauthorized() from None

    try:
        user_id = UUID(payload.user_id)
        session_id = UUID(payload.session_id)
    except ValueError:
        raise _unauthorized() from None

    redis = get_redis_client()
    session_active = await is_session_active(
        redis,
        db,
        session_id=session_id,
        cache_ttl_seconds=settings.session_revocation_cache_ttl_seconds,
    )
    if not session_active:
        raise _unauthorized()

    # Deliberately uncached — re-read fresh from Postgres on every request
    # so a deactivation (`users.is_active = false`) takes effect
    # immediately, without depending on any cache invalidation elsewhere.
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorized()

    return AuthenticatedUser(user_id=user_id, session_id=session_id)


_FORBIDDEN_DETAIL = "This action requires System Admin privileges."


async def require_system_admin(
    current: Annotated[AuthenticatedUser, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthenticatedUser:
    """`require_auth`, plus a `403` gate on `users.is_system_admin` (T13).

    Backs every `/v1/invites*` System Admin-only route (frozen contract:
    "`system_admin` role has invite + deactivate/reactivate powers only").
    Re-reads `is_system_admin` fresh from Postgres on every call, same
    freshness guarantee as `require_auth`'s `is_active` check — a
    demotion takes effect on the caller's very next request, not after
    some cache TTL.
    """

    # `require_auth` already proved this user exists and is active for
    # this same request but does not hand back the loaded row — re-fetch
    # here rather than re-deriving privilege from the JWT (which never
    # carries a role claim).
    user = await db.get(User, current.user_id)
    if user is None or not user.is_system_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_FORBIDDEN_DETAIL)
    return current
