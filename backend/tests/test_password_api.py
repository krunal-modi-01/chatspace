"""Integration tests for `/v1/auth/password*` (T16, frozen contract).

Exercises the real routes end-to-end against Postgres + Redis (both
skipped when unreachable): the uniform non-enumerating `202` on
password-reset request (F15), the "only latest token validates" sweep
(F17), the `410` on a stale/used/superseded token, the `422` policy
gate, and the session-revocation side effects of both reset-confirm
(F16 — revoke every other session) and password-change (F22 — keep the
initiating session, revoke the rest).

`get_email_service` is overridden with a fake so these tests never touch
a real SMTP server; the fake records enough to assert delivery was (or
was not) attempted without ever asserting on the raw token/link value
(which must never be logged or exposed in the first place).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.password as password_api
from app.core.config import Settings
from app.core.ids import generate_id
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.core.token_hash import hash_reset_token
from app.models.password_reset_token import PasswordResetToken
from app.models.session import Session
from app.models.user import User
from app.services.email import EmailDeliveryError, EmailMessageType, get_email_service
from tests.conftest import REQUIRED_ENV

pytestmark = pytest.mark.usefixtures("configured_env")

_CURRENT_PW = "correct-horse-1"
_NEW_PW = "new-correct-horse-2"


def _settings() -> Settings:
    return Settings(**{k.lower(): v for k, v in REQUIRED_ENV.items()})  # type: ignore[arg-type]


async def _make_user(db: AsyncSession, *, password: str = _CURRENT_PW) -> User:
    unique = generate_id().hex[-12:]
    user = User(
        id=generate_id(),
        username=f"user{unique}",
        email=f"{unique}@example.com",
        hashed_password=hash_password(password),
        first_name="Test",
        last_name="User",
        is_active=True,
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


async def _make_reset_token(
    db: AsyncSession,
    user: User,
    *,
    raw_token: str,
    used: bool = False,
    expired: bool = False,
) -> PasswordResetToken:
    now = datetime.now(UTC)
    token = PasswordResetToken(
        id=generate_id(),
        user_id=user.id,
        token_hash=hash_reset_token(raw_token),
        expires_at=(now - timedelta(minutes=1)) if expired else (now + timedelta(hours=1)),
        used_at=now if used else None,
    )
    db.add(token)
    await db.flush()
    return token


@dataclass
class _FakeEmailService:
    """Records send attempts without touching a real SMTP server."""

    fail: bool = False
    sent: list[dict[str, object]] = field(default_factory=list)

    async def send_password_reset_email(
        self, *, to_email: str, reset_link: str, expires_at: datetime
    ) -> None:
        self.sent.append({"to_email": to_email, "reset_link": reset_link})
        if self.fail:
            raise EmailDeliveryError(EmailMessageType.PASSWORD_RESET, attempts=3)


@pytest.fixture
def fake_email_service(client: TestClient) -> Iterator[_FakeEmailService]:
    fake = _FakeEmailService()
    client.app.dependency_overrides[get_email_service] = lambda: fake  # type: ignore[attr-defined]
    yield fake
    client.app.dependency_overrides.pop(get_email_service, None)  # type: ignore[attr-defined]


def _extract_raw_token(reset_link: str) -> str:
    return reset_link.rsplit("token=", 1)[-1]


class TestPasswordResetRequest:
    async def test_existing_email_returns_uniform_202_and_sends_email(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
        fake_email_service: _FakeEmailService,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        user = await _make_user(db_session)
        await db_session.commit()

        response = client.post("/v1/auth/password-reset", json={"email": user.email})

        assert response.status_code == 202
        assert response.json() == {
            "message": "If an account exists for that email, a reset link has been sent."
        }
        assert len(fake_email_service.sent) == 1
        assert fake_email_service.sent[0]["to_email"] == user.email

    async def test_nonexistent_email_returns_identical_uniform_202_without_sending(
        self,
        migrated_db: None,
        client: TestClient,
        redis_available: bool,
        fake_email_service: _FakeEmailService,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        response = client.post("/v1/auth/password-reset", json={"email": "nobody-here@example.com"})

        assert response.status_code == 202
        assert response.json() == {
            "message": "If an account exists for that email, a reset link has been sent."
        }
        assert fake_email_service.sent == []

    async def test_malformed_body_is_400(
        self, migrated_db: None, client: TestClient, redis_available: bool
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        response = client.post("/v1/auth/password-reset", json={})

        assert response.status_code == 400
        assert response.headers["content-type"] == "application/problem+json"

    async def test_email_delivery_failure_still_returns_uniform_202(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
        fake_email_service: _FakeEmailService,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        fake_email_service.fail = True
        user = await _make_user(db_session)
        await db_session.commit()

        response = client.post("/v1/auth/password-reset", json={"email": user.email})

        assert response.status_code == 202
        assert response.json()["message"] == (
            "If an account exists for that email, a reset link has been sent."
        )

    async def test_second_request_invalidates_the_first_token(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
        fake_email_service: _FakeEmailService,
    ) -> None:
        """F17: only the most recently issued reset token validates."""

        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        user = await _make_user(db_session)
        await db_session.commit()

        first = client.post("/v1/auth/password-reset", json={"email": user.email})
        assert first.status_code == 202
        first_raw_token = _extract_raw_token(str(fake_email_service.sent[0]["reset_link"]))

        second = client.post("/v1/auth/password-reset", json={"email": user.email})
        assert second.status_code == 202
        second_raw_token = _extract_raw_token(str(fake_email_service.sent[1]["reset_link"]))

        assert first_raw_token != second_raw_token

        stale_confirm = client.post(
            "/v1/auth/password-reset/confirm",
            json={"reset_token": first_raw_token, "new_password": _NEW_PW},
        )
        assert stale_confirm.status_code == 410

        fresh_confirm = client.post(
            "/v1/auth/password-reset/confirm",
            json={"reset_token": second_raw_token, "new_password": _NEW_PW},
        )
        assert fresh_confirm.status_code == 204

    async def test_account_dependent_work_is_deferred_to_a_background_task(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
        fake_email_service: _FakeEmailService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Structural regression test for the HIGH timing side-channel fix.

        A wall-clock timing assertion would be flaky (per the review), so
        this instead asserts the *mechanism*: the account-dependent
        sequence (user lookup / token issuance / SMTP send) must be
        scheduled via `BackgroundTasks.add_task`, not awaited inline in
        the request handler, for *both* an existing and a non-existent
        email -- proving neither branch does account-dependent work
        before the response is produced.
        """

        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        user = await _make_user(db_session)
        await db_session.commit()

        scheduled: list[object] = []
        original_add_task = BackgroundTasks.add_task

        def _spy_add_task(
            self: BackgroundTasks, func: object, *args: object, **kwargs: object
        ) -> None:
            scheduled.append(func)
            original_add_task(self, func, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(BackgroundTasks, "add_task", _spy_add_task)

        existing = client.post("/v1/auth/password-reset", json={"email": user.email})
        missing = client.post("/v1/auth/password-reset", json={"email": "nobody-here@example.com"})

        assert existing.status_code == 202
        assert missing.status_code == 202
        # Both branches scheduled the same account-dependent job as a
        # background task -- neither ran it inline before returning.
        assert scheduled == [
            password_api._process_password_reset_request,
            password_api._process_password_reset_request,
        ]
        # And it did in fact run (TestClient executes background tasks
        # before `.post()` returns), so this isn't just an unused stub.
        assert len(fake_email_service.sent) == 1
        assert fake_email_service.sent[0]["to_email"] == user.email


class TestPasswordResetConfirm:
    async def test_valid_token_sets_password_and_revokes_other_sessions(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        user = await _make_user(db_session)
        other_session = await _make_session(db_session, user)
        raw_value = "raw-reset-token-value"
        await _make_reset_token(db_session, user, raw_token=raw_value)
        await db_session.commit()
        other_token = _bearer_token_for(user, other_session)

        # Other session is active before confirm.
        pre = client.get("/v1/auth/sessions", headers=_auth_header(other_token))
        assert pre.status_code == 200

        response = client.post(
            "/v1/auth/password-reset/confirm",
            json={"reset_token": raw_value, "new_password": _NEW_PW},
        )

        assert response.status_code == 204

        # F16: the other session is now revoked.
        post = client.get("/v1/auth/sessions", headers=_auth_header(other_token))
        assert post.status_code == 401

        await db_session.refresh(user)
        from app.core.security import verify_password

        assert verify_password(_NEW_PW, user.hashed_password)

    async def test_unknown_token_is_410(
        self, migrated_db: None, client: TestClient, redis_available: bool
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        response = client.post(
            "/v1/auth/password-reset/confirm",
            json={"reset_token": "does-not-exist", "new_password": _NEW_PW},
        )

        assert response.status_code == 410
        assert response.headers["content-type"] == "application/problem+json"

    async def test_used_token_is_410(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        user = await _make_user(db_session)
        raw_value = "already-used-token"
        await _make_reset_token(db_session, user, raw_token=raw_value, used=True)
        await db_session.commit()

        response = client.post(
            "/v1/auth/password-reset/confirm",
            json={"reset_token": raw_value, "new_password": _NEW_PW},
        )

        assert response.status_code == 410

    async def test_expired_token_is_410(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        user = await _make_user(db_session)
        raw_value = "expired-token"
        await _make_reset_token(db_session, user, raw_token=raw_value, expired=True)
        await db_session.commit()

        response = client.post(
            "/v1/auth/password-reset/confirm",
            json={"reset_token": raw_value, "new_password": _NEW_PW},
        )

        assert response.status_code == 410

    async def test_policy_failing_new_password_is_422_and_token_still_valid(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        user = await _make_user(db_session)
        raw_value = "policy-check-token"
        await _make_reset_token(db_session, user, raw_token=raw_value)
        await db_session.commit()

        bad = client.post(
            "/v1/auth/password-reset/confirm",
            json={"reset_token": raw_value, "new_password": "short"},
        )
        assert bad.status_code == 422
        assert bad.headers["content-type"] == "application/problem+json"

        # Token was not consumed by the policy failure — a compliant
        # password against the same token still succeeds.
        good = client.post(
            "/v1/auth/password-reset/confirm",
            json={"reset_token": raw_value, "new_password": _NEW_PW},
        )
        assert good.status_code == 204

    async def test_malformed_body_is_400(
        self, migrated_db: None, client: TestClient, redis_available: bool
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        response = client.post("/v1/auth/password-reset/confirm", json={})

        assert response.status_code == 400
        assert response.headers["content-type"] == "application/problem+json"

    async def test_must_change_password_account_can_unblock_via_reset_and_then_login(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
        fake_email_service: _FakeEmailService,
    ) -> None:
        """T42/ADR-0011: reset-confirm is the exit path for a
        `must_change_password=true` account (e.g. the ADR-0009 bootstrap
        admin) — completing the existing self-service reset flow clears the
        flag, so the account can then log in normally."""

        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        user = await _make_user(db_session)
        user.must_change_password = True
        await db_session.commit()

        # Confirm the account is blocked at login before the fix path runs.
        blocked = client.post("/v1/auth/login", json={"email": user.email, "password": _CURRENT_PW})
        assert blocked.status_code == 403

        request_response = client.post("/v1/auth/password-reset", json={"email": user.email})
        assert request_response.status_code == 202
        raw_token = _extract_raw_token(str(fake_email_service.sent[0]["reset_link"]))

        confirm_response = client.post(
            "/v1/auth/password-reset/confirm",
            json={"reset_token": raw_token, "new_password": _NEW_PW},
        )
        assert confirm_response.status_code == 204

        await db_session.refresh(user)
        assert user.must_change_password is False

        login_response = client.post(
            "/v1/auth/login", json={"email": user.email, "password": _NEW_PW}
        )
        assert login_response.status_code == 200
        body = login_response.json()
        assert body["access_token"]
        assert body["refresh_token"]


class TestPasswordChange:
    async def test_correct_password_changes_and_revokes_other_sessions_only(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        user = await _make_user(db_session)
        initiating_session = await _make_session(db_session, user)
        other_session = await _make_session(db_session, user)
        await db_session.commit()
        initiating_token = _bearer_token_for(user, initiating_session)
        other_token = _bearer_token_for(user, other_session)

        response = client.post(
            "/v1/auth/password/change",
            headers=_auth_header(initiating_token),
            json={"current_password": _CURRENT_PW, "new_password": _NEW_PW},
        )

        assert response.status_code == 204

        # Initiating session stays alive (F22).
        still_alive = client.get("/v1/auth/sessions", headers=_auth_header(initiating_token))
        assert still_alive.status_code == 200

        # Every other session is revoked.
        revoked = client.get("/v1/auth/sessions", headers=_auth_header(other_token))
        assert revoked.status_code == 401

        await db_session.refresh(user)
        from app.core.security import verify_password

        assert verify_password(_NEW_PW, user.hashed_password)

    async def test_wrong_current_password_is_401_and_password_unchanged(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        user = await _make_user(db_session)
        session = await _make_session(db_session, user)
        await db_session.commit()
        token = _bearer_token_for(user, session)
        original_hash = user.hashed_password

        response = client.post(
            "/v1/auth/password/change",
            headers=_auth_header(token),
            json={"current_password": "totally-wrong-1", "new_password": _NEW_PW},
        )

        assert response.status_code == 401
        assert response.headers["content-type"] == "application/problem+json"

        await db_session.refresh(user)
        assert user.hashed_password == original_hash

        # Session must still be alive (password change never touched it).
        still_alive = client.get("/v1/auth/sessions", headers=_auth_header(token))
        assert still_alive.status_code == 200

    async def test_policy_failing_new_password_is_422(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        user = await _make_user(db_session)
        session = await _make_session(db_session, user)
        await db_session.commit()
        token = _bearer_token_for(user, session)

        response = client.post(
            "/v1/auth/password/change",
            headers=_auth_header(token),
            json={"current_password": _CURRENT_PW, "new_password": "short"},
        )

        assert response.status_code == 422
        assert response.headers["content-type"] == "application/problem+json"

    async def test_malformed_body_is_400(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        user = await _make_user(db_session)
        session = await _make_session(db_session, user)
        await db_session.commit()
        token = _bearer_token_for(user, session)

        response = client.post(
            "/v1/auth/password/change",
            headers=_auth_header(token),
            json={},
        )

        assert response.status_code == 400
        assert response.headers["content-type"] == "application/problem+json"

    async def test_missing_auth_is_401(
        self, migrated_db: None, client: TestClient, redis_available: bool
    ) -> None:
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        response = client.post(
            "/v1/auth/password/change",
            json={"current_password": _CURRENT_PW, "new_password": _NEW_PW},
        )

        assert response.status_code == 401

    async def test_change_password_clears_must_change_password_flag(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_available: bool,
    ) -> None:
        """T42/ADR-0011: an authenticated session hitting `/password/change`
        while `must_change_password` is set also clears the flag."""

        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        user = await _make_user(db_session)
        user.must_change_password = True
        session = await _make_session(db_session, user)
        await db_session.commit()
        token = _bearer_token_for(user, session)

        response = client.post(
            "/v1/auth/password/change",
            headers=_auth_header(token),
            json={"current_password": _CURRENT_PW, "new_password": _NEW_PW},
        )

        assert response.status_code == 204

        await db_session.refresh(user)
        assert user.must_change_password is False
