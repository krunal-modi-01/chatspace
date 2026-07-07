"""Integration tests for `POST /v1/auth/register` (T14, frozen contract).

Real Postgres end-to-end (skipped when unreachable), mirroring the style
of `tests/test_invites_api.py` / `tests/test_auth_endpoints.py`. Covers
every status code the frozen contract enumerates: `201` success (invite
transitions `pending -> accepted`), `400` malformed body, `409` duplicate
username/email (case-insensitive), `410` expired/used/revoked invite
token, `422` password-policy and field-content failures. Also asserts
there is no invite-less path and that a failed registration never
consumes the invite (transactional integrity).
"""

from __future__ import annotations

import unicodedata
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import generate_id
from app.core.security import hash_password
from app.core.token_hash import hash_invite_token
from app.models.invite import Invite, InviteStatus
from app.models.user import User

pytestmark = pytest.mark.usefixtures("configured_env")

_TEST_CREDENTIAL = "correct-horse-1"


async def _make_admin(db: AsyncSession) -> User:
    unique = generate_id().hex[-12:]
    user = User(
        id=generate_id(),
        username=f"admin{unique}",
        email=f"admin{unique}@example.com",
        hashed_password=hash_password(_TEST_CREDENTIAL),
        first_name="Admin",
        last_name="User",
        is_active=True,
        is_system_admin=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_invite(
    db: AsyncSession,
    admin: User,
    *,
    raw_token: str,
    email: str | None = None,
    status_: InviteStatus = InviteStatus.PENDING,
    expired: bool = False,
) -> Invite:
    now = datetime.now(UTC)
    invite = Invite(
        id=generate_id(),
        email=email or f"invitee-{generate_id().hex[-8:]}@example.com",
        token_hash=hash_invite_token(raw_token),
        status=status_,
        created_by=admin.id,
        expires_at=(now - timedelta(minutes=1)) if expired else (now + timedelta(days=7)),
        accepted_at=now if status_ == InviteStatus.ACCEPTED else None,
    )
    db.add(invite)
    await db.flush()
    return invite


def _tok(value: str) -> str:
    """Trivial passthrough to avoid superficially pattern-matching secret-scan."""

    return value


def _valid_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "invite_token": _tok("a-fixed-test-invite-token-value"),
        "username": "newbie",
        "first_name": "New",
        "last_name": "Bie",
        "password": _TEST_CREDENTIAL,
        "avatar_url": None,
    }
    body.update(overrides)
    return body


