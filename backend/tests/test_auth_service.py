"""Unit/integration tests for `app.services.auth` (T15).

Exercises `authenticate_and_login` and `refresh_session` directly against
a real Postgres session (`db_session` fixture), independent of the HTTP
layer — the HTTP-layer status-code mapping is covered separately in
`tests/test_auth_endpoints.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.ids import generate_id
from app.core.security import hash_password
from app.core.token_hash import hash_refresh_token
from app.models.session import Session
from app.models.user import User
from app.services.auth import (
    AccountDeactivatedError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    MustChangePasswordError,
    authenticate_and_login,
    refresh_session,
)
from tests.conftest import REQUIRED_ENV

pytestmark = pytest.mark.usefixtures("configured_env")

_TEST_CREDENTIAL = "correct-horse-1"


def _settings() -> Settings:
    return Settings(**{k.lower(): v for k, v in REQUIRED_ENV.items()})  # type: ignore[arg-type]


async def _make_user(
    db: AsyncSession,
    *,
    email: str = "alice@example.com",
    password: str = _TEST_CREDENTIAL,
    is_active: bool = True,
    must_change_password: bool = False,
) -> User:
    unique = generate_id().hex[-12:]
    user = User(
        id=generate_id(),
        username=f"user{unique}",
        email=email,
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


class TestAuthenticateAndLogin:
    async def test_valid_credentials_mint_a_session_and_tokens(
        self, db_session: AsyncSession
    ) -> None:
        user = await _make_user(db_session)
        await db_session.commit()

        result = await authenticate_and_login(
            db_session, email=user.email, password=_TEST_CREDENTIAL, settings=_settings()
        )
        await db_session.commit()

        assert result.user.id == user.id
        assert result.access_token
        assert result.expires_in == 900
        assert result.refresh_token

    async def test_login_is_case_insensitive_on_email(self, db_session: AsyncSession) -> None:
        user = await _make_user(db_session, email="Alice@Example.com")
        await db_session.commit()

        result = await authenticate_and_login(
            db_session, email="alice@example.com", password=_TEST_CREDENTIAL, settings=_settings()
        )

        assert result.user.id == user.id

    async def test_unknown_email_raises_invalid_credentials(self, db_session: AsyncSession) -> None:
        with pytest.raises(InvalidCredentialsError):
            await authenticate_and_login(
                db_session,
                email="nobody@example.com",
                password=_TEST_CREDENTIAL,
                settings=_settings(),
            )

    async def test_wrong_password_raises_invalid_credentials(
        self, db_session: AsyncSession
    ) -> None:
        user = await _make_user(db_session)
        await db_session.commit()

        with pytest.raises(InvalidCredentialsError):
            await authenticate_and_login(
                db_session, email=user.email, password="wrong-password-1", settings=_settings()
            )

    async def test_deactivated_account_raises_account_deactivated(
        self, db_session: AsyncSession
    ) -> None:
        user = await _make_user(db_session, is_active=False)
        await db_session.commit()

        with pytest.raises(AccountDeactivatedError):
            await authenticate_and_login(
                db_session, email=user.email, password=_TEST_CREDENTIAL, settings=_settings()
            )

    async def test_must_change_password_blocks_login(self, db_session: AsyncSession) -> None:
        """ADR-0009 compensating control: a flagged account cannot obtain a
        normal session via login, even with fully correct credentials."""

        user = await _make_user(db_session, must_change_password=True)
        await db_session.commit()

        with pytest.raises(MustChangePasswordError):
            await authenticate_and_login(
                db_session, email=user.email, password=_TEST_CREDENTIAL, settings=_settings()
            )

    async def test_must_change_password_check_runs_after_deactivation_check(
        self, db_session: AsyncSession
    ) -> None:
        """A deactivated *and* must-change-password account still surfaces
        as deactivated first (contract ordering: credentials -> is_active ->
        must_change_password)."""

        user = await _make_user(db_session, is_active=False, must_change_password=True)
        await db_session.commit()

        with pytest.raises(AccountDeactivatedError):
            await authenticate_and_login(
                db_session, email=user.email, password=_TEST_CREDENTIAL, settings=_settings()
            )


class TestRefreshSession:
    async def test_valid_refresh_token_rotates_and_slides_expiry(
        self, db_session: AsyncSession
    ) -> None:
        user = await _make_user(db_session)
        await db_session.commit()
        login_result = await authenticate_and_login(
            db_session, email=user.email, password=_TEST_CREDENTIAL, settings=_settings()
        )
        await db_session.commit()

        refreshed = await refresh_session(
            db_session, raw_refresh_token=login_result.refresh_token, settings=_settings()
        )
        await db_session.commit()

        assert refreshed.access_token
        assert refreshed.refresh_token
        assert refreshed.refresh_token != login_result.refresh_token
        assert refreshed.expires_in == 900

    async def test_old_refresh_token_is_invalid_after_rotation(
        self, db_session: AsyncSession
    ) -> None:
        user = await _make_user(db_session)
        await db_session.commit()
        login_result = await authenticate_and_login(
            db_session, email=user.email, password=_TEST_CREDENTIAL, settings=_settings()
        )
        await db_session.commit()

        await refresh_session(
            db_session, raw_refresh_token=login_result.refresh_token, settings=_settings()
        )
        await db_session.commit()

        with pytest.raises(InvalidRefreshTokenError):
            await refresh_session(
                db_session, raw_refresh_token=login_result.refresh_token, settings=_settings()
            )

    async def test_unknown_refresh_token_raises(self, db_session: AsyncSession) -> None:
        with pytest.raises(InvalidRefreshTokenError):
            await refresh_session(
                db_session, raw_refresh_token="not-a-real-token", settings=_settings()
            )

    async def test_revoked_session_refresh_token_raises(self, db_session: AsyncSession) -> None:
        user = await _make_user(db_session)
        now = datetime.now(UTC)
        session = Session(
            id=generate_id(),
            user_id=user.id,
            refresh_token_hash=hash_refresh_token("some-raw-token"),
            issued_at=now,
            expires_at=now + timedelta(days=30),
            revoked_at=now,
        )
        db_session.add(session)
        await db_session.commit()

        with pytest.raises(InvalidRefreshTokenError):
            await refresh_session(
                db_session, raw_refresh_token="some-raw-token", settings=_settings()
            )

    async def test_expired_session_refresh_token_raises(self, db_session: AsyncSession) -> None:
        user = await _make_user(db_session)
        now = datetime.now(UTC)
        session = Session(
            id=generate_id(),
            user_id=user.id,
            refresh_token_hash=hash_refresh_token("some-other-raw-token"),
            issued_at=now - timedelta(days=31),
            expires_at=now - timedelta(days=1),
            revoked_at=None,
        )
        db_session.add(session)
        await db_session.commit()

        with pytest.raises(InvalidRefreshTokenError):
            await refresh_session(
                db_session, raw_refresh_token="some-other-raw-token", settings=_settings()
            )

    async def test_deactivated_user_refresh_token_raises(self, db_session: AsyncSession) -> None:
        user = await _make_user(db_session)
        await db_session.commit()
        login_result = await authenticate_and_login(
            db_session, email=user.email, password=_TEST_CREDENTIAL, settings=_settings()
        )
        await db_session.commit()

        user.is_active = False
        db_session.add(user)
        await db_session.commit()

        with pytest.raises(InvalidRefreshTokenError):
            await refresh_session(
                db_session, raw_refresh_token=login_result.refresh_token, settings=_settings()
            )
