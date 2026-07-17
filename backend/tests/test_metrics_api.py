"""Integration tests for `GET /v1/internal/metrics` (T39).

Exercises the real route end-to-end against Postgres + Redis (both
skipped when unreachable), mirroring `tests/test_admin_api.py`'s
system-admin auth setup.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics as metrics_module
from app.core.ids import generate_id
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.models.session import Session
from app.models.user import User
from tests.conftest import REQUIRED_ENV

pytestmark = pytest.mark.usefixtures("configured_env")


def _password() -> str:
    """Not a real secret — a fixed non-production credential for test fixtures only."""

    return "correct-horse-1"


def _settings() -> object:
    from app.core.config import Settings

    return Settings(**{k.lower(): v for k, v in REQUIRED_ENV.items()})  # type: ignore[arg-type]


async def _make_user(db: AsyncSession, *, is_system_admin: bool = False) -> User:
    unique = generate_id().hex[-12:]
    user = User(
        id=generate_id(),
        username=f"user{unique}",
        email=f"{unique}@example.com",
        hashed_password=hash_password(_password()),
        first_name="Test",
        last_name="User",
        is_active=True,
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


async def _admin_token(db: AsyncSession) -> str:
    admin = await _make_user(db, is_system_admin=True)
    session = await _make_session(db, admin)
    await db.commit()
    return _bearer_token_for(admin, session)


async def _member_token(db: AsyncSession) -> str:
    user = await _make_user(db, is_system_admin=False)
    session = await _make_session(db, user)
    await db.commit()
    return _bearer_token_for(user, session)


class TestMetricsEndpointAuth:
    async def test_requires_authentication(
        self, migrated_db: None, client: TestClient, redis_available: bool
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        response = client.get("/v1/internal/metrics")

        assert response.status_code == 401

    async def test_rejects_non_system_admin(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        bearer = await _member_token(db_session)

        response = client.get("/v1/internal/metrics", headers=_auth_header(bearer))

        assert response.status_code == 403


class TestMetricsEndpointShape:
    async def test_system_admin_gets_a_metrics_snapshot(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        metrics_module.reset_metrics()
        bearer = await _admin_token(db_session)

        response = client.get("/v1/internal/metrics", headers=_auth_header(bearer))

        assert response.status_code == 200
        body = response.json()
        assert set(body) >= {"counters", "gauges", "histograms", "db_pool", "redis_available"}
        assert body["redis_available"] is True
        assert set(body["db_pool"]) == {"size", "checked_out", "overflow"}

    async def test_never_leaks_password_material(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        bearer = await _admin_token(db_session)

        response = client.get("/v1/internal/metrics", headers=_auth_header(bearer))

        assert "password" not in response.text.lower()
        assert "hashed_password" not in response.text.lower()
