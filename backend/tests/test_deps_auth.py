"""Integration tests for `require_auth` (T10) via the real `/v1/auth/sessions` routes.

Exercises the full stack end-to-end (real Postgres + real Redis, both
skipped when unreachable): JWT decode (T09), the Redis-cached/Postgres-
fallback revocation check (`app.services.session_revocation`), and the
fresh-every-request `users.is_active` gate — covering every scenario T10
calls out explicitly: valid, revoked, expired, deactivated-user, and
cold-cache fallback (including a genuine Redis outage).
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.ids import generate_id
from app.core.jwt import create_access_token
from app.models.session import Session
from app.models.user import User
from tests.conftest import REQUIRED_ENV

pytestmark = pytest.mark.usefixtures("configured_env")

_PLACEHOLDER_HASH_VALUE = "not-a-real-hash-value"


def _find_closed_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _settings() -> Settings:
    return Settings(**{k.lower(): v for k, v in REQUIRED_ENV.items()})  # type: ignore[arg-type]


async def _make_user(db: AsyncSession, *, is_active: bool = True) -> User:
    # Trailing hex digits (not the leading, millisecond-timestamp-derived
    # ones) so two calls made microseconds apart in the same test still
    # produce distinct usernames — `username` is capped at 32 chars
    # (`ck_users_username_len`), so `"user" + 12 hex chars` stays well
    # under that.
    unique = generate_id().hex[-12:]
    user = User(
        id=generate_id(),
        username=f"user{unique}",
        email=f"{unique}@example.com",
        hashed_password=_PLACEHOLDER_HASH_VALUE,
        first_name="Test",
        last_name="User",
        is_active=is_active,
        is_system_admin=False,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_session(
    db: AsyncSession, user: User, *, revoked: bool = False, expired: bool = False
) -> Session:
    now = datetime.now(UTC)
    session = Session(
        id=generate_id(),
        user_id=user.id,
        refresh_token_hash=f"hash-{generate_id()}",
        issued_at=now,
        expires_at=(now - timedelta(days=1)) if expired else (now + timedelta(days=30)),
        revoked_at=now if revoked else None,
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


@pytest.fixture
def broken_redis_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A `TestClient` whose Redis is genuinely unreachable (closed port).

    Simulates a real Redis outage rather than mocking the revocation
    module, so this exercises the actual `redis_fail_closed` ->
    `RedisUnavailableError` -> Postgres-fallback path end-to-end.
    """

    from app.core.config import get_settings
    from app.db.redis import get_redis_client
    from app.main import create_app

    closed_port = _find_closed_port()
    monkeypatch.setenv("REDIS_URL", f"redis://127.0.0.1:{closed_port}/0")
    get_settings.cache_clear()
    get_redis_client.cache_clear()

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client

    get_settings.cache_clear()
    get_redis_client.cache_clear()