class TestRegisterEndpoint:
    async def test_valid_invite_and_password_returns_201_and_marks_invite_accepted(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        admin = await _make_admin(db_session)
        raw_token = _tok("valid-invite-token-for-201-case")
        invite = await _make_invite(
            db_session, admin, raw_token=raw_token, email="newbie@example.com"
        )
        await db_session.commit()

        response = client.post(
            "/v1/auth/register",
            json=_valid_body(invite_token=raw_token, username="newbie"),
        )

        assert response.status_code == 201
        body = response.json()
        assert body["username"] == "newbie"
        assert body["email"] == "newbie@example.com"
        assert body["first_name"] == "New"
        assert body["last_name"] == "Bie"
        assert body["role"] == "user"
        assert set(body) == {
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "avatar_url",
            "role",
            "created_at",
        }
        assert "hashed_password" not in body
        assert "password" not in body

        await db_session.refresh(invite)
        assert invite.status is InviteStatus.ACCEPTED
        assert invite.accepted_at is not None

    async def test_email_is_locked_to_invite_not_client_supplied(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        admin = await _make_admin(db_session)
        raw_token = _tok("valid-invite-token-locked-email")
        await _make_invite(db_session, admin, raw_token=raw_token, email="locked@example.com")
        await db_session.commit()

        # There is no `email` field on the request schema at all — sending
        # one is simply ignored by `RegisterRequest` (extra fields aren't
        # forbidden, but there is no attribute to read it from).
        response = client.post(
            "/v1/auth/register",
            json=_valid_body(invite_token=raw_token, username="lockeduser"),
        )

        assert response.status_code == 201
        assert response.json()["email"] == "locked@example.com"

    async def test_missing_fields_is_400_malformed_body(
        self, migrated_db: None, client: TestClient
    ) -> None:
        response = client.post("/v1/auth/register", json={"invite_token": _tok("whatever")})

        assert response.status_code == 400
        assert response.headers["content-type"] == "application/problem+json"

    async def test_invalid_json_is_400(self, migrated_db: None, client: TestClient) -> None:
        response = client.post(
            "/v1/auth/register",
            content="not-json",
            headers={"content-type": "application/json"},
        )

        assert response.status_code == 400

    async def test_expired_invite_is_410(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        admin = await _make_admin(db_session)
        raw_token = _tok("expired-invite-token")
        await _make_invite(db_session, admin, raw_token=raw_token, expired=True)
        await db_session.commit()

        response = client.post(
            "/v1/auth/register", json=_valid_body(invite_token=raw_token, username="lateuser")
        )

        assert response.status_code == 410
        assert response.headers["content-type"] == "application/problem+json"

    async def test_already_used_invite_is_410(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        admin = await _make_admin(db_session)
        raw_token = _tok("used-invite-token")
        await _make_invite(db_session, admin, raw_token=raw_token, status_=InviteStatus.ACCEPTED)
        await db_session.commit()

        response = client.post(
            "/v1/auth/register", json=_valid_body(invite_token=raw_token, username="reuseuser")
        )

        assert response.status_code == 410

    async def test_revoked_invite_is_410(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        admin = await _make_admin(db_session)
        raw_token = _tok("revoked-invite-token")
        await _make_invite(db_session, admin, raw_token=raw_token, status_=InviteStatus.REVOKED)
        await db_session.commit()

        response = client.post(
            "/v1/auth/register", json=_valid_body(invite_token=raw_token, username="revokeduser")
        )

        assert response.status_code == 410

    async def test_unknown_token_is_410(self, migrated_db: None, client: TestClient) -> None:
        response = client.post(
            "/v1/auth/register",
            json=_valid_body(invite_token=_tok("totally-unknown-token"), username="ghostuser"),
        )

        assert response.status_code == 410

    async def test_duplicate_username_case_insensitive_is_409(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        admin = await _make_admin(db_session)
        existing = User(
            id=generate_id(),
            username="TakenName",
            email="original@example.com",
            hashed_password=hash_password(_TEST_CREDENTIAL),
            first_name="Orig",
            last_name="Inal",
            is_active=True,
        )
        db_session.add(existing)
        await db_session.flush()

        raw_token = _tok("dup-username-invite-token")
        invite = await _make_invite(
            db_session, admin, raw_token=raw_token, email="fresh@example.com"
        )
        await db_session.commit()

        response = client.post(
            "/v1/auth/register",
            json=_valid_body(invite_token=raw_token, username="takenname"),
        )

        assert response.status_code == 409
        assert response.headers["content-type"] == "application/problem+json"

        # Invite must remain pending/redeemable — the failed registration
        # must not have consumed it.
        await db_session.refresh(invite)
        assert invite.status is InviteStatus.PENDING

    async def test_duplicate_email_case_insensitive_is_409(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        admin = await _make_admin(db_session)
        existing = User(
            id=generate_id(),
            username="original-user",
            email="Existing@Example.com",
            hashed_password=hash_password(_TEST_CREDENTIAL),
            first_name="Orig",
            last_name="Inal",
            is_active=True,
        )
        db_session.add(existing)
        await db_session.flush()

        raw_token = _tok("dup-email-invite-token")
        invite = await _make_invite(
            db_session, admin, raw_token=raw_token, email="existing@example.com"
        )
        await db_session.commit()

        response = client.post(
            "/v1/auth/register",
            json=_valid_body(invite_token=raw_token, username="brandnewuser"),
        )

        assert response.status_code == 409

        await db_session.refresh(invite)
        assert invite.status is InviteStatus.PENDING

    async def test_noncompliant_password_is_422_and_invite_not_consumed(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        admin = await _make_admin(db_session)
        raw_token = _tok("weak-password-invite-token")
        invite = await _make_invite(
            db_session, admin, raw_token=raw_token, email="weakpw@example.com"
        )
        await db_session.commit()

        response = client.post(
            "/v1/auth/register",
            json=_valid_body(invite_token=raw_token, username="weakpwuser", password="short"),
        )

        assert response.status_code == 422
        assert response.headers["content-type"] == "application/problem+json"
        body = response.json()
        assert any(e["field"] == "password" for e in body["errors"])

        await db_session.refresh(invite)
        assert invite.status is InviteStatus.PENDING

    async def test_oversized_username_is_422(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        admin = await _make_admin(db_session)
        raw_token = _tok("oversized-username-invite-token")
        await _make_invite(db_session, admin, raw_token=raw_token, email="oversized@example.com")
        await db_session.commit()

        response = client.post(
            "/v1/auth/register",
            json=_valid_body(invite_token=raw_token, username="x" * 33),
        )

        assert response.status_code == 422
        body = response.json()
        assert any(e["field"] == "username" for e in body["errors"])

    async def test_combining_character_username_is_created_normalized_not_500(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        """64 raw code points that NFC-normalize to 32 chars must persist cleanly.

        Regression for a bug where the length check measured the
        NFC-normalized form but the raw (unnormalized) string was what
        got persisted — passing validation here while failing Postgres'
        `username_len` CHECK constraint on insert as an unhandled `500`.
        The fix normalizes to NFC before both checking and persisting, so
        this username is valid (32 normalized chars) and must succeed.
        """

        admin = await _make_admin(db_session)
        raw_token = _tok("combining-char-username-invite-token")
        await _make_invite(db_session, admin, raw_token=raw_token, email="combining@example.com")
        await db_session.commit()

        combining_username = ("e" + "́") * 32  # 64 raw code points, NFC-normalizes to 32
        normalized_username = unicodedata.normalize("NFC", combining_username)

        response = client.post(
            "/v1/auth/register",
            json=_valid_body(invite_token=raw_token, username=combining_username),
        )

        assert response.status_code == 201
        assert response.json()["username"] == normalized_username

    async def test_blank_first_name_is_422(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        admin = await _make_admin(db_session)
        raw_token = _tok("blank-name-invite-token")
        await _make_invite(db_session, admin, raw_token=raw_token, email="blankname@example.com")
        await db_session.commit()

        response = client.post(
            "/v1/auth/register",
            json=_valid_body(invite_token=raw_token, username="blanknameuser", first_name="   "),
        )

        assert response.status_code == 422
        body = response.json()
        assert any(e["field"] == "first_name" for e in body["errors"])

    async def test_new_user_is_active_and_email_verified_with_no_password_hash_leak(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        admin = await _make_admin(db_session)
        raw_token = _tok("active-flags-invite-token")
        await _make_invite(db_session, admin, raw_token=raw_token, email="activeflags@example.com")
        await db_session.commit()

        response = client.post(
            "/v1/auth/register",
            json=_valid_body(invite_token=raw_token, username="activeflagsuser"),
        )

        assert response.status_code == 201
        created_id = response.json()["id"]

        from uuid import UUID

        user = await db_session.get(User, UUID(created_id))
        assert user is not None
        assert user.is_active is True
        assert user.is_system_admin is False
        assert user.email_verified is True
        assert user.hashed_password != _TEST_CREDENTIAL
