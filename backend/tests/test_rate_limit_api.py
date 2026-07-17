"""End-to-end `429`/`Retry-After` tests for the T27 Redis rate limiter.

Exercises the real routes through `TestClient` against Postgres + Redis
(skipped when unreachable, matching every other integration test in this
suite): per-user message-send (channel + DM) and per-IP+identifier auth
rate limiting (login, refresh, register, password-reset request), plus
the non-enumeration guarantee (an over-limit auth response looks
identical whether or not the attempted identifier is real).

Every test uses a freshly generated user/channel/identifier so its bucket
never collides with another test's — this suite does not flush Redis
between tests (see `tests/test_rate_limit.py`'s module docstring), so
reusing a literal identifier across tests would make counts leak between
them.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.core.metrics import reset_metrics
from app.core.metrics import snapshot as metrics_snapshot
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import generate_id
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.models.channel import Channel
from app.models.channel_member import ChannelMember, ChannelMemberRole
from app.models.session import Session
from app.models.user import User
from tests.conftest import REQUIRED_ENV

pytestmark = pytest.mark.usefixtures("configured_env")

_TEST_CREDENTIAL = "correct-horse-1"

# MESSAGE_SEND capacity (burst) — must match `app.core.rate_limit`'s
# `RateLimitScope.MESSAGE_SEND` policy exactly, since these tests drive
# the bucket to (and past) that limit.
_MESSAGE_SEND_CAPACITY = 20
# AUTH capacity — must match `RateLimitScope.AUTH`'s policy.
_AUTH_CAPACITY = 5
# MEDIA_UPLOAD capacity (burst) — must match `RateLimitScope.MEDIA_UPLOAD`'s
# policy (T28's `Depends(enforce_media_upload_rate_limit)` wiring on
# `POST /v1/media`).
_MEDIA_UPLOAD_CAPACITY = 20


def _minimal_png_bytes() -> bytes:
    """A real, tiny, valid PNG — must survive `strip_exif`'s decode/re-encode.

    Unlike a bare magic-byte signature, `POST /v1/media` (`kind=image`)
    also runs the upload through Pillow's mandatory EXIF-strip (F61), so
    this needs to be an actual decodable image, not just bytes that sniff
    as one.
    """

    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), color=(1, 2, 3)).save(buffer, format="PNG")
    return buffer.getvalue()


def _settings() -> object:
    from app.core.config import Settings

    return Settings(**{k.lower(): v for k, v in REQUIRED_ENV.items()})  # type: ignore[arg-type]


async def _make_user(db: AsyncSession, *, is_active: bool = True) -> User:
    unique = generate_id().hex[-12:]
    user = User(
        id=generate_id(),
        username=f"user{unique}",
        email=f"{unique}@example.com",
        hashed_password=hash_password(_TEST_CREDENTIAL),
        first_name="Test",
        last_name="User",
        is_active=is_active,
        is_system_admin=False,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_session(db: AsyncSession, user: User) -> Session:
    now = datetime.now(UTC)
    session = Session(
        id=generate_id(),
        user_id=user.id,
        refresh_token_hash=f"hash-{generate_id()}",
        issued_at=now,
        expires_at=now + timedelta(days=30),
        revoked_at=None,
    )
    db.add(session)
    await db.flush()
    return session


def _bearer_token_for(user: User, session: Session) -> str:
    token, _ = create_access_token(
        user_id=str(user.id), session_id=str(session.id), settings=_settings()
    )
    return token


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _authed_user(db: AsyncSession) -> tuple[User, str]:
    user = await _make_user(db)
    session = await _make_session(db, user)
    await db.commit()
    return user, _bearer_token_for(user, session)


async def _make_channel(db: AsyncSession, *, creator: User) -> Channel:
    channel = Channel(
        id=generate_id(),
        name=f"channel-{generate_id().hex[-8:]}",
        is_private=False,
        created_by=creator.id,
    )
    db.add(channel)
    await db.flush()
    db.add(ChannelMember(channel_id=channel.id, user_id=creator.id, role=ChannelMemberRole.ADMIN))
    await db.flush()
    return channel


def _idem_key() -> str:
    return str(uuid.uuid4())


class TestChannelMessageSendRateLimit:
    async def test_burst_capacity_then_429_with_retry_after(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession, redis_available: bool
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        sender, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        await db_session.commit()

        reset_metrics()
        for _ in range(_MESSAGE_SEND_CAPACITY):
            response = client.post(
                f"/v1/channels/{channel.id}/messages",
                headers={**_auth_header(token), "Idempotency-Key": _idem_key()},
                json={"content": "hello"},
            )
            assert response.status_code == 201

        over_limit = client.post(
            f"/v1/channels/{channel.id}/messages",
            headers={**_auth_header(token), "Idempotency-Key": _idem_key()},
            json={"content": "one too many"},
        )

        assert over_limit.status_code == 429
        assert over_limit.headers["content-type"] == "application/problem+json"
        assert int(over_limit.headers["retry-after"]) >= 1
        body = over_limit.json()
        assert body["status"] == 429
        assert "correlation_id" in body

        # Key metric (technical spec §9): "429 counts by endpoint class" —
        # this is the REST-route rate-limit path (distinct from the WS
        # frame-rate guard's own `endpoint_class=ws_frame`, already covered
        # by `test_ws_connection_manager.py`), labeled by the matched route
        # *template*, not the raw path (T39; code review finding 1).
        # `APIRoute.path` reflects only the router's own declared path, not
        # the `/v1` prefix applied by `include_router` at mount time (T39;
        # verified against the actual running app rather than assumed).
        counters = metrics_snapshot()["counters"]["rate_limit_rejected_total"]
        assert counters["endpoint_class=/channels/{channel_id}/messages"] == 1

    async def test_different_users_have_independent_buckets(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession, redis_available: bool
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        exhausted_sender, exhausted_token = await _authed_user(db_session)
        exhausted_channel = await _make_channel(db_session, creator=exhausted_sender)
        other_sender, other_token = await _authed_user(db_session)
        other_channel = await _make_channel(db_session, creator=other_sender)
        await db_session.commit()

        for _ in range(_MESSAGE_SEND_CAPACITY):
            response = client.post(
                f"/v1/channels/{exhausted_channel.id}/messages",
                headers={**_auth_header(exhausted_token), "Idempotency-Key": _idem_key()},
                json={"content": "hello"},
            )
            assert response.status_code == 201

        exhausted_response = client.post(
            f"/v1/channels/{exhausted_channel.id}/messages",
            headers={**_auth_header(exhausted_token), "Idempotency-Key": _idem_key()},
            json={"content": "one too many"},
        )
        other_response = client.post(
            f"/v1/channels/{other_channel.id}/messages",
            headers={**_auth_header(other_token), "Idempotency-Key": _idem_key()},
            json={"content": "still fine"},
        )

        assert exhausted_response.status_code == 429
        assert other_response.status_code == 201


class TestDmMessageSendRateLimit:
    async def test_burst_capacity_then_429_with_retry_after(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession, redis_available: bool
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        sender, token = await _authed_user(db_session)
        recipient = await _make_user(db_session)
        await db_session.commit()

        for _ in range(_MESSAGE_SEND_CAPACITY):
            response = client.post(
                f"/v1/dms/{recipient.id}/messages",
                headers={**_auth_header(token), "Idempotency-Key": _idem_key()},
                json={"content": "hey"},
            )
            assert response.status_code == 201

        over_limit = client.post(
            f"/v1/dms/{recipient.id}/messages",
            headers={**_auth_header(token), "Idempotency-Key": _idem_key()},
            json={"content": "one too many"},
        )

        assert over_limit.status_code == 429
        assert int(over_limit.headers["retry-after"]) >= 1


class TestLoginRateLimit:
    async def test_five_attempts_then_429(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession, redis_available: bool
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        user = await _make_user(db_session)
        await db_session.commit()

        for _ in range(_AUTH_CAPACITY):
            response = client.post(
                "/v1/auth/login", json={"email": user.email, "password": "totally-wrong-1"}
            )
            assert response.status_code == 401

        over_limit = client.post(
            "/v1/auth/login", json={"email": user.email, "password": "totally-wrong-1"}
        )

        assert over_limit.status_code == 429
        assert int(over_limit.headers["retry-after"]) >= 1
        assert over_limit.headers["content-type"] == "application/problem+json"

    async def test_non_enumerating_unknown_email_behaves_identically(
        self, migrated_db: None, client: TestClient, redis_available: bool
    ) -> None:
        """A nonexistent email is rate-limited the same way as a real one.

        Proves the auth-scope bucket key never depends on account
        existence (F11/F64): identical `401` x5 then `429` shape for an
        email that was never a real account.
        """

        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        bogus_email = f"nobody-{uuid.uuid4().hex}@example.com"

        for _ in range(_AUTH_CAPACITY):
            response = client.post(
                "/v1/auth/login", json={"email": bogus_email, "password": "whatever-1"}
            )
            assert response.status_code == 401

        over_limit = client.post(
            "/v1/auth/login", json={"email": bogus_email, "password": "whatever-1"}
        )

        assert over_limit.status_code == 429


class TestRefreshRateLimit:
    async def test_five_attempts_then_429(
        self, migrated_db: None, client: TestClient, redis_available: bool
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        bogus_refresh_token = f"not-a-real-refresh-token-{uuid.uuid4().hex}"

        for _ in range(_AUTH_CAPACITY):
            response = client.post("/v1/auth/refresh", json={"refresh_token": bogus_refresh_token})
            assert response.status_code == 401

        over_limit = client.post("/v1/auth/refresh", json={"refresh_token": bogus_refresh_token})

        assert over_limit.status_code == 429
        assert int(over_limit.headers["retry-after"]) >= 1


class TestRegisterRateLimit:
    async def test_five_attempts_then_429(
        self, migrated_db: None, client: TestClient, redis_available: bool
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        bogus_invite_token = f"not-a-real-invite-token-{uuid.uuid4().hex}"
        body = {
            "invite_token": bogus_invite_token,
            "username": "newbie",
            "first_name": "New",
            "last_name": "Bie",
            "password": _TEST_CREDENTIAL,
            "avatar_url": None,
        }

        for _ in range(_AUTH_CAPACITY):
            response = client.post("/v1/auth/register", json=body)
            assert response.status_code == 410

        over_limit = client.post("/v1/auth/register", json=body)

        assert over_limit.status_code == 429
        assert int(over_limit.headers["retry-after"]) >= 1


class TestPasswordResetRequestRateLimit:
    async def test_five_attempts_then_429_still_uniform(
        self, migrated_db: None, client: TestClient, redis_available: bool
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        bogus_email = f"nobody-{uuid.uuid4().hex}@example.com"

        for _ in range(_AUTH_CAPACITY):
            response = client.post("/v1/auth/password-reset", json={"email": bogus_email})
            assert response.status_code == 202

        over_limit = client.post("/v1/auth/password-reset", json={"email": bogus_email})

        # Still non-enumerating at the rate-limit boundary itself: a 429
        # here, never a different status/shape hinting the email exists.
        assert over_limit.status_code == 429
        assert int(over_limit.headers["retry-after"]) >= 1


def _fake_put_object(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkeypatch `app.services.media.put_object` so uploads succeed without a real S3.

    Mirrors `test_media_api.py`'s identical helper -- this suite only
    cares that `Depends(enforce_media_upload_rate_limit)` is actually
    wired onto the route, not the upload's own behavior.
    """

    async def _fake(
        client: object, *, bucket: str, key: str, body: bytes, content_type: str
    ) -> None:
        return None

    monkeypatch.setattr("app.services.media.put_object", _fake)