class TestRequireAuthValid:
    async def test_valid_session_is_authorized(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        user = await _make_user(db_session)
        session = await _make_session(db_session, user)
        await db_session.commit()

        response = client.get(
            "/v1/auth/sessions", headers=_auth_header(_bearer_token_for(user, session))
        )

        assert response.status_code == 200
        body = response.json()
        assert body["items"][0]["session_id"] == str(session.id)
        assert body["items"][0]["current"] is True

    async def test_missing_authorization_header_is_401_problem_json(
        self, migrated_db: None, client: TestClient
    ) -> None:
        response = client.get("/v1/auth/sessions")

        assert response.status_code == 401
        assert response.headers["content-type"] == "application/problem+json"
        body = response.json()
        assert body["status"] == 401
        assert "correlation_id" in body


class TestRequireAuthRevoked:
    async def test_revoked_session_fails_with_401(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        user = await _make_user(db_session)
        session = await _make_session(db_session, user, revoked=True)
        await db_session.commit()

        response = client.get(
            "/v1/auth/sessions", headers=_auth_header(_bearer_token_for(user, session))
        )

        assert response.status_code == 401
        assert response.headers["content-type"] == "application/problem+json"

    async def test_revoking_via_the_api_fails_the_very_next_request(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        """`DELETE .../sessions/{id}` busts the cache so revocation is immediate."""

        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        user = await _make_user(db_session)
        session = await _make_session(db_session, user)
        await db_session.commit()
        token = _bearer_token_for(user, session)

        # First request populates the (cold) revocation cache as "active".
        first = client.get("/v1/auth/sessions", headers=_auth_header(token))
        assert first.status_code == 200

        delete_response = client.delete(
            f"/v1/auth/sessions/{session.id}", headers=_auth_header(token)
        )
        assert delete_response.status_code == 204

        second = client.get("/v1/auth/sessions", headers=_auth_header(token))
        assert second.status_code == 401


class TestRequireAuthExpired:
    async def test_expired_session_fails_with_401(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        user = await _make_user(db_session)
        session = await _make_session(db_session, user, expired=True)
        await db_session.commit()

        response = client.get(
            "/v1/auth/sessions", headers=_auth_header(_bearer_token_for(user, session))
        )

        assert response.status_code == 401


class TestRequireAuthDeactivatedUser:
    async def test_deactivated_user_fails_with_401_even_with_a_valid_session(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        user = await _make_user(db_session, is_active=True)
        session = await _make_session(db_session, user)
        await db_session.commit()
        token = _bearer_token_for(user, session)

        # First request while active — proves the session/cache side is fine.
        first = client.get("/v1/auth/sessions", headers=_auth_header(token))
        assert first.status_code == 200

        # Deactivate directly (no admin-deactivate endpoint exists yet —
        # T27/out of scope); `is_active` is intentionally never cached, so
        # this alone must be enough to fail the very next request.
        user.is_active = False
        db_session.add(user)
        await db_session.commit()

        second = client.get("/v1/auth/sessions", headers=_auth_header(token))
        assert second.status_code == 401


class TestRequireAuthColdCacheFallback:
    async def test_first_request_is_a_cold_cache_and_still_succeeds(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        user = await _make_user(db_session)
        session = await _make_session(db_session, user)
        await db_session.commit()

        # No prior request has ever touched the revocation cache for this
        # brand-new session id — this is a cold-cache lookup by construction.
        response = client.get(
            "/v1/auth/sessions", headers=_auth_header(_bearer_token_for(user, session))
        )

        assert response.status_code == 200

    async def test_redis_outage_falls_back_to_postgres_and_preserves_correctness(
        self,
        migrated_db: None,
        broken_redis_client: TestClient,
        db_session: AsyncSession,
    ) -> None:
        """Redis-down: latency up, correctness preserved (ADR-0006)."""

        user = await _make_user(db_session)
        active_session = await _make_session(db_session, user)
        revoked_session = await _make_session(db_session, user, revoked=True)
        await db_session.commit()

        active_response = broken_redis_client.get(
            "/v1/auth/sessions",
            headers=_auth_header(_bearer_token_for(user, active_session)),
        )
        revoked_response = broken_redis_client.get(
            "/v1/auth/sessions",
            headers=_auth_header(_bearer_token_for(user, revoked_session)),
        )

        assert active_response.status_code == 200
        assert revoked_response.status_code == 401


class TestSessionsListAndRevokeEndpoints:
    async def test_delete_unknown_session_is_404(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        user = await _make_user(db_session)
        session = await _make_session(db_session, user)
        await db_session.commit()

        response = client.delete(
            f"/v1/auth/sessions/{generate_id()}",
            headers=_auth_header(_bearer_token_for(user, session)),
        )

        assert response.status_code == 404
        assert response.headers["content-type"] == "application/problem+json"

    async def test_delete_another_users_session_is_403(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        owner = await _make_user(db_session)
        other = await _make_user(db_session)
        owner_session = await _make_session(db_session, owner)
        other_session = await _make_session(db_session, other)
        await db_session.commit()

        response = client.delete(
            f"/v1/auth/sessions/{owner_session.id}",
            headers=_auth_header(_bearer_token_for(other, other_session)),
        )

        assert response.status_code == 403
        assert response.headers["content-type"] == "application/problem+json"

    async def test_delete_is_idempotent_on_an_already_revoked_session(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        user = await _make_user(db_session)
        session = await _make_session(db_session, user)
        await db_session.commit()
        token = _bearer_token_for(user, session)

        first = client.delete(f"/v1/auth/sessions/{session.id}", headers=_auth_header(token))
        assert first.status_code == 204

        # The token itself is now for a revoked session, so re-issue a
        # fresh one bound to a *second*, still-active session owned by the
        # same user purely to authenticate the second delete call against
        # the now-revoked `session.id`.
        second_session = await _make_session(db_session, user)
        await db_session.commit()
        second_token = _bearer_token_for(user, second_session)

        second = client.delete(
            f"/v1/auth/sessions/{session.id}", headers=_auth_header(second_token)
        )
        assert second.status_code == 204
