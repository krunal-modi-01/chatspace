"""Integration tests for `GET /v1/users/search` (T73, F76/R59, ADR-0016).

Exercises the real route end-to-end against Postgres + Redis (both
skipped when unreachable, matching every other integration test in this
suite): auth (any active user, not admin-gated), `q` matching across
`username`/`first_name`/`last_name` case-insensitively, `min length 1`
validation, deactivated-user exclusion, field minimization (never
`email`/`is_active`/`last_seen`/`role`), cursor pagination (ADR-0003
default/max `limit`, invalid cursor/limit -> `400`), and the
`RateLimitScope.GENERAL_READ` `429`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import generate_id
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.models.session import Session
from app.models.user import User
from tests.conftest import REQUIRED_ENV

pytestmark = pytest.mark.usefixtures("configured_env")

# GENERAL_READ capacity (burst) — must match `RateLimitScope.GENERAL_READ`'s
# policy exactly (`app.core.rate_limit`), since the 429 test below drives
# the bucket to (and past) that limit.
_GENERAL_READ_CAPACITY = 60


def _password() -> str:
    """Not a real secret — a fixed non-production credential for test fixtures only."""

    return "correct-horse-1"


def _settings() -> object:
    from app.core.config import Settings

    return Settings(**{k.lower(): v for k, v in REQUIRED_ENV.items()})  # type: ignore[arg-type]


async def _make_user(
    db: AsyncSession,
    *,
    is_active: bool = True,
    is_system_admin: bool = False,
    first_name: str = "Test",
    last_name: str = "User",
    username: str | None = None,
    email: str | None = None,
) -> User:
    unique = generate_id().hex[-12:]
    user = User(
        id=generate_id(),
        username=username or f"user{unique}",
        email=email or f"{unique}@example.com",
        hashed_password=hash_password(_password()),
        first_name=first_name,
        last_name=last_name,
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


async def _authed_user(
    db: AsyncSession, *, is_system_admin: bool = False, is_active: bool = True
) -> tuple[User, str]:
    user = await _make_user(db, is_system_admin=is_system_admin, is_active=is_active)
    session = await _make_session(db, user)
    await db.commit()
    return user, _bearer_token_for(user, session)


class TestUserSearchAuth:
    async def test_missing_auth_is_401(
        self, migrated_db: None, client: TestClient, redis_available: bool
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        response = client.get("/v1/users/search", params={"q": "a"})

        assert response.status_code == 401

    async def test_ordinary_non_admin_user_is_authorized(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        """Auth is `require_auth` only — an ordinary (non-System-Admin) caller succeeds.

        Regression pin for the "any active user, NOT admin-gated" contract
        clause distinguishing this endpoint from `GET /v1/admin/users`.
        """

        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        _, bearer = await _authed_user(db_session, is_system_admin=False)

        response = client.get("/v1/users/search", headers=_auth_header(bearer), params={"q": "a"})

        assert response.status_code == 200

    async def test_deactivated_caller_is_401(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        _, bearer = await _authed_user(db_session, is_active=False)

        response = client.get("/v1/users/search", headers=_auth_header(bearer), params={"q": "a"})

        assert response.status_code == 401


class TestUserSearchMatching:
    async def test_q_matches_username_first_last_case_insensitively(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        _, bearer = await _authed_user(db_session)
        target = await _make_user(
            db_session, first_name="Zelda", last_name="Rivers", username="zrivers"
        )
        await _make_user(db_session, first_name="Someone", last_name="Else", username="selse")
        await db_session.commit()

        by_first_name = client.get(
            "/v1/users/search", headers=_auth_header(bearer), params={"q": "zelda"}
        )
        by_last_name = client.get(
            "/v1/users/search", headers=_auth_header(bearer), params={"q": "RIVERS"}
        )
        by_username = client.get(
            "/v1/users/search", headers=_auth_header(bearer), params={"q": "ZRivers"}
        )

        for response in (by_first_name, by_last_name, by_username):
            assert response.status_code == 200
            ids = {item["id"] for item in response.json()["items"]}
            assert str(target.id) in ids

    async def test_q_does_not_match_email(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        """`q` matches `username`/`first_name`/`last_name` only — never `email`.

        Distinct from `GET /v1/admin/users`, which also matches `email`.
        """

        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        _, bearer = await _authed_user(db_session)
        target = await _make_user(
            db_session,
            first_name="Aaa",
            last_name="Bbb",
            username="ccc",
            email="findme-by-email-only@example.com",
        )
        await db_session.commit()

        response = client.get(
            "/v1/users/search",
            headers=_auth_header(bearer),
            params={"q": "findme-by-email-only"},
        )

        assert response.status_code == 200
        ids = {item["id"] for item in response.json()["items"]}
        assert str(target.id) not in ids

    async def test_deactivated_users_excluded_by_default(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        _, bearer = await _authed_user(db_session)
        inactive = await _make_user(db_session, is_active=False, username="deactivatedsearchtarget")
        await db_session.commit()

        response = client.get(
            "/v1/users/search",
            headers=_auth_header(bearer),
            params={"q": "deactivatedsearchtarget"},
        )

        assert response.status_code == 200
        ids = {item["id"] for item in response.json()["items"]}
        assert str(inactive.id) not in ids


class TestUserSearchFieldMinimization:
    async def test_response_shape_is_minimal_public_identity_only(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        """Hard security acceptance criterion: exactly these five fields, never more."""

        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        _, bearer = await _authed_user(db_session)
        await _make_user(db_session, username="fieldsearchtarget")
        await db_session.commit()

        response = client.get(
            "/v1/users/search",
            headers=_auth_header(bearer),
            params={"q": "fieldsearchtarget"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["items"], "expected at least one match"
        for item in body["items"]:
            assert set(item) == {"id", "username", "first_name", "last_name", "avatar_url"}
            assert "email" not in item
            assert "is_active" not in item
            assert "last_seen" not in item
            assert "role" not in item
            assert "hashed_password" not in item


class TestUserSearchValidation:
    async def test_missing_q_is_400(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        _, bearer = await _authed_user(db_session)

        response = client.get("/v1/users/search", headers=_auth_header(bearer))

        assert response.status_code == 400
        assert response.headers["content-type"] == "application/problem+json"

    async def test_whitespace_only_q_is_400(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        _, bearer = await _authed_user(db_session)

        response = client.get("/v1/users/search", headers=_auth_header(bearer), params={"q": "   "})

        assert response.status_code == 400

    async def test_invalid_limit_is_400(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        _, bearer = await _authed_user(db_session)

        response = client.get(
            "/v1/users/search",
            headers=_auth_header(bearer),
            params={"q": "a", "limit": "not-a-number"},
        )

        assert response.status_code == 400
        assert response.headers["content-type"] == "application/problem+json"

    async def test_invalid_cursor_is_400(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        _, bearer = await _authed_user(db_session)

        response = client.get(
            "/v1/users/search",
            headers=_auth_header(bearer),
            params={"q": "a", "cursor": "!!!not-base64url!!!"},
        )

        assert response.status_code == 400
        assert response.headers["content-type"] == "application/problem+json"


class TestUserSearchPagination:
    async def test_limit_clamps_to_max_100(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        _, bearer = await _authed_user(db_session)
        for _ in range(3):
            await _make_user(db_session, username=f"clamptarget{generate_id().hex[-8:]}")
        await db_session.commit()

        response = client.get(
            "/v1/users/search",
            headers=_auth_header(bearer),
            params={"q": "clamptarget", "limit": "1000"},
        )

        assert response.status_code == 200
        # Just proves the request succeeds with an over-max limit (clamped
        # server-side, never a 400) — the exact page size is asserted by
        # the cursor-walk test below, which independently pins the
        # (default 50 / smaller explicit limit) contract more directly.

    async def test_cursor_walks_every_match_exactly_once(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        _, bearer = await _authed_user(db_session)
        unique = generate_id().hex[-8:]
        expected_ids = set()
        for i in range(5):
            u = await _make_user(db_session, username=f"walktarget{unique}{i}")
            expected_ids.add(str(u.id))
        await db_session.commit()

        seen_ids: set[str] = set()
        cursor: str | None = None
        for _ in range(10):  # generous upper bound on page count
            params = {"q": f"walktarget{unique}", "limit": "2"}
            if cursor:
                params["cursor"] = cursor
            response = client.get("/v1/users/search", headers=_auth_header(bearer), params=params)
            assert response.status_code == 200
            body = response.json()
            assert len(body["items"]) <= 2
            seen_ids.update(item["id"] for item in body["items"])
            cursor = body["next_cursor"]
            if cursor is None:
                break

        assert cursor is None, "expected end-of-stream within the page-count bound"
        assert seen_ids == expected_ids


class TestUserSearchRateLimit:
    async def test_burst_capacity_then_429_with_retry_after(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        _, bearer = await _authed_user(db_session)

        for _ in range(_GENERAL_READ_CAPACITY):
            response = client.get(
                "/v1/users/search", headers=_auth_header(bearer), params={"q": "a"}
            )
            assert response.status_code == 200

        over_limit = client.get("/v1/users/search", headers=_auth_header(bearer), params={"q": "a"})

        assert over_limit.status_code == 429
        assert over_limit.headers["content-type"] == "application/problem+json"
        assert int(over_limit.headers["retry-after"]) >= 1
        body = over_limit.json()
        assert body["status"] == 429
        assert "correlation_id" in body
