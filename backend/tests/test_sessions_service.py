from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import generate_id
from app.core.token_hash import hash_refresh_token
from app.models.session import Session
from app.models.user import User
from app.services.sessions import (
    RevokeOutcome,
    create_session,
    extend_session_expiry,
    generate_raw_refresh_token,
    list_active_sessions_for_user,
    revoke_session,
)

pytestmark = pytest.mark.usefixtures("configured_env")

# Not a real credential — just filler for a NOT NULL column this test suite
# never authenticates against; kept as a named constant (rather than an
# inline literal) so it doesn't read as a live secret.
_PLACEHOLDER_HASH_VALUE = "not-a-real-hash-value"


async def _make_user(db: AsyncSession, *, username: str = "alice", is_active: bool = True) -> User:
    user = User(
        id=generate_id(),
        username=username,
        email=f"{username}@example.com",
        hashed_password=_PLACEHOLDER_HASH_VALUE,
        first_name="A",
        last_name="Lice",
        is_active=is_active,
        is_system_admin=False,
    )
    db.add(user)
    await db.flush()
    return user


class TestGenerateRawRefreshToken:
    def test_produces_distinct_high_entropy_values(self) -> None:
        tokens = {generate_raw_refresh_token() for _ in range(50)}

        assert len(tokens) == 50
        assert all(len(token) >= 32 for token in tokens)


class TestCreateSession:
    async def test_stores_only_the_hash_never_the_raw_token(self, db_session: AsyncSession) -> None:
        user = await _make_user(db_session)

        created = await create_session(db_session, user_id=user.id, session_ttl_days=30)
        await db_session.commit()

        assert created.session.refresh_token_hash == hash_refresh_token(created.raw_refresh_token)
        assert created.raw_refresh_token not in created.session.refresh_token_hash

    async def test_sets_30_day_sliding_expiry_from_issued_at(
        self, db_session: AsyncSession
    ) -> None:
        user = await _make_user(db_session)
        now = datetime.now(UTC).replace(microsecond=0)

        created = await create_session(db_session, user_id=user.id, session_ttl_days=30, now=now)
        await db_session.commit()

        assert created.session.issued_at == now
        assert created.session.expires_at == now + timedelta(days=30)
        assert created.session.revoked_at is None

    async def test_id_is_usable_as_the_jwt_sid_claim(self, db_session: AsyncSession) -> None:
        user = await _make_user(db_session)

        created = await create_session(db_session, user_id=user.id, session_ttl_days=30)
        await db_session.commit()

        fetched = await db_session.get(Session, created.session.id)
        assert fetched is not None
        assert fetched.user_id == user.id


class TestListActiveSessionsForUser:
    async def test_excludes_revoked_sessions(self, db_session: AsyncSession) -> None:
        user = await _make_user(db_session)
        active = await create_session(db_session, user_id=user.id, session_ttl_days=30)
        revoked = await create_session(db_session, user_id=user.id, session_ttl_days=30)
        revoked.session.revoked_at = datetime.now(UTC)
        await db_session.commit()

        sessions = await list_active_sessions_for_user(db_session, user.id)

        session_ids = {s.id for s in sessions}
        assert active.session.id in session_ids
        assert revoked.session.id not in session_ids

    async def test_excludes_other_users_sessions(self, db_session: AsyncSession) -> None:
        user_a = await _make_user(db_session, username="usera")
        user_b = await _make_user(db_session, username="userb")
        own = await create_session(db_session, user_id=user_a.id, session_ttl_days=30)
        await create_session(db_session, user_id=user_b.id, session_ttl_days=30)
        await db_session.commit()

        sessions = await list_active_sessions_for_user(db_session, user_a.id)

        assert [s.id for s in sessions] == [own.session.id]


class TestExtendSessionExpiry:
    async def test_slides_expiry_forward_and_stamps_last_used(
        self, db_session: AsyncSession
    ) -> None:
        user = await _make_user(db_session)
        created = await create_session(db_session, user_id=user.id, session_ttl_days=30)
        await db_session.commit()

        later = created.session.issued_at + timedelta(days=10)
        extend_session_expiry(created.session, session_ttl_days=30, now=later)

        assert created.session.last_used_at == later
        assert created.session.expires_at == later + timedelta(days=30)


class TestRevokeSession:
    async def test_revokes_a_session_owned_by_the_caller(self, db_session: AsyncSession) -> None:
        user = await _make_user(db_session)
        created = await create_session(db_session, user_id=user.id, session_ttl_days=30)
        await db_session.commit()

        outcome = await revoke_session(db_session, session_id=created.session.id, user_id=user.id)
        await db_session.commit()

        assert outcome is RevokeOutcome.REVOKED
        refreshed = await db_session.get(Session, created.session.id)
        assert refreshed is not None
        assert refreshed.revoked_at is not None

    async def test_is_idempotent_on_an_already_revoked_session(
        self, db_session: AsyncSession
    ) -> None:
        user = await _make_user(db_session)
        created = await create_session(db_session, user_id=user.id, session_ttl_days=30)
        await db_session.commit()

        first = await revoke_session(db_session, session_id=created.session.id, user_id=user.id)
        await db_session.commit()
        second = await revoke_session(db_session, session_id=created.session.id, user_id=user.id)
        await db_session.commit()

        assert first is RevokeOutcome.REVOKED
        assert second is RevokeOutcome.REVOKED

    async def test_returns_not_found_for_a_nonexistent_session(
        self, db_session: AsyncSession
    ) -> None:
        user = await _make_user(db_session)
        await db_session.commit()

        outcome = await revoke_session(db_session, session_id=generate_id(), user_id=user.id)

        assert outcome is RevokeOutcome.NOT_FOUND

    async def test_returns_forbidden_for_another_users_session(
        self, db_session: AsyncSession
    ) -> None:
        owner = await _make_user(db_session, username="owner")
        other = await _make_user(db_session, username="other")
        created = await create_session(db_session, user_id=owner.id, session_ttl_days=30)
        await db_session.commit()

        outcome = await revoke_session(db_session, session_id=created.session.id, user_id=other.id)

        assert outcome is RevokeOutcome.FORBIDDEN
        refreshed = await db_session.get(Session, created.session.id)
        assert refreshed is not None
        assert refreshed.revoked_at is None
