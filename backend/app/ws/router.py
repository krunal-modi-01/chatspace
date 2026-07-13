"""`WebSocket /v1/ws` — the T23 connection manager endpoint.

Implements, per the frozen API contract (T23 slice) and F51-F56:

- **Auth before join** — `authenticate_connect` runs (and must succeed)
  before `websocket.accept()` and before any `join` frame is processed;
  failure closes with 4401.
- **Per-frame join/leave re-check** — every `join` re-runs the channel
  membership / DM participant check (`app.ws.conversations`); an
  unauthorized join sends a non-fatal `error` frame and the socket stays
  open.
- **Heartbeat + periodic revalidation** — a client `ping` gets a `pong`
  and triggers `revalidate_connection`; a stale/revoked/deactivated
  session closes mid-connection with 4402/4403/4404. The heartbeat clock
  is only extended by a `ping` frame — a connection that sends other
  traffic (`join`/`leave`/`typing`/malformed frames) but no `ping` within
  `ws_heartbeat_timeout_seconds` of the last one is still reaped with
  4408; this keeps periodic revalidation from being dodged by a client
  that never pings again after the first one.
- **Frame-rate abuse guard** — `FrameRateLimiter` closes with 4429 on an
  abusive frame rate.
- **Per-connection subscription bookkeeping** — `connection_manager`
  tracks which topics a connection has joined; no Redis fan-out payload
  is published here (T24).
- **Presence lifecycle (T25, F49-F50)** — `app.services.presence.handle_connect`
  ref-counts this connection right after it registers, `handle_heartbeat`
  renews its TTL on every client `ping` (alongside revalidation), and
  `handle_disconnect` runs unconditionally in the connection's `finally`
  block — on a clean client close, a 4402/4403/4404 revalidation drop,
  and a 4408 heartbeat-timeout reap alike — so every disconnect path
  decrements the ref-count and, on the last one, durably persists
  `users.last_seen` and emits the `offline` presence event.

Explicitly out of scope here (T26): `typing` delivery to other clients.
`typing` frames are accepted and deliberately no-op'd rather than
rejected, so a client that already speaks the full contract doesn't get
spurious `error` frames for a frame type this task doesn't yet act on.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import APIRouter
from pydantic import ValidationError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocket, WebSocketState

from app.core.config import Settings, get_settings
from app.core.correlation import generate_correlation_id, set_correlation_id
from app.core.redis_keys import channel_topic, dm_topic
from app.db.redis import get_redis_client
from app.db.session import get_sessionmaker
from app.services import presence
from app.ws.auth import (
    WSAuthenticatedConnection,
    WSAuthError,
    authenticate_connect,
    revalidate_connection,
)
from app.ws.close_codes import WSCloseCode
from app.ws.connection_manager import ConnectionState, connection_manager
from app.ws.conversations import authorize_conversation
from app.ws.frames import (
    ChannelConversation,
    Conversation,
    DMConversation,
    JoinFrame,
    LeaveFrame,
    PingFrame,
    TypingFrame,
    client_frame_adapter,
    error_frame,
    pong_frame,
)
from app.ws.rate_limit import FrameRateLimiter

logger = logging.getLogger(__name__)

ws_router = APIRouter()


@asynccontextmanager
async def _db_session() -> AsyncIterator[AsyncSession]:
    """A short-lived `AsyncSession` for one WS operation (connect/heartbeat/join).

    Mirrors `app.db.session.get_db_session`'s commit/rollback/close
    contract, but as a plain async context manager rather than a FastAPI
    dependency — a WS connection is long-lived, so it must not hold a
    single DB session/transaction open for its whole lifetime; each
    discrete operation gets its own short session instead.
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


def _topic_for(conversation: Conversation, caller_id: UUID) -> str:
    """Compute the canonical topic string for a `leave` frame (no re-auth).

    Leaving a subscription the connection may or may not currently hold
    is always safe — unlike `join`, no membership/participant re-check is
    required to *stop* listening to a topic.
    """

    if isinstance(conversation, ChannelConversation):
        return channel_topic(conversation.channel_id)
    if isinstance(conversation, DMConversation):
        return dm_topic(caller_id, conversation.user_id)
    raise AssertionError("unreachable: unknown conversation kind")  # pragma: no cover


