"""Integration tests for `GET`/`PATCH /v1/me` (T17, frozen contract).

Exercises the real stack (Postgres + Redis, both skipped when
unreachable) via `require_auth`, matching the pattern established by
`tests/test_deps_auth.py` for T10.
"""

from __future__ import annotations

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


def _settings() -> Settings:
    return Settings(**{k.lower(): v for k, v in REQUIRED_ENV.items()})  # type: ignore[arg-type]


async def _make_user(
    db: AsyncSession,
    *,
    is_active: bool = True,
    is_system_admin: bool = False,
    first_name: str = "Test",
    last_name: str = "User",
    avatar_url: str | None = None,
) -> User:
    unique = generate_id().hex[-12:]
    user = User(
        id=generate_id(),
        username=f"user{unique}",
        email=f"{unique}@example.com",
        hashed_password=_PLACEHOLDER_HASH_VALUE,
        first_name=first_name,
        last_name=last_name,
        avatar_url=avatar_url,
        is_active=is_active,
        is_system_admin=is_system_admin,
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


async def _authed(db: AsyncSession, **user_kwargs: object) -> tuple[User, dict[str, str]]:
    user = await _make_user(db, **user_kwargs)  # type: ignore[arg-type]
    session = await _make_session(db, user)
    await db.commit()
    return user, _auth_header(_bearer_token_for(user, session))


class TestGetMe:
    async def test_returns_profile_without_password_hash(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        user, headers = await _authed(db_session, first_name="Alice", last_name="Ng")

        response = client.get("/v1/me", headers=headers)

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(user.id)
        assert body["username"] == user.username
        assert body["email"] == user.email
        assert body["first_name"] == "Alice"
        assert body["last_name"] == "Ng"
        assert body["role"] == "user"
        assert body["is_active"] is True
        assert "hashed_password" not in body
        assert "password" not in body

    async def test_role_reflects_system_admin_flag(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        _, headers = await _authed(db_session, is_system_admin=True)

        response = client.get("/v1/me", headers=headers)

        assert response.status_code == 200
        assert response.json()["role"] == "system_admin"

    async def test_no_avatar_url_returns_null_for_initials_fallback(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        _, headers = await _authed(db_session, avatar_url=None, first_name="Bo", last_name="Zed")

        response = client.get("/v1/me", headers=headers)

        body = response.json()
        assert body["avatar_url"] is None
        assert body["first_name"] and body["last_name"]

    async def test_missing_auth_is_401_problem_json(
        self, migrated_db: None, client: TestClient
    ) -> None:
        response = client.get("/v1/me")

        assert response.status_code == 401
        assert response.headers["content-type"] == "application/problem+json"


class TestPatchMe:
    async def test_updates_first_last_name_and_avatar(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        _, headers = await _authed(db_session)

        response = client.patch(
            "/v1/me",
            headers=headers,
            json={
                "first_name": "Alice",
                "last_name": "Ng",
                "avatar_url": "https://cdn.example/av/opaque-key",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["first_name"] == "Alice"
        assert body["last_name"] == "Ng"
        assert body["avatar_url"] == "https://cdn.example/av/opaque-key"

    async def test_persists_across_a_subsequent_get(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        _, headers = await _authed(db_session)

        patch_response = client.patch("/v1/me", headers=headers, json={"first_name": "Renamed"})
        assert patch_response.status_code == 200

        get_response = client.get("/v1/me", headers=headers)
        assert get_response.json()["first_name"] == "Renamed"

    async def test_partial_update_leaves_other_fields_untouched(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        _, headers = await _authed(
            db_session, first_name="Alice", last_name="Ng", avatar_url="https://old"
        )

        response = client.patch("/v1/me", headers=headers, json={"last_name": "Wong"})

        assert response.status_code == 200
        body = response.json()
        assert body["first_name"] == "Alice"
        assert body["last_name"] == "Wong"
        assert body["avatar_url"] == "https://old"

    async def test_same_body_twice_is_idempotent(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        _, headers = await _authed(db_session)
        payload = {"first_name": "Alice", "last_name": "Ng"}

        first = client.patch("/v1/me", headers=headers, json=payload)
        second = client.patch("/v1/me", headers=headers, json=payload)

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["first_name"] == second.json()["first_name"] == "Alice"

    async def test_changing_email_is_400(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        _, headers = await _authed(db_session)

        response = client.patch(
            "/v1/me", headers=headers, json={"email": "someone-else@example.com"}
        )

        assert response.status_code == 400
        assert response.headers["content-type"] == "application/problem+json"

    async def test_changing_username_is_400(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        _, headers = await _authed(db_session)

        response = client.patch("/v1/me", headers=headers, json={"username": "new-handle"})

        assert response.status_code == 400
        assert response.headers["content-type"] == "application/problem+json"

    async def test_resending_the_same_email_is_not_rejected(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        user, headers = await _authed(db_session)

        response = client.patch("/v1/me", headers=headers, json={"email": user.email})

        assert response.status_code == 200

    async def test_empty_first_name_is_422(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        _, headers = await _authed(db_session)

        response = client.patch("/v1/me", headers=headers, json={"first_name": ""})

        assert response.status_code == 422
        assert response.headers["content-type"] == "application/problem+json"

    async def test_whitespace_only_last_name_is_422(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        _, headers = await _authed(db_session)

        response = client.patch("/v1/me", headers=headers, json={"last_name": "   "})

        assert response.status_code == 422

    async def test_missing_auth_is_401(self, migrated_db: None, client: TestClient) -> None:
        response = client.patch("/v1/me", json={"first_name": "Alice"})

        assert response.status_code == 401
        assert response.headers["content-type"] == "application/problem+json"

    async def test_cannot_update_another_users_profile(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        """`/v1/me` is always self — there is no `user_id` path param to spoof."""

        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6379")

        victim, _ = await _authed(db_session, first_name="Victim")
        _, attacker_headers = await _authed(db_session, first_name="Attacker")

        response = client.patch("/v1/me", headers=attacker_headers, json={"first_name": "Hijacked"})
        assert response.status_code == 200
        assert response.json()["id"] != str(victim.id)

        get_victim = client.get("/v1/me", headers=attacker_headers)
        assert get_victim.json()["first_name"] == "Hijacked"
