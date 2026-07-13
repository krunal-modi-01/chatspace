"""Integration tests for `WebSocket /v1/ws` (T23, frozen contract).

Exercises the real endpoint end-to-end against Postgres + Redis (skipped
when unreachable): auth-before-join (missing/invalid/expired token/
revoked session/deactivated user all closing with 4401 before any join
frame is processed), per-frame channel-membership / DM-participant
re-check on `join` (unauthorized → non-fatal `error` frame, socket stays
open), ping/pong heartbeat + mid-connection revalidation (4402/4403/
4404), missed-heartbeat reaping (4408), abusive-frame-rate closing
(4429), `leave` unsubscription bookkeeping, and the server-drain path
(1001).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketDisconnect

from app.core.config import get_settings
from app.core.ids import generate_id
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.models.channel import Channel
from app.models.channel_member import ChannelMember, ChannelMemberRole
from app.models.session import Session
from app.models.user import User
from app.ws.auth import WSAuthenticatedConnection, revalidate_connection
from app.ws.close_codes import WSCloseCode
from app.ws.connection_manager import connection_manager
from tests.conftest import REQUIRED_ENV

pytestmark = pytest.mark.usefixtures("configured_env")


def _test_login_secret() -> str:
    """Not a real secret — see `test_channels_api.py`'s identical helper."""

    return "correct-horse-1"


def _settings() -> object:
    from app.core.config import Settings

    return Settings(**{k.lower(): v for k, v in REQUIRED_ENV.items()})  # type: ignore[arg-type]


