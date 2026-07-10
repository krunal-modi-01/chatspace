"""Integration tests for `POST /v1/auth/login`, `/refresh`, `/logout` (T15).

Real Postgres + real Redis end-to-end (both skipped when unreachable),
mirroring the style of `tests/test_deps_auth.py`. Covers every status
code the frozen contract enumerates for these three endpoints, F10-F14,
and the ADR-0009 `must_change_password` compensating control the task
calls out as a CRITICAL requirement.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import generate_id
from app.core.security import hash_password
from app.models.session import Session
from app.models.user import User

pytestmark = pytest.mark.usefixtures("configured_env")

_TEST_CREDENTIAL = "correct-horse-1"


async def _make_user(
    db: AsyncSession,
    *,
    email: str | None = None,
    password: str = _TEST_CREDENTIAL,
    is_active: bool = True,
    must_change_password: bool = False,
) -> User:
    unique = generate_id().hex[-12:]
    user = User(
        id=generate_id(),
        username=f"user{unique}",
        # T27: a per-call unique default (not a fixed "alice@example.com"
        # literal) — `POST /v1/auth/login` is now rate-limited per
        # attempted identifier (`RateLimitScope.AUTH`, 5/5min), and this
        # module's Redis test database is not flushed between tests, so
        # every test in this file sharing one literal email would
        # eventually exhaust that single bucket and see spurious `429`s
        # instead of the status code each test is actually asserting.
        email=email or f"alice-{unique}@example.com",
        hashed_password=hash_password(password),
        first_name="A",
        last_name="Lice",
        is_active=is_active,
        is_system_admin=False,
        must_change_password=must_change_password,
    )
    db.add(user)
    await db.flush()
    return user


class TestLoginEndpoint:
    async def test_valid_credentials_return_200_with_tokens_and_user(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        user = await _make_user(db_session)
        await db_session.commit()

        response = client.post(
            "/v1/auth/login", json={"email": user.email, "password": _TEST_CREDENTIAL}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "Bearer"
        assert body["expires_in"] == 900
        assert body["access_token"]
        assert body["refresh_token"]
        assert body["user"]["id"] == str(user.id)
        assert body["user"]["email"] == user.email
        assert "hashed_password" not in body["user"]
        assert "password" not in body["user"]
        assert body["user"]["role"] == "user"

    async def test_unknown_email_is_401_uniform(
        self, migrated_db: None, client: TestClient, redis_available: bool
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        response = client.post(
            "/v1/auth/login",
            json={"email": "nobody@example.com", "password": _TEST_CREDENTIAL},
        )

        assert response.status_code == 401
        assert response.headers["content-type"] == "application/problem+json"

    async def test_wrong_password_is_401_uniform_same_body_shape_as_unknown_email(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        user = await _make_user(db_session)
        await db_session.commit()

        wrong_password_response = client.post(
            "/v1/auth/login", json={"email": user.email, "password": "totally-wrong-1"}
        )
        unknown_email_response = client.post(
            "/v1/auth/login",
            json={"email": "nobody-at-all@example.com", "password": _TEST_CREDENTIAL},
        )

        assert wrong_password_response.status_code == 401
        assert unknown_email_response.status_code == 401
        # F11: no field-level disclosure — both failure modes render the
        # exact same problem `type`/`title`/`detail`, so a caller cannot
        # tell "bad email" from "bad password" apart from the response.
        assert wrong_password_response.json()["type"] == unknown_email_response.json()["type"]
        assert wrong_password_response.json()["detail"] == unknown_email_response.json()["detail"]

    async def test_deactivated_account_is_403(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        user = await _make_user(db_session, is_active=False)
        await db_session.commit()

        response = client.post(
            "/v1/auth/login", json={"email": user.email, "password": _TEST_CREDENTIAL}
        )

        assert response.status_code == 403
        body = response.json()
        assert body["type"] == "https://chatspace.example/problems/forbidden"

    async def test_must_change_password_blocks_normal_login_with_403(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        """CRITICAL (ADR-0009 compensating control): a `must_change_password`
        account cannot obtain a normal session at login, even with fully
        correct credentials — proves the flag added by T12's migration 0002
        is not inert."""

        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        user = await _make_user(db_session, must_change_password=True)
        await db_session.commit()

        response = client.post(
            "/v1/auth/login", json={"email": user.email, "password": _TEST_CREDENTIAL}
        )

        assert response.status_code == 403
        assert response.headers["content-type"] == "application/problem+json"
        body = response.json()
        # Distinct `type` from the plain "account deactivated" 403 — a
        # tolerant client can tell the two 403s apart (documented contract
        # gap, T15 CONTRACT-GAP NOTICE, option 2).
        assert body["type"] == "https://chatspace.example/problems/must-change-password"
        assert body["status"] == 403
        assert "access_token" not in body
        assert "refresh_token" not in body

    async def test_must_change_password_login_creates_no_session_row(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        """T42 regression: the 403 must-change-password block on login must
        remain unchanged — no `sessions` row is ever created for a flagged,
        not-yet-reset account, even with fully correct credentials."""

        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        user = await _make_user(db_session, must_change_password=True)
        await db_session.commit()

        response = client.post(
            "/v1/auth/login", json={"email": user.email, "password": _TEST_CREDENTIAL}
        )

        assert response.status_code == 403
        body = response.json()
        assert "access_token" not in body
        assert "refresh_token" not in body

        result = await db_session.execute(select(Session).where(Session.user_id == user.id))
        assert result.scalars().all() == []

    async def test_malformed_body_is_400(
        self, migrated_db: None, client: TestClient, redis_available: bool
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        response = client.post("/v1/auth/login", json={"email": "alice@example.com"})

        assert response.status_code == 400
        assert response.headers["content-type"] == "application/problem+json"

    async def test_non_json_body_is_400(
        self, migrated_db: None, client: TestClient, redis_available: bool
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        response = client.post(
            "/v1/auth/login",
            content=b"not-json-at-all",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 400


class TestRefreshEndpoint:
    async def test_valid_refresh_token_returns_200_with_rotated_token(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        user = await _make_user(db_session)
        await db_session.commit()

        login_response = client.post(
            "/v1/auth/login", json={"email": user.email, "password": _TEST_CREDENTIAL}
        )
        refresh_token = login_response.json()["refresh_token"]

        response = client.post("/v1/auth/refresh", json={"refresh_token": refresh_token})

        assert response.status_code == 200
        body = response.json()
        assert body["access_token"]
        assert body["refresh_token"]
        assert body["refresh_token"] != refresh_token
        assert body["expires_in"] == 900

    async def test_revoked_refresh_token_is_401(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        """F12: a revoked refresh token fails refresh with 401."""

        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        user = await _make_user(db_session)
        await db_session.commit()

        login_response = client.post(
            "/v1/auth/login", json={"email": user.email, "password": _TEST_CREDENTIAL}
        )
        access_token = login_response.json()["access_token"]
        refresh_token = login_response.json()["refresh_token"]

        logout_response = client.post(
            "/v1/auth/logout", headers={"Authorization": f"Bearer {access_token}"}
        )
        assert logout_response.status_code == 204

        response = client.post("/v1/auth/refresh", json={"refresh_token": refresh_token})

        assert response.status_code == 401
        assert response.headers["content-type"] == "application/problem+json"

    async def test_unknown_refresh_token_is_401(
        self, migrated_db: None, client: TestClient, redis_available: bool
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        response = client.post(
            "/v1/auth/refresh", json={"refresh_token": "not-a-real-refresh-token"}
        )

        assert response.status_code == 401

    async def test_malformed_body_is_400(
        self, migrated_db: None, client: TestClient, redis_available: bool
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        response = client.post("/v1/auth/refresh", json={})

        assert response.status_code == 400


class TestLogoutEndpoint:
    async def test_logout_revokes_current_session_only(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        """F14: logout revokes only the current session, other sessions unaffected."""

        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        user = await _make_user(db_session)
        await db_session.commit()

        first_login = client.post(
            "/v1/auth/login", json={"email": user.email, "password": _TEST_CREDENTIAL}
        )
        second_login = client.post(
            "/v1/auth/login", json={"email": user.email, "password": _TEST_CREDENTIAL}
        )
        first_token = first_login.json()["access_token"]
        second_token = second_login.json()["access_token"]

        logout_response = client.post(
            "/v1/auth/logout", headers={"Authorization": f"Bearer {first_token}"}
        )
        assert logout_response.status_code == 204

        # First session is now dead.
        first_sessions_response = client.get(
            "/v1/auth/sessions", headers={"Authorization": f"Bearer {first_token}"}
        )
        assert first_sessions_response.status_code == 401

        # Second session, from a separate login, is untouched.
        second_sessions_response = client.get(
            "/v1/auth/sessions", headers={"Authorization": f"Bearer {second_token}"}
        )
        assert second_sessions_response.status_code == 200

    async def test_logout_without_auth_is_401(
        self, migrated_db: None, client: TestClient, redis_available: bool
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        response = client.post("/v1/auth/logout")

        assert response.status_code == 401
        assert response.headers["content-type"] == "application/problem+json"

    async def test_logout_ignores_request_body(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        user = await _make_user(db_session)
        await db_session.commit()

        login_response = client.post(
            "/v1/auth/login", json={"email": user.email, "password": _TEST_CREDENTIAL}
        )
        access_token = login_response.json()["access_token"]

        response = client.post(
            "/v1/auth/logout",
            headers={"Authorization": f"Bearer {access_token}"},
            json={},
        )

        assert response.status_code == 204