async def _authenticate_and_accept(
    websocket: WebSocket, *, redis: Redis, settings: Settings
) -> WSAuthenticatedConnection | None:
    """Run connect-time auth; accept the socket on success, close(4401) on failure.

    Returns `None` (already closed) on failure so the caller can return
    immediately without processing any frame.
    """

    try:
        async with _db_session() as db:
            auth = await authenticate_connect(websocket, db, redis, settings=settings)
    except WSAuthError:
        logger.info("ws connect auth failed")
        await websocket.close(code=WSCloseCode.AUTH_FAILED)
        return None
    except Exception:  # noqa: BLE001 - infra hiccup (DB/Redis) must still get a documented code
        logger.exception("ws connect auth failed with an unexpected error; closing with 4401")
        await websocket.close(code=WSCloseCode.AUTH_FAILED)
        return None

    await websocket.accept(subprotocol=auth.accepted_subprotocol)
    return auth


async def _receive_frame_dict(
    websocket: WebSocket, *, timeout_seconds: float
) -> dict[str, object] | None:
    """Receive and JSON-decode one client frame, or `None` on clean disconnect.

    Raises `TimeoutError` if nothing arrives within `timeout_seconds`
    (missed-heartbeat reap path) and returns `None` when the client closed
    the connection (`websocket.disconnect`) so the caller can exit its
    loop without treating a normal client-initiated close as an error.
    """

    message = await asyncio.wait_for(websocket.receive(), timeout=timeout_seconds)

    if message["type"] == "websocket.disconnect":
        return None

    raw_text = message.get("text")
    if raw_text is None and message.get("bytes") is not None:
        try:
            raw_text = message["bytes"].decode("utf-8")
        except UnicodeDecodeError:
            # Not valid UTF-8 text — treat like any other malformed frame
            # rather than letting the decode error crash the connection
            # with an undocumented close.
            return {}
    if raw_text is None:
        return {}

    try:
        decoded = json.loads(raw_text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(decoded, dict):
        return {}
    return decoded


@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """`/v1/ws` — see module docstring for the full behavior contract."""

    set_correlation_id(generate_correlation_id())
    settings = get_settings()
    redis = get_redis_client()

    auth = await _authenticate_and_accept(websocket, redis=redis, settings=settings)
    if auth is None:
        return

    state = connection_manager.register(websocket, user_id=auth.user_id, session_id=auth.session_id)
    limiter = FrameRateLimiter(
        max_frames=settings.ws_frame_rate_limit_max_frames,
        window_seconds=settings.ws_frame_rate_limit_window_seconds,
    )

    try:
        # T25: ref-count this connection as soon as it is registered —
        # inside this same `try` so that even a non-Redis-transport bug in
        # `handle_connect` still runs `unregister`/`handle_disconnect`
        # below rather than leaking the connection-manager registration
        # and skipping the paired decrement (code review finding 4).
        # Every disconnect path below (clean close, revalidation drop,
        # heartbeat reap) runs `handle_disconnect` in `finally` regardless
        # of how the loop exits, so connect/disconnect stay paired.
        await presence.handle_connect(
            redis, user_id=auth.user_id, ttl_seconds=settings.presence_ttl_seconds
        )
        await _connection_loop(
            websocket,
            auth=auth,
            state=state,
            limiter=limiter,
            redis=redis,
            settings=settings,
        )
    finally:
        connection_manager.unregister(state)
        async with _db_session() as db:
            await presence.handle_disconnect(redis, db, user_id=auth.user_id)


async def _connection_loop(
    websocket: WebSocket,
    *,
    auth: WSAuthenticatedConnection,
    state: ConnectionState,
    limiter: FrameRateLimiter,
    redis: Redis,
    settings: Settings,
) -> None:
    # The heartbeat deadline is only ever pushed forward by a `ping` frame
    # (see `PingFrame` handling below) — never by `join`/`leave`/`typing`/
    # malformed traffic. Otherwise a client could dodge periodic
    # revalidation indefinitely by sending anything *but* `ping` on an
    # interval shorter than the timeout, which would both violate the
    # contract's "dropped at the next heartbeat" guarantee and let a
    # revoked/deactivated session keep issuing (stale-membership) `join`s.
    loop = asyncio.get_running_loop()
    heartbeat_deadline = loop.time() + settings.ws_heartbeat_timeout_seconds

    while True:
        remaining = heartbeat_deadline - loop.time()
        if remaining <= 0:
            logger.info(
                "ws heartbeat timeout; reaping connection",
                extra={"user_id": str(auth.user_id)},
            )
            await _safe_close(websocket, code=WSCloseCode.HEARTBEAT_TIMEOUT)
            return

        try:
            raw = await _receive_frame_dict(websocket, timeout_seconds=remaining)
        except TimeoutError:
            logger.info(
                "ws heartbeat timeout; reaping connection",
                extra={"user_id": str(auth.user_id)},
            )
            await _safe_close(websocket, code=WSCloseCode.HEARTBEAT_TIMEOUT)
            return

        if raw is None:
            # Client closed the connection itself (normal closure) — nothing
            # further to send; the ASGI transport is already gone.
            return

        if limiter.record_and_check():
            logger.info(
                "ws frame rate limit exceeded; closing connection",
                extra={"user_id": str(auth.user_id)},
            )
            await _safe_close(websocket, code=WSCloseCode.RATE_LIMITED)
            return

        try:
            frame = client_frame_adapter.validate_python(raw)
        except ValidationError:
            await _safe_send_json(
                websocket,
                error_frame(code="invalid_frame", detail="Malformed or unrecognized frame."),
            )
            continue

        if isinstance(frame, PingFrame):
            # Extend the deadline on receipt of the ping itself (liveness
            # demonstrated) regardless of what revalidation below decides —
            # a connection that must be dropped is dropped via its own
            # close code, not via a stale heartbeat timeout race.
            heartbeat_deadline = loop.time() + settings.ws_heartbeat_timeout_seconds
            await presence.handle_heartbeat(
                redis, user_id=auth.user_id, ttl_seconds=settings.presence_ttl_seconds
            )
            close_code = await _revalidate(auth, redis=redis, settings=settings)
            if close_code is not None:
                logger.info(
                    "ws revalidation failed; closing connection",
                    extra={"user_id": str(auth.user_id), "close_code": int(close_code)},
                )
                await _safe_close(websocket, code=close_code)
                return
            await _safe_send_json(websocket, pong_frame())
            continue

        if isinstance(frame, JoinFrame):
            async with _db_session() as db:
                result = await authorize_conversation(
                    db, conversation=frame.conversation, caller_id=auth.user_id
                )
            if not result.authorized:
                assert result.error_code is not None
                assert result.error_detail is not None
                await _safe_send_json(
                    websocket, error_frame(code=result.error_code, detail=result.error_detail)
                )
                continue
            assert result.topic is not None
            connection_manager.subscribe(state, result.topic)
            continue

        if isinstance(frame, LeaveFrame):
            topic = _topic_for(frame.conversation, auth.user_id)
            connection_manager.unsubscribe(state, topic)
            continue

        if isinstance(frame, TypingFrame):
            # Typing delivery is T26 scope; accepted and intentionally a
            # no-op here so it doesn't trip the "unknown frame" error path.
            continue


async def _revalidate(
    auth: WSAuthenticatedConnection, *, redis: Redis, settings: Settings
) -> WSCloseCode | None:
    async with _db_session() as db:
        return await revalidate_connection(db, redis, connection=auth, settings=settings)


async def _safe_close(websocket: WebSocket, *, code: WSCloseCode) -> None:
    if websocket.application_state == WebSocketState.CONNECTED:
        await websocket.close(code=code)


async def _safe_send_json(websocket: WebSocket, payload: dict[str, object]) -> None:
    if websocket.application_state == WebSocketState.CONNECTED:
        await websocket.send_json(payload)