async def _make_user(db: AsyncSession, *, is_active: bool = True) -> User:
    unique = generate_id().hex[-12:]
    user = User(
        id=generate_id(),
        username=f"user{unique}",
        email=f"{unique}@example.com",
        hashed_password=hash_password(_test_login_secret()),
        first_name="Test",
        last_name="User",
        is_active=is_active,
        is_system_admin=False,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_session(
    db: AsyncSession, user: User, *, revoked: bool = False, expires_at: datetime | None = None
) -> Session:
    now = datetime.now(UTC)
    session = Session(
        id=generate_id(),
        user_id=user.id,
        refresh_token_hash=f"hash-{generate_id()}",
        issued_at=now,
        expires_at=expires_at or now + timedelta(days=30),
        revoked_at=now if revoked else None,
    )
    db.add(session)
    await db.flush()
    return session


def _token_for(user: User, session: Session, *, issued_at: datetime | None = None) -> str:
    token, _ = create_access_token(
        user_id=str(user.id),
        session_id=str(session.id),
        settings=_settings(),
        now=issued_at,
    )
    return token


async def _authed_user(db: AsyncSession) -> tuple[User, Session, str]:
    user = await _make_user(db)
    session = await _make_session(db, user)
    await db.commit()
    return user, session, _token_for(user, session)


async def _make_channel(
    db: AsyncSession,
    *,
    creator: User,
    is_private: bool = False,
    members: list[User] | None = None,
) -> Channel:
    channel = Channel(
        id=generate_id(),
        name=f"channel-{generate_id().hex[-8:]}",
        is_private=is_private,
        created_by=creator.id,
    )
    db.add(channel)
    await db.flush()

    db.add(ChannelMember(channel_id=channel.id, user_id=creator.id, role=ChannelMemberRole.ADMIN))
    for member in members or []:
        db.add(
            ChannelMember(channel_id=channel.id, user_id=member.id, role=ChannelMemberRole.MEMBER)
        )
    await db.flush()
    return channel


def _ws_url(token: str | None) -> str:
    return "/v1/ws" if token is None else f"/v1/ws?access_token={token}"


@pytest.fixture
def redis_client(redis_available: bool):  # type: ignore[no-untyped-def]
    """A `get_redis_client()` instance fresh to *this* test's event loop.

    `asyncio_mode = "auto"` gives every async test its own event loop; the
    process-wide `lru_cache`d Redis client (`app.db.redis.get_redis_client`)
    must not be reused across loops (a cached client from a previous test's
    now-closed loop raises "attached to a different loop"). Every other
    real-Redis-touching fixture in this suite (`client`, indirectly)
    clears this cache around the test for the same reason.
    """

    if not redis_available:
        pytest.skip("local Redis not reachable on localhost:6379")

    from app.db.redis import get_redis_client

    get_redis_client.cache_clear()
    yield get_redis_client()
    get_redis_client.cache_clear()


class TestConnectAuth:
    """Auth-before-join: connect-time failures always close with 4401."""

    async def test_missing_token_closes_4401_before_any_join(
        self, migrated_db: None, client: TestClient
    ) -> None:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(_ws_url(None)):
                pass
        assert exc_info.value.code == WSCloseCode.AUTH_FAILED

    async def test_invalid_token_closes_4401(self, migrated_db: None, client: TestClient) -> None:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(_ws_url("not-a-real-jwt")):
                pass
        assert exc_info.value.code == WSCloseCode.AUTH_FAILED

    async def test_expired_token_closes_4401(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        user, session, _ = await _authed_user(db_session)
        stale_token = _token_for(user, session, issued_at=datetime.now(UTC) - timedelta(hours=1))

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(_ws_url(stale_token)):
                pass
        assert exc_info.value.code == WSCloseCode.AUTH_FAILED

    async def test_revoked_session_closes_4401(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        user = await _make_user(db_session)
        session = await _make_session(db_session, user, revoked=True)
        await db_session.commit()
        token = _token_for(user, session)

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(_ws_url(token)):
                pass
        assert exc_info.value.code == WSCloseCode.AUTH_FAILED

    async def test_deactivated_user_closes_4401(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        user = await _make_user(db_session, is_active=False)
        session = await _make_session(db_session, user)
        await db_session.commit()
        token = _token_for(user, session)

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(_ws_url(token)):
                pass
        assert exc_info.value.code == WSCloseCode.AUTH_FAILED

    async def test_valid_token_connects_and_accepts(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, _, token = await _authed_user(db_session)

        with client.websocket_connect(_ws_url(token)) as ws:
            ws.send_json({"type": "ping"})
            reply = ws.receive_json()
            assert reply == {"type": "pong"}

    async def test_subprotocol_token_connects_and_echoes_subprotocol(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        """The documented `Sec-WebSocket-Protocol: bearer, <jwt>` fallback.

        A spec-compliant client (all browsers) that offers a non-empty
        `Sec-WebSocket-Protocol` list fails the connection itself if the
        server's handshake response doesn't select one of the offered
        values (RFC 6455 4.1) — so this must round-trip `accepted_subprotocol`.
        """

        _, _, token = await _authed_user(db_session)

        with client.websocket_connect("/v1/ws", subprotocols=["bearer", token]) as ws:
            assert ws.accepted_subprotocol == "bearer"
            ws.send_json({"type": "ping"})
            reply = ws.receive_json()
            assert reply == {"type": "pong"}

    async def test_query_param_token_does_not_select_a_subprotocol(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, _, token = await _authed_user(db_session)

        with client.websocket_connect(_ws_url(token)) as ws:
            assert ws.accepted_subprotocol is None


class TestJoinLeave:
    """Per-frame membership/participant re-check on `join` (F34)."""

    async def test_join_channel_member_succeeds_silently(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, _, _ = await _authed_user(db_session)
        member, _, member_token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=creator, members=[member])
        await db_session.commit()

        with client.websocket_connect(_ws_url(member_token)) as ws:
            ws.send_json(
                {"type": "join", "conversation": {"kind": "channel", "channel_id": str(channel.id)}}
            )
            ws.send_json({"type": "ping"})
            # A join failure would have emitted an `error` frame before the
            # pong; a successful join emits nothing, so the very next frame
            # received is the pong.
            reply = ws.receive_json()
            assert reply == {"type": "pong"}

    async def test_join_channel_non_member_is_non_fatal_error(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, _, _ = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=creator)
        _, _, outsider_token = await _authed_user(db_session)
        await db_session.commit()

        with client.websocket_connect(_ws_url(outsider_token)) as ws:
            ws.send_json(
                {"type": "join", "conversation": {"kind": "channel", "channel_id": str(channel.id)}}
            )
            error = ws.receive_json()
            assert error["type"] == "error"
            assert error["data"]["code"] == "unauthorized_join"

            # Socket stays open — subsequent ping still works.
            ws.send_json({"type": "ping"})
            reply = ws.receive_json()
            assert reply == {"type": "pong"}

    async def test_join_dm_valid_peer_succeeds_silently(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, _, token = await _authed_user(db_session)
        peer, _, _ = await _authed_user(db_session)

        with client.websocket_connect(_ws_url(token)) as ws:
            ws.send_json({"type": "join", "conversation": {"kind": "dm", "user_id": str(peer.id)}})
            ws.send_json({"type": "ping"})
            reply = ws.receive_json()
            assert reply == {"type": "pong"}

    async def test_join_dm_self_is_non_fatal_error(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        user, _, token = await _authed_user(db_session)

        with client.websocket_connect(_ws_url(token)) as ws:
            ws.send_json({"type": "join", "conversation": {"kind": "dm", "user_id": str(user.id)}})
            error = ws.receive_json()
            assert error["type"] == "error"
            assert error["data"]["code"] == "invalid_conversation"

    async def test_join_dm_inactive_peer_is_non_fatal_error(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, _, token = await _authed_user(db_session)
        inactive_peer = await _make_user(db_session, is_active=False)
        await db_session.commit()

        with client.websocket_connect(_ws_url(token)) as ws:
            ws.send_json(
                {"type": "join", "conversation": {"kind": "dm", "user_id": str(inactive_peer.id)}}
            )
            error = ws.receive_json()
            assert error["type"] == "error"
            assert error["data"]["code"] == "unauthorized_join"

    async def test_join_dm_nonexistent_peer_is_non_fatal_error(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, _, token = await _authed_user(db_session)

        with client.websocket_connect(_ws_url(token)) as ws:
            ws.send_json(
                {"type": "join", "conversation": {"kind": "dm", "user_id": str(uuid.uuid4())}}
            )
            error = ws.receive_json()
            assert error["type"] == "error"
            assert error["data"]["code"] == "unauthorized_join"

    async def test_leave_unsubscribes_bookkeeping(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, _, _ = await _authed_user(db_session)
        member, _, member_token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=creator, members=[member])
        await db_session.commit()

        with client.websocket_connect(_ws_url(member_token)) as ws:
            ws.send_json(
                {"type": "join", "conversation": {"kind": "channel", "channel_id": str(channel.id)}}
            )
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}

            states = list(connection_manager._connections.values())  # noqa: SLF001
            matching = [s for s in states if s.user_id == member.id]
            assert len(matching) == 1
            assert str(channel.id) in "".join(matching[0].subscribed_topics)

            ws.send_json(
                {
                    "type": "leave",
                    "conversation": {"kind": "channel", "channel_id": str(channel.id)},
                }
            )
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}

            assert matching[0].subscribed_topics == set()

    async def test_malformed_frame_is_non_fatal_error(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, _, token = await _authed_user(db_session)

        with client.websocket_connect(_ws_url(token)) as ws:
            ws.send_json({"type": "not-a-real-frame"})
            error = ws.receive_json()
            assert error["type"] == "error"
            assert error["data"]["code"] == "invalid_frame"

            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}

    async def test_typing_frame_is_noop(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, _, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=creator)
        await db_session.commit()

        with client.websocket_connect(_ws_url(token)) as ws:
            ws.send_json(
                {
                    "type": "typing",
                    "conversation": {"kind": "channel", "channel_id": str(channel.id)},
                }
            )
            ws.send_json({"type": "ping"})
            # No `error` frame for `typing` (out of scope, deliberately
            # accepted as a no-op) — the very next frame is the pong.
            assert ws.receive_json() == {"type": "pong"}


class TestRevalidation:
    """Mid-connection revalidation close-code mapping (F52, ADR-0006)."""

    async def test_expired_token_maps_to_4402(
        self, migrated_db: None, db_session: AsyncSession, redis_client: object
    ) -> None:
        user = await _make_user(db_session)
        session = await _make_session(db_session, user)
        await db_session.commit()

        connection = WSAuthenticatedConnection(
            user_id=user.id,
            session_id=session.id,
            token_expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )

        close_code = await revalidate_connection(
            db_session,
            redis_client,
            connection=connection,
            settings=_settings(),
        )
        assert close_code == WSCloseCode.TOKEN_EXPIRED

    async def test_revoked_session_maps_to_4403(
        self, migrated_db: None, db_session: AsyncSession, redis_client: object
    ) -> None:
        user = await _make_user(db_session)
        session = await _make_session(db_session, user, revoked=True)
        await db_session.commit()

        connection = WSAuthenticatedConnection(
            user_id=user.id,
            session_id=session.id,
            token_expires_at=datetime.now(UTC) + timedelta(minutes=15),
        )

        close_code = await revalidate_connection(
            db_session,
            redis_client,
            connection=connection,
            settings=_settings(),
        )
        assert close_code == WSCloseCode.TOKEN_REVOKED

    async def test_deactivated_user_maps_to_4404(
        self, migrated_db: None, db_session: AsyncSession, redis_client: object
    ) -> None:
        user = await _make_user(db_session)
        session = await _make_session(db_session, user)
        await db_session.commit()

        connection = WSAuthenticatedConnection(
            user_id=user.id,
            session_id=session.id,
            token_expires_at=datetime.now(UTC) + timedelta(minutes=15),
        )

        user.is_active = False
        await db_session.commit()

        close_code = await revalidate_connection(
            db_session,
            redis_client,
            connection=connection,
            settings=_settings(),
        )
        assert close_code == WSCloseCode.USER_DEACTIVATED

    async def test_still_valid_connection_revalidates_clean(
        self, migrated_db: None, db_session: AsyncSession, redis_client: object
    ) -> None:
        user = await _make_user(db_session)
        session = await _make_session(db_session, user)
        await db_session.commit()

        connection = WSAuthenticatedConnection(
            user_id=user.id,
            session_id=session.id,
            token_expires_at=datetime.now(UTC) + timedelta(minutes=15),
        )

        close_code = await revalidate_connection(
            db_session,
            redis_client,
            connection=connection,
            settings=_settings(),
        )
        assert close_code is None

    async def test_live_connection_drops_with_4403_on_session_revocation(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """End-to-end: revoke the session mid-connection; the next `ping` drops it.

        Uses a near-zero session-revocation cache TTL (rather than reaching
        into `app.db.redis.get_redis_client()` directly from the test body)
        so the revocation-cache write the first `ping` makes and the read
        the second `ping` makes both happen inside the running app/portal
        — the same event loop — instead of racing a second, test-owned
        Redis client bound to a different loop.
        """

        monkeypatch.setenv("SESSION_REVOCATION_CACHE_TTL_SECONDS", "1")
        get_settings.cache_clear()
        try:
            user, session, token = await _authed_user(db_session)

            with client.websocket_connect(_ws_url(token)) as ws:
                ws.send_json({"type": "ping"})
                assert ws.receive_json() == {"type": "pong"}

                session_row = await db_session.get(Session, session.id)
                assert session_row is not None
                session_row.revoked_at = datetime.now(UTC)
                await db_session.commit()

                # Let the 1s cache entry lapse so the next `ping`'s
                # revalidation re-reads Postgres and observes the revoke.
                await asyncio.sleep(1.2)

                ws.send_json({"type": "ping"})
                with pytest.raises(WebSocketDisconnect) as exc_info:
                    ws.receive_json()
                assert exc_info.value.code == WSCloseCode.TOKEN_REVOKED
        finally:
            get_settings.cache_clear()

    async def test_live_connection_drops_with_4404_on_deactivation(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        """End-to-end: deactivate the user mid-connection; the next `ping` drops it."""

        user, _, token = await _authed_user(db_session)

        with client.websocket_connect(_ws_url(token)) as ws:
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}

            user_row = await db_session.get(User, user.id)
            assert user_row is not None
            user_row.is_active = False
            await db_session.commit()

            ws.send_json({"type": "ping"})
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_json()
            assert exc_info.value.code == WSCloseCode.USER_DEACTIVATED


class TestHeartbeatTimeoutAndRateLimit:
    """Missed-heartbeat reaping (4408) and abusive-frame-rate closing (4429)."""

    async def test_missed_heartbeat_is_reaped_with_4408(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("WS_HEARTBEAT_TIMEOUT_SECONDS", "0.3")
        get_settings.cache_clear()
        try:
            _, _, token = await _authed_user(db_session)

            with client.websocket_connect(_ws_url(token)) as ws:
                with pytest.raises(WebSocketDisconnect) as exc_info:
                    ws.receive_json()
                assert exc_info.value.code == WSCloseCode.HEARTBEAT_TIMEOUT
        finally:
            get_settings.cache_clear()

    async def test_non_ping_frames_do_not_extend_the_heartbeat_deadline(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Regression: a client that never re-pings must still be reaped.

        Pre-fix, *any* received frame reset the heartbeat timer, so a
        client could send harmless `leave` frames faster than the timeout
        and dodge periodic revalidation forever. Only a `ping` frame may
        extend the heartbeat deadline; sending other traffic on a tight
        interval must not keep the connection alive past
        `ws_heartbeat_timeout_seconds`.
        """

        monkeypatch.setenv("WS_HEARTBEAT_TIMEOUT_SECONDS", "0.3")
        get_settings.cache_clear()
        try:
            _, _, token = await _authed_user(db_session)
            leave_frame = {
                "type": "leave",
                "conversation": {"kind": "channel", "channel_id": str(uuid.uuid4())},
            }

            with client.websocket_connect(_ws_url(token)) as ws:
                with pytest.raises(WebSocketDisconnect) as exc_info:
                    # ~50ms apart, well under the 300ms heartbeat timeout,
                    # for a full second — far longer than a single timeout
                    # window — with no `ping` ever sent.
                    for _ in range(20):
                        ws.send_json(leave_frame)
                        await asyncio.sleep(0.05)
                    ws.receive_json()
                assert exc_info.value.code == WSCloseCode.HEARTBEAT_TIMEOUT
        finally:
            get_settings.cache_clear()

    async def test_invalid_utf8_binary_frame_is_non_fatal_error(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        """A binary frame with invalid UTF-8 bytes must not crash the connection.

        It should be treated like any other malformed frame (non-fatal
        `error`), not propagate an uncaught `UnicodeDecodeError` that
        terminates the connection with an undocumented close.
        """

        _, _, token = await _authed_user(db_session)

        with client.websocket_connect(_ws_url(token)) as ws:
            ws.send_bytes(bytes([0xFF, 0xFE]))
            error = ws.receive_json()
            assert error["type"] == "error"
            assert error["data"]["code"] == "invalid_frame"

            # Socket stays open — subsequent ping still works.
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}

    async def test_abusive_frame_rate_closes_with_4429(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("WS_FRAME_RATE_LIMIT_MAX_FRAMES", "3")
        monkeypatch.setenv("WS_FRAME_RATE_LIMIT_WINDOW_SECONDS", "10")
        get_settings.cache_clear()
        try:
            _, _, token = await _authed_user(db_session)

            with client.websocket_connect(_ws_url(token)) as ws:
                for _ in range(3):
                    ws.send_json({"type": "ping"})
                    assert ws.receive_json() == {"type": "pong"}

                # 4th and later frames within the window exceed the limit.
                ws.send_json({"type": "ping"})
                ws.send_json({"type": "ping"})
                with pytest.raises(WebSocketDisconnect) as exc_info:
                    ws.receive_json()
                assert exc_info.value.code == WSCloseCode.RATE_LIMITED
        finally:
            get_settings.cache_clear()


async def _wait_until_last_seen_persisted(
    db_session: AsyncSession, user: User, *, timeout_seconds: float = 3.0
) -> None:
    """Poll `user.last_seen` (via `db_session.refresh`) until it is set.

    The server-side `finally` block (unregister + `presence.handle_disconnect`,
    including its own commit) runs as a continuation of the same endpoint
    task on the app's own anyio portal, not synchronously with whatever
    line of test code triggered the disconnect — so asserting on its
    committed side effect must poll rather than assume it has already
    landed the instant the disconnect was sent (same rationale as
    `test_ws_fanout.py`'s `_wait_until`).

    Callers must poll for this *before* letting
    `client.websocket_connect`'s `with` block exit naturally: exiting it
    invokes `WebSocketTestSession.__exit__`, which — after resending a
    close — cancels the anyio `CancelScope` wrapping the endpoint's ASGI
    call almost immediately (Starlette `testclient.py`'s
    `stack.callback(portal.call, cs.cancel)`). In a real deployment
    nothing ever cancels a connection's task out from under its own
    `finally` block this way — only this synthetic per-session teardown
    does — so the disconnect must be triggered and its durable side
    effect awaited *inside* the `with` block, before that teardown can
    race it.
    """

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while loop.time() < deadline:
        await db_session.refresh(user)
        if user.last_seen is not None:
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"user {user.id}'s last_seen was not persisted within {timeout_seconds}s")


class TestPresenceLifecycle:
    """End-to-end T25: a live `/v1/ws` connection ref-counts presence and a
    clean disconnect (or a missed-heartbeat reap) persists `last_seen`.

    Deliberately does not touch `app.db.redis.get_redis_client()` directly
    from the test body: `TestClient.websocket_connect` runs the app (and
    thus the process-wide Redis client) on its own anyio portal, and a
    second, test-owned client bound to *this* test's `pytest-asyncio` loop
    would race it (`test_ws_fanout.py`'s note on the identical hazard for
    a two-client setup). Asserting on the durable Postgres `last_seen`
    write is enough to prove `presence.handle_connect`/`handle_disconnect`
    actually ran on every connect/disconnect through the real endpoint,
    without needing to read the app's own in-process Redis client from a
    different event loop.
    """

    async def test_clean_disconnect_persists_last_seen(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        user, _, token = await _authed_user(db_session)
        assert user.last_seen is None

        with client.websocket_connect(_ws_url(token)) as ws:
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}

            # Trigger the client-initiated disconnect and await its durable
            # side effect *while still inside the `with` block* — see
            # `_wait_until_last_seen_persisted`'s docstring for why this
            # must happen before the block's own `__exit__` teardown runs.
            ws.close()
            await _wait_until_last_seen_persisted(db_session, user)

    async def test_missed_heartbeat_reap_also_persists_last_seen(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("WS_HEARTBEAT_TIMEOUT_SECONDS", "0.3")
        get_settings.cache_clear()
        try:
            user, _, token = await _authed_user(db_session)

            with client.websocket_connect(_ws_url(token)) as ws:
                with pytest.raises(WebSocketDisconnect) as exc_info:
                    ws.receive_json()
                assert exc_info.value.code == WSCloseCode.HEARTBEAT_TIMEOUT

                # Await the durable side effect while still inside the
                # `with` block — see `_wait_until_last_seen_persisted`'s
                # docstring for why this must happen before the block's
                # own `__exit__` teardown cancels the endpoint's task.
                await _wait_until_last_seen_persisted(db_session, user)
        finally:
            get_settings.cache_clear()


class TestServerDrain:
    """Server shutdown/instance drain closes every live connection with 1001."""

    async def test_close_all_uses_going_away_code(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, _, token = await _authed_user(db_session)

        with client.websocket_connect(_ws_url(token)) as ws:
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}

            await connection_manager.close_all()

            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_json()
            assert exc_info.value.code == WSCloseCode.GOING_AWAY
