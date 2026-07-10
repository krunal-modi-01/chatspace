"""`/v1/ws` connect-time auth + mid-connection revalidation (T23, F52, ADR-0006).

Two distinct checks, both reused from the exact primitives `require_auth`
(`app.core.deps`) uses for REST so the two surfaces never drift:

1. **Connect-time auth** (`authenticate_connect`) — decode + verify the
   access JWT, then re-run the session-revocation check
   (`app.services.session_revocation.is_session_active`) and the
   `users.is_active` check, all *before* the connection is accepted or
   any `join` frame is processed. Any failure raises `WSAuthError` with
   close code 4401 (contract: auth-failed at connect, not one of the
   more specific mid-connection codes).

2. **Periodic revalidation** (`revalidate_connection`) — re-run on every
   client `ping` (the contract's "on each heartbeat, re-runs the
   session-revocation check"). Unlike connect-time auth, a mid-connection
   failure must map to one of three *specific* close codes so the client
   knows what to do next (refresh-and-reconnect vs. give up):
   token-expired (4402), token-revoked (4403), or user-deactivated
   (4404). Checked in that order because an expired JWT is the most
   common/expected trigger (15-minute access-token TTL vs. a
   heartbeat-timeout window of several times that) and is distinguished
   from session-level revocation using the JWT's own `exp` claim, decoded
   once at connect time — `is_session_active` alone cannot tell "JWT
   expired" apart from "session revoked", so token expiry is checked
   first using the claim this module already extracted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocket

from app.core.config import Settings
from app.core.jwt import ExpiredTokenError, InvalidTokenError, decode_access_token
from app.models.user import User
from app.services.session_revocation import is_session_active
from app.ws.close_codes import WSCloseCode

logger = logging.getLogger(__name__)

_ACCESS_TOKEN_QUERY_PARAM = "access_token"


class WSAuthError(Exception):
    """Connect-time authentication failure — always maps to close code 4401."""


@dataclass(frozen=True, slots=True)
class WSAuthenticatedConnection:
    """The verified identity + token expiry backing a live `/v1/ws` connection."""

    user_id: UUID
    session_id: UUID
    token_expires_at: datetime
    accepted_subprotocol: str | None = None
    """The sub-protocol the server must echo back on `websocket.accept()`.

    `None` when the token came via the `?access_token=` query param (no
    sub-protocol negotiation involved). When the token came via the
    `Sec-WebSocket-Protocol` bearer fallback, RFC 6455 4.1 requires the
    server's handshake response to select one of the client-offered
    protocol strings — a browser client fails the connection itself if it
    doesn't, before any frame (including this auth) is ever processed.
    """


def extract_access_token(websocket: WebSocket) -> tuple[str | None, str | None]:
    """Return `(token, subprotocol_to_accept)`, or `(None, None)` if absent.

    Per the contract: `?access_token=<jwt>` query param, or a bearer
    `Sec-WebSocket-Protocol` sub-protocol. The query param is checked
    first (the common browser-client path, since browser `WebSocket`
    cannot set arbitrary headers); the sub-protocol is a fallback for
    clients that prefer not to put the token in the URL (query strings
    can land in server/proxy access logs).

    `subprotocol_to_accept` is the exact client-offered protocol string
    (e.g. `"bearer"`) the caller must pass back to `websocket.accept()`
    when the sub-protocol path was used — `None` for the query-param path.
    """

    query_token = websocket.query_params.get(_ACCESS_TOKEN_QUERY_PARAM)
    if query_token:
        return query_token, None

    # Sub-protocol fallback convention: `Sec-WebSocket-Protocol: bearer, <jwt>`
    # (two comma-separated entries: the literal scheme, then the token) —
    # avoids the token landing in a URL that proxies/servers may log.
    subprotocols = [
        entry.strip() for entry in websocket.headers.get("sec-websocket-protocol", "").split(",")
    ]
    if len(subprotocols) == 2 and subprotocols[0].lower() == "bearer" and subprotocols[1]:
        return subprotocols[1], subprotocols[0]
    return None, None


async def authenticate_connect(
    websocket: WebSocket,
    db: AsyncSession,
    redis: Redis,
    *,
    settings: Settings,
) -> WSAuthenticatedConnection:
    """Verify the connect-time token + session + user, or raise `WSAuthError`.

    Must be called — and must succeed — before `websocket.accept()` and
    before any `join` frame is processed (contract: "auth BEFORE any
    join"). Never logs the raw token.
    """

    token, accepted_subprotocol = extract_access_token(websocket)
    if not token:
        raise WSAuthError("missing access token")

    try:
        payload = decode_access_token(token, settings=settings)
    except (ExpiredTokenError, InvalidTokenError) as exc:
        raise WSAuthError("invalid or expired access token") from exc

    try:
        user_id = UUID(payload.user_id)
        session_id = UUID(payload.session_id)
    except ValueError as exc:
        raise WSAuthError("malformed token claims") from exc

    session_active = await is_session_active(
        redis,
        db,
        session_id=session_id,
        cache_ttl_seconds=settings.session_revocation_cache_ttl_seconds,
    )
    if not session_active:
        raise WSAuthError("session is not active")

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise WSAuthError("user is not active")

    return WSAuthenticatedConnection(
        user_id=user_id,
        session_id=session_id,
        token_expires_at=payload.expires_at,
        accepted_subprotocol=accepted_subprotocol,
    )


async def revalidate_connection(
    db: AsyncSession,
    redis: Redis,
    *,
    connection: WSAuthenticatedConnection,
    settings: Settings,
    now: datetime | None = None,
) -> WSCloseCode | None:
    """Re-run the auth checks for a live connection; return a close code if it must drop.

    Returns `None` when the connection remains valid. Order matters (see
    module docstring): JWT expiry, then session revocation, then user
    deactivation.
    """

    current_time = now or datetime.now(UTC)

    if connection.token_expires_at <= current_time:
        return WSCloseCode.TOKEN_EXPIRED

    session_active = await is_session_active(
        redis,
        db,
        session_id=connection.session_id,
        cache_ttl_seconds=settings.session_revocation_cache_ttl_seconds,
    )
    if not session_active:
        return WSCloseCode.TOKEN_REVOKED

    user = await db.get(User, connection.user_id)
    if user is None or not user.is_active:
        return WSCloseCode.USER_DEACTIVATED

    return None