class TestMediaUploadRateLimit:
    """Regression test for T28 code review Minor #4.

    `POST /v1/media` wires `Depends(enforce_media_upload_rate_limit)`
    (`RateLimitScope.MEDIA_UPLOAD`, 20/min per user) same as every other
    rate-limited route in this suite -- without a test asserting the `429`
    end-to-end, a future refactor could silently drop the `Depends()` from
    the route signature and nothing would catch it.
    """

    async def test_burst_capacity_then_429_with_retry_after(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        _, token = await _authed_user(db_session)
        _fake_put_object(monkeypatch)
        png_bytes = _minimal_png_bytes()

        for _ in range(_MEDIA_UPLOAD_CAPACITY):
            response = client.post(
                "/v1/media",
                headers=_auth_header(token),
                data={
                    "declared_content_type": "image/png",
                    "kind": "image",
                    "filename": "screenshot.png",
                },
                files={"file": ("screenshot.png", png_bytes, "image/png")},
            )
            assert response.status_code == 201

        over_limit = client.post(
            "/v1/media",
            headers=_auth_header(token),
            data={
                "declared_content_type": "image/png",
                "kind": "image",
                "filename": "one-too-many.png",
            },
            files={"file": ("one-too-many.png", png_bytes, "image/png")},
        )

        assert over_limit.status_code == 429
        assert over_limit.headers["content-type"] == "application/problem+json"
        assert int(over_limit.headers["retry-after"]) >= 1
        body = over_limit.json()
        assert body["status"] == 429
        assert "correlation_id" in body
