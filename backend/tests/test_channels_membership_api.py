"""Integration tests for `/v1/channels/{id}/join|leave|members*` (T19, frozen contract).

Exercises the real routes end-to-end against Postgres (skipped when
unreachable): idempotent public-channel join (F31/F32), sole-admin
succession on leave/removal (F35/F36), the F37 zero-admin terminal state
and its `409` mutation-block on add/role-change/remove, offset-paginated
member listing, and the `400`/`401`/`403`/`404`/`409`/`422` error paths
for each endpoint.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.ids import generate_id
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.models.channel import Channel
from app.models.channel_member import ChannelMember, ChannelMemberRole
from app.models.session import Session
from app.models.user import User
from app.services.channels import LeaveOutcome, leave_channel
from tests.conftest import ASYNC_DATABASE_URL, REQUIRED_ENV

pytestmark = pytest.mark.usefixtures("configured_env")


def _test_login_secret() -> str:
    """Not a real secret — see `test_channels_api.py`'s identical helper."""

    return "correct-horse-1"


def _settings() -> object:
    from app.core.config import Settings

    return Settings(**{k.lower(): v for k, v in REQUIRED_ENV.items()})  # type: ignore[arg-type]


async def _make_user(db: AsyncSession, *, is_active: bool = True) -> User:
    unique = generate_id().hex[-12:]
    user = User(
        id=generate_id(),
        username=f"user{unique}",
        email=f"{unique}@example.com",
        hashed_password=hash_password(_test_login_secret()),
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


async def _make_channel(
    db: AsyncSession,
    *,
    creator: User,
    name: str | None = None,
    is_private: bool = False,
    members: list[tuple[User, ChannelMemberRole]] | None = None,
    joined_at_offsets_seconds: dict[str, int] | None = None,
) -> Channel:
    """Create a channel with `creator` as admin, plus any extra `members`.

    `joined_at_offsets_seconds` (keyed by user id str) lets a test control
    relative `joined_at` ordering for succession/list-ordering assertions
    without depending on real wall-clock gaps between inserts.
    """

    channel = Channel(
        id=generate_id(),
        name=name or f"channel-{generate_id().hex[-8:]}",
        is_private=is_private,
        created_by=creator.id,
    )
    db.add(channel)
    await db.flush()

    base = datetime.now(UTC)
    offsets = joined_at_offsets_seconds or {}

    creator_membership = ChannelMember(
        channel_id=channel.id, user_id=creator.id, role=ChannelMemberRole.ADMIN
    )
    if str(creator.id) in offsets:
        creator_membership.joined_at = base + timedelta(seconds=offsets[str(creator.id)])
    db.add(creator_membership)

    for member, role in members or []:
        membership = ChannelMember(channel_id=channel.id, user_id=member.id, role=role)
        if str(member.id) in offsets:
            membership.joined_at = base + timedelta(seconds=offsets[str(member.id)])
        db.add(membership)

    await db.flush()
    return channel


async def _get_membership_row(
    db: AsyncSession, *, channel_id: object, user_id: object
) -> ChannelMember | None:
    return await db.get(ChannelMember, (channel_id, user_id))


class TestJoinChannel:
    async def test_joins_public_channel_as_member(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, _ = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=creator, is_private=False)
        await db_session.commit()

        _, token = await _authed_user(db_session)

        response = client.post(f"/v1/channels/{channel.id}/join", headers=_auth_header(token))

        assert response.status_code == 200
        body = response.json()
        assert body["channel_id"] == str(channel.id)
        assert body["role"] == "member"
        assert "joined_at" in body

    async def test_joining_twice_is_idempotent(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, _ = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=creator, is_private=False)
        await db_session.commit()

        _, token = await _authed_user(db_session)

        first = client.post(f"/v1/channels/{channel.id}/join", headers=_auth_header(token))
        second = client.post(f"/v1/channels/{channel.id}/join", headers=_auth_header(token))

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["joined_at"] == second.json()["joined_at"]

    async def test_private_channel_direct_join_is_403(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, _ = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=creator, is_private=True)
        await db_session.commit()

        _, token = await _authed_user(db_session)

        response = client.post(f"/v1/channels/{channel.id}/join", headers=_auth_header(token))

        assert response.status_code == 403
        assert response.headers["content-type"] == "application/problem+json"

    async def test_missing_channel_is_404(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, token = await _authed_user(db_session)

        response = client.post(f"/v1/channels/{generate_id()}/join", headers=_auth_header(token))

        assert response.status_code == 404
        assert response.headers["content-type"] == "application/problem+json"

    async def test_missing_auth_is_401(self, migrated_db: None, client: TestClient) -> None:
        response = client.post(f"/v1/channels/{generate_id()}/join")

        assert response.status_code == 401


class TestLeaveChannel:
    async def test_member_leaves_channel(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, _ = await _authed_user(db_session)
        member, member_token = await _authed_user(db_session)
        channel = await _make_channel(
            db_session, creator=creator, members=[(member, ChannelMemberRole.MEMBER)]
        )
        await db_session.commit()

        response = client.post(
            f"/v1/channels/{channel.id}/leave", headers=_auth_header(member_token)
        )

        assert response.status_code == 204

        remaining = await _get_membership_row(db_session, channel_id=channel.id, user_id=member.id)
        assert remaining is None

    async def test_leaving_twice_second_call_is_204_idempotent_noop(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        """A repeat `leave` call, after the first already removed the row, is a no-op `204`.

        Per the api-reviewer's idempotency ruling, leave is idempotent: a
        second call that finds no membership row performs no mutation and
        still returns `204` — succession, correspondingly, still "runs at
        most once" either way.
        """

        creator, _ = await _authed_user(db_session)
        member, member_token = await _authed_user(db_session)
        channel = await _make_channel(
            db_session, creator=creator, members=[(member, ChannelMemberRole.MEMBER)]
        )
        await db_session.commit()

        first = client.post(f"/v1/channels/{channel.id}/leave", headers=_auth_header(member_token))
        second = client.post(f"/v1/channels/{channel.id}/leave", headers=_auth_header(member_token))

        assert first.status_code == 204
        assert second.status_code == 204

    async def test_not_a_member_is_204_idempotent_noop(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, _ = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=creator)
        await db_session.commit()

        _, other_token = await _authed_user(db_session)

        response = client.post(
            f"/v1/channels/{channel.id}/leave", headers=_auth_header(other_token)
        )

        assert response.status_code == 204

    async def test_absent_channel_is_204_idempotent_noop(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        """Leaving a channel that doesn't exist at all is also a no-op `204` (non-enumerating)."""

        _, token = await _authed_user(db_session)

        response = client.post(f"/v1/channels/{generate_id()}/leave", headers=_auth_header(token))

        assert response.status_code == 204

    async def test_sole_admin_leave_promotes_earliest_joined_member(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, creator_token = await _authed_user(db_session)
        early_member, _ = await _authed_user(db_session)
        late_member, _ = await _authed_user(db_session)
        channel = await _make_channel(
            db_session,
            creator=creator,
            members=[
                (early_member, ChannelMemberRole.MEMBER),
                (late_member, ChannelMemberRole.MEMBER),
            ],
            joined_at_offsets_seconds={
                str(creator.id): 0,
                str(early_member.id): 10,
                str(late_member.id): 20,
            },
        )
        await db_session.commit()

        response = client.post(
            f"/v1/channels/{channel.id}/leave", headers=_auth_header(creator_token)
        )
        assert response.status_code == 204

        promoted = await _get_membership_row(
            db_session, channel_id=channel.id, user_id=early_member.id
        )
        assert promoted is not None
        assert promoted.role == ChannelMemberRole.ADMIN

        not_promoted = await _get_membership_row(
            db_session, channel_id=channel.id, user_id=late_member.id
        )
        assert not_promoted is not None
        assert not_promoted.role == ChannelMemberRole.MEMBER

    async def test_sole_admin_leave_with_no_other_members_is_zero_admin_terminal_state(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, creator_token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=creator)
        await db_session.commit()

        response = client.post(
            f"/v1/channels/{channel.id}/leave", headers=_auth_header(creator_token)
        )

        assert response.status_code == 204

        remaining = await _get_membership_row(db_session, channel_id=channel.id, user_id=creator.id)
        assert remaining is None

    async def test_missing_auth_is_401(self, migrated_db: None, client: TestClient) -> None:
        response = client.post(f"/v1/channels/{generate_id()}/leave")

        assert response.status_code == 401


class TestListMembers:
    async def test_member_can_list_members(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, creator_token = await _authed_user(db_session)
        member, _ = await _authed_user(db_session)
        channel = await _make_channel(
            db_session, creator=creator, members=[(member, ChannelMemberRole.MEMBER)]
        )
        await db_session.commit()

        response = client.get(
            f"/v1/channels/{channel.id}/members", headers=_auth_header(creator_token)
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        user_ids = {item["user_id"] for item in body["items"]}
        assert str(creator.id) in user_ids
        assert str(member.id) in user_ids
        for item in body["items"]:
            assert "username" in item and "role" in item and "joined_at" in item

    async def test_public_channel_non_member_is_403(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        """A public channel's existence is already discoverable, so a non-member gets `403`."""

        creator, _ = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=creator, is_private=False)
        await db_session.commit()

        _, other_token = await _authed_user(db_session)

        response = client.get(
            f"/v1/channels/{channel.id}/members", headers=_auth_header(other_token)
        )

        assert response.status_code == 403
        assert response.headers["content-type"] == "application/problem+json"

    async def test_private_channel_non_member_is_404(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        """A private channel is hidden from a non-member behind the uniform, non-enumerating `404`.

        Mirrors `GET /{channel_id}`'s visibility gate (`get_channel_view`)
        — a caller cannot distinguish "doesn't exist" from "exists but is
        private" by status code.
        """

        creator, _ = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=creator, is_private=True)
        await db_session.commit()

        _, other_token = await _authed_user(db_session)

        response = client.get(
            f"/v1/channels/{channel.id}/members", headers=_auth_header(other_token)
        )

        assert response.status_code == 404
        assert response.headers["content-type"] == "application/problem+json"

    async def test_member_of_private_channel_can_list_members(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, creator_token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=creator, is_private=True)
        await db_session.commit()

        response = client.get(
            f"/v1/channels/{channel.id}/members", headers=_auth_header(creator_token)
        )

        assert response.status_code == 200
        assert response.json()["total"] == 1

    async def test_missing_channel_is_404(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, token = await _authed_user(db_session)

        response = client.get(f"/v1/channels/{generate_id()}/members", headers=_auth_header(token))

        assert response.status_code == 404

    async def test_missing_auth_is_401(self, migrated_db: None, client: TestClient) -> None:
        response = client.get(f"/v1/channels/{generate_id()}/members")

        assert response.status_code == 401


class TestAddMember:
    async def test_admin_adds_member_to_private_channel(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, creator_token = await _authed_user(db_session)
        target, _ = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=creator, is_private=True)
        await db_session.commit()

        response = client.post(
            f"/v1/channels/{channel.id}/members",
            headers=_auth_header(creator_token),
            json={"user_id": str(target.id), "role": "member"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["user_id"] == str(target.id)
        assert body["role"] == "member"

    async def test_adding_existing_member_is_idempotent(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, creator_token = await _authed_user(db_session)
        target, _ = await _authed_user(db_session)
        channel = await _make_channel(
            db_session, creator=creator, members=[(target, ChannelMemberRole.MEMBER)]
        )
        await db_session.commit()

        response = client.post(
            f"/v1/channels/{channel.id}/members",
            headers=_auth_header(creator_token),
            json={"user_id": str(target.id), "role": "admin"},
        )

        assert response.status_code == 200
        # Idempotent: role is NOT overwritten by the add-member call.
        assert response.json()["role"] == "member"

    async def test_non_admin_caller_is_403(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, _ = await _authed_user(db_session)
        member, member_token = await _authed_user(db_session)
        target, _ = await _authed_user(db_session)
        channel = await _make_channel(
            db_session, creator=creator, members=[(member, ChannelMemberRole.MEMBER)]
        )
        await db_session.commit()

        response = client.post(
            f"/v1/channels/{channel.id}/members",
            headers=_auth_header(member_token),
            json={"user_id": str(target.id), "role": "member"},
        )

        assert response.status_code == 403
        assert response.headers["content-type"] == "application/problem+json"

    async def test_non_admin_caller_is_403_regardless_of_target_user_existence(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        """A non-admin caller gets an identical `403` whether or not the target user exists.

        Regression for the authorization-ordering fix: caller
        authorization must be resolved *before* the target-user existence
        lookup, so a non-admin caller can never use this endpoint's status
        code to probe whether a given user id exists.
        """

        creator, _ = await _authed_user(db_session)
        member, member_token = await _authed_user(db_session)
        existing_target, _ = await _authed_user(db_session)
        channel = await _make_channel(
            db_session, creator=creator, members=[(member, ChannelMemberRole.MEMBER)]
        )
        await db_session.commit()

        existing_target_response = client.post(
            f"/v1/channels/{channel.id}/members",
            headers=_auth_header(member_token),
            json={"user_id": str(existing_target.id), "role": "member"},
        )
        nonexistent_target_response = client.post(
            f"/v1/channels/{channel.id}/members",
            headers=_auth_header(member_token),
            json={"user_id": str(generate_id()), "role": "member"},
        )

        assert existing_target_response.status_code == 403
        assert nonexistent_target_response.status_code == 403
        assert (
            existing_target_response.json()["detail"]
            == nonexistent_target_response.json()["detail"]
        )

    async def test_missing_channel_is_404(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, token = await _authed_user(db_session)
        target, _ = await _authed_user(db_session)
        await db_session.commit()

        response = client.post(
            f"/v1/channels/{generate_id()}/members",
            headers=_auth_header(token),
            json={"user_id": str(target.id), "role": "member"},
        )

        assert response.status_code == 404

    async def test_missing_target_user_is_404(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, creator_token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=creator)
        await db_session.commit()

        response = client.post(
            f"/v1/channels/{channel.id}/members",
            headers=_auth_header(creator_token),
            json={"user_id": str(generate_id()), "role": "member"},
        )

        assert response.status_code == 404

    async def test_invalid_role_is_422(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, creator_token = await _authed_user(db_session)
        target, _ = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=creator)
        await db_session.commit()

        response = client.post(
            f"/v1/channels/{channel.id}/members",
            headers=_auth_header(creator_token),
            json={"user_id": str(target.id), "role": "superadmin"},
        )

        assert response.status_code == 422
        assert response.headers["content-type"] == "application/problem+json"

    async def test_malformed_body_is_400(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, creator_token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=creator)
        await db_session.commit()

        response = client.post(
            f"/v1/channels/{channel.id}/members",
            headers=_auth_header(creator_token),
            json={"role": "member"},
        )

        assert response.status_code == 400
        assert response.headers["content-type"] == "application/problem+json"

    async def test_zero_admin_channel_is_409(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, creator_token = await _authed_user(db_session)
        target, _ = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=creator)
        await db_session.commit()

        # Self-demote the sole admin to `member` via PATCH — the frozen
        # contract scopes succession to leave/remove only, so this
        # legitimately produces the F37 zero-admin terminal state with a
        # member still present, without going through `leave`.
        demote = client.patch(
            f"/v1/channels/{channel.id}/members/{creator.id}",
            headers=_auth_header(creator_token),
            json={"role": "member"},
        )
        assert demote.status_code == 200
        assert demote.json()["role"] == "member"

        response = client.post(
            f"/v1/channels/{channel.id}/members",
            headers=_auth_header(creator_token),
            json={"user_id": str(target.id), "role": "member"},
        )

        assert response.status_code == 409
        assert response.headers["content-type"] == "application/problem+json"

    async def test_missing_auth_is_401(self, migrated_db: None, client: TestClient) -> None:
        response = client.post(
            f"/v1/channels/{generate_id()}/members",
            json={"user_id": str(generate_id()), "role": "member"},
        )

        assert response.status_code == 401


class TestChangeMemberRole:
    async def test_admin_promotes_member_to_admin(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, creator_token = await _authed_user(db_session)
        member, _ = await _authed_user(db_session)
        channel = await _make_channel(
            db_session, creator=creator, members=[(member, ChannelMemberRole.MEMBER)]
        )
        await db_session.commit()

        response = client.patch(
            f"/v1/channels/{channel.id}/members/{member.id}",
            headers=_auth_header(creator_token),
            json={"role": "admin"},
        )

        assert response.status_code == 200
        assert response.json()["role"] == "admin"

    async def test_setting_same_role_is_idempotent_no_op(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, creator_token = await _authed_user(db_session)
        member, _ = await _authed_user(db_session)
        channel = await _make_channel(
            db_session, creator=creator, members=[(member, ChannelMemberRole.MEMBER)]
        )
        await db_session.commit()

        response = client.patch(
            f"/v1/channels/{channel.id}/members/{member.id}",
            headers=_auth_header(creator_token),
            json={"role": "member"},
        )

        assert response.status_code == 200
        assert response.json()["role"] == "member"

    async def test_non_admin_caller_is_403(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, _ = await _authed_user(db_session)
        member, member_token = await _authed_user(db_session)
        other, _ = await _authed_user(db_session)
        channel = await _make_channel(
            db_session,
            creator=creator,
            members=[(member, ChannelMemberRole.MEMBER), (other, ChannelMemberRole.MEMBER)],
        )
        await db_session.commit()

        response = client.patch(
            f"/v1/channels/{channel.id}/members/{other.id}",
            headers=_auth_header(member_token),
            json={"role": "admin"},
        )

        assert response.status_code == 403

    async def test_target_not_a_member_is_404(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, creator_token = await _authed_user(db_session)
        outsider, _ = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=creator)
        await db_session.commit()

        response = client.patch(
            f"/v1/channels/{channel.id}/members/{outsider.id}",
            headers=_auth_header(creator_token),
            json={"role": "admin"},
        )

        assert response.status_code == 404

    async def test_invalid_role_is_422(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, creator_token = await _authed_user(db_session)
        member, _ = await _authed_user(db_session)
        channel = await _make_channel(
            db_session, creator=creator, members=[(member, ChannelMemberRole.MEMBER)]
        )
        await db_session.commit()

        response = client.patch(
            f"/v1/channels/{channel.id}/members/{member.id}",
            headers=_auth_header(creator_token),
            json={"role": "superadmin"},
        )

        assert response.status_code == 422

    async def test_zero_admin_channel_is_409(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, creator_token = await _authed_user(db_session)
        member, _ = await _authed_user(db_session)
        channel = await _make_channel(
            db_session, creator=creator, members=[(member, ChannelMemberRole.MEMBER)]
        )
        await db_session.commit()

        # Self-demote the sole admin to `member` — legitimately produces
        # the F37 zero-admin terminal state (role-change never runs
        # succession).
        demote = client.patch(
            f"/v1/channels/{channel.id}/members/{creator.id}",
            headers=_auth_header(creator_token),
            json={"role": "member"},
        )
        assert demote.status_code == 200
        assert demote.json()["role"] == "member"

        response = client.patch(
            f"/v1/channels/{channel.id}/members/{member.id}",
            headers=_auth_header(creator_token),
            json={"role": "admin"},
        )

        assert response.status_code == 409
        assert response.headers["content-type"] == "application/problem+json"

    async def test_missing_auth_is_401(self, migrated_db: None, client: TestClient) -> None:
        response = client.patch(
            f"/v1/channels/{generate_id()}/members/{generate_id()}",
            json={"role": "admin"},
        )

        assert response.status_code == 401


class TestRemoveMember:
    async def test_admin_removes_member(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, creator_token = await _authed_user(db_session)
        member, _ = await _authed_user(db_session)
        channel = await _make_channel(
            db_session, creator=creator, members=[(member, ChannelMemberRole.MEMBER)]
        )
        await db_session.commit()

        response = client.delete(
            f"/v1/channels/{channel.id}/members/{member.id}",
            headers=_auth_header(creator_token),
        )

        assert response.status_code == 204

        remaining = await _get_membership_row(db_session, channel_id=channel.id, user_id=member.id)
        assert remaining is None

    async def test_removing_non_member_is_idempotent_204(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, creator_token = await _authed_user(db_session)
        outsider, _ = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=creator)
        await db_session.commit()

        response = client.delete(
            f"/v1/channels/{channel.id}/members/{outsider.id}",
            headers=_auth_header(creator_token),
        )

        assert response.status_code == 204

    async def test_removing_sole_admin_promotes_earliest_joined_member(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, creator_token = await _authed_user(db_session)
        co_admin, co_admin_token = await _authed_user(db_session)
        early_member, _ = await _authed_user(db_session)
        channel = await _make_channel(
            db_session,
            creator=creator,
            members=[(co_admin, ChannelMemberRole.ADMIN), (early_member, ChannelMemberRole.MEMBER)],
            joined_at_offsets_seconds={
                str(creator.id): 0,
                str(co_admin.id): 5,
                str(early_member.id): 10,
            },
        )
        await db_session.commit()

        # Capture ids before any `expire_all()` below — reading an
        # attribute off an expired ORM instance triggers a lazy reload
        # outside the async greenlet (`MissingGreenlet`), mirroring
        # `test_admin_api.py`'s identical precaution.
        channel_id = channel.id
        creator_id = creator.id
        co_admin_id = co_admin.id
        early_member_id = early_member.id

        # Two admins exist (creator, co_admin) — removing `creator` does
        # not trigger succession since `co_admin` remains admin.
        remove_creator = client.delete(
            f"/v1/channels/{channel_id}/members/{creator_id}",
            headers=_auth_header(co_admin_token),
        )
        assert remove_creator.status_code == 204

        # `db.get` returns from `db_session`'s identity map otherwise — the
        # app's request-scoped session that performed the removal is a
        # separate connection, so expire here to observe the just-committed
        # state rather than a stale cached object.
        db_session.expire_all()
        still_member = await _get_membership_row(
            db_session, channel_id=channel_id, user_id=early_member_id
        )
        assert still_member is not None
        assert still_member.role == ChannelMemberRole.MEMBER

        # Now co_admin is sole admin; removing them promotes early_member.
        remove_co_admin = client.delete(
            f"/v1/channels/{channel_id}/members/{co_admin_id}",
            headers=_auth_header(co_admin_token),
        )
        assert remove_co_admin.status_code == 204

        db_session.expire_all()
        promoted = await _get_membership_row(
            db_session, channel_id=channel_id, user_id=early_member_id
        )
        assert promoted is not None
        assert promoted.role == ChannelMemberRole.ADMIN

    async def test_non_admin_caller_is_403(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, _ = await _authed_user(db_session)
        member, member_token = await _authed_user(db_session)
        other, _ = await _authed_user(db_session)
        channel = await _make_channel(
            db_session,
            creator=creator,
            members=[(member, ChannelMemberRole.MEMBER), (other, ChannelMemberRole.MEMBER)],
        )
        await db_session.commit()

        response = client.delete(
            f"/v1/channels/{channel.id}/members/{other.id}",
            headers=_auth_header(member_token),
        )

        assert response.status_code == 403

    async def test_non_admin_caller_is_403_regardless_of_target_user_existence(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        """A non-admin caller gets an identical `403` whether or not the target user exists.

        Regression for the authorization-ordering fix, mirroring the
        equivalent `POST /members` test above.
        """

        creator, _ = await _authed_user(db_session)
        member, member_token = await _authed_user(db_session)
        existing_target, _ = await _authed_user(db_session)
        channel = await _make_channel(
            db_session,
            creator=creator,
            members=[
                (member, ChannelMemberRole.MEMBER),
                (existing_target, ChannelMemberRole.MEMBER),
            ],
        )
        await db_session.commit()

        existing_target_response = client.delete(
            f"/v1/channels/{channel.id}/members/{existing_target.id}",
            headers=_auth_header(member_token),
        )
        nonexistent_target_response = client.delete(
            f"/v1/channels/{channel.id}/members/{generate_id()}",
            headers=_auth_header(member_token),
        )

        assert existing_target_response.status_code == 403
        assert nonexistent_target_response.status_code == 403
        assert (
            existing_target_response.json()["detail"]
            == nonexistent_target_response.json()["detail"]
        )

    async def test_missing_target_user_is_404(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, creator_token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=creator)
        await db_session.commit()

        response = client.delete(
            f"/v1/channels/{channel.id}/members/{generate_id()}",
            headers=_auth_header(creator_token),
        )

        assert response.status_code == 404

    async def test_missing_channel_is_404(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, token = await _authed_user(db_session)
        target, _ = await _authed_user(db_session)
        await db_session.commit()

        response = client.delete(
            f"/v1/channels/{generate_id()}/members/{target.id}",
            headers=_auth_header(token),
        )

        assert response.status_code == 404

    async def test_zero_admin_channel_is_409(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, creator_token = await _authed_user(db_session)
        member, _ = await _authed_user(db_session)
        channel = await _make_channel(
            db_session, creator=creator, members=[(member, ChannelMemberRole.MEMBER)]
        )
        await db_session.commit()

        # Self-demote the sole admin to `member` — legitimately produces
        # the F37 zero-admin terminal state (role-change never runs
        # succession).
        demote = client.patch(
            f"/v1/channels/{channel.id}/members/{creator.id}",
            headers=_auth_header(creator_token),
            json={"role": "member"},
        )
        assert demote.status_code == 200
        assert demote.json()["role"] == "member"

        response = client.delete(
            f"/v1/channels/{channel.id}/members/{member.id}",
            headers=_auth_header(creator_token),
        )

        assert response.status_code == 409
        assert response.headers["content-type"] == "application/problem+json"

    async def test_missing_auth_is_401(self, migrated_db: None, client: TestClient) -> None:
        response = client.delete(f"/v1/channels/{generate_id()}/members/{generate_id()}")

        assert response.status_code == 401


class TestSoleAdminSuccessionConcurrency:
    """Regression test for the F36 sole-admin-succession TOCTOU race.

    Analogous to `test_admin_api.py::TestLastAdminGuardConcurrency`: seeds
    a channel with *two* admins (`admin_a`, `admin_b`) and one other
    member (`early_member`), then fires both admins' `leave_channel`
    calls concurrently on independent sessions/connections. Each call,
    read in isolation, sees "2 admins -> not sole -> no succession
    needed" — but by the time both have committed, the channel actually
    has zero admins unless one of the two departures re-checks the
    *post-lock* admin count and runs succession. Without
    `_lock_channel_admin_ids`'s `FOR UPDATE` row lock forcing the second
    departure to block until the first commits and then re-read the
    now-shrunk admin set, both could observe "not sole" and skip
    succession entirely, leaving the channel with zero admins even though
    a member remains to promote. The lock serializes them so succession
    runs exactly once.
    """

    async def test_concurrent_departures_promote_exactly_one_successor(
        self,
        migrated_db: None,
        db_session: AsyncSession,
        postgres_available: bool,
    ) -> None:
        if not postgres_available:
            pytest.skip("local Postgres not reachable on localhost:5432")

        admin_a, _ = await _authed_user(db_session)
        admin_b, _ = await _authed_user(db_session)
        early_member, _ = await _authed_user(db_session)
        channel = await _make_channel(
            db_session,
            creator=admin_a,
            members=[
                (admin_b, ChannelMemberRole.ADMIN),
                (early_member, ChannelMemberRole.MEMBER),
            ],
            joined_at_offsets_seconds={
                str(admin_a.id): 0,
                str(admin_b.id): 5,
                str(early_member.id): 10,
            },
        )
        await db_session.commit()

        channel_id = channel.id
        admin_a_id, admin_b_id, early_member_id = admin_a.id, admin_b.id, early_member.id

        engine = create_async_engine(ASYNC_DATABASE_URL)
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

        async def _leave(user_id: object) -> LeaveOutcome:
            async with sessionmaker() as session:
                outcome = await leave_channel(session, channel_id=channel_id, user_id=user_id)
                await session.commit()
                return outcome

        try:
            outcome_a, outcome_b = await asyncio.gather(_leave(admin_a_id), _leave(admin_b_id))
        finally:
            await engine.dispose()

        # Both departures succeed (leave never raises `409`).
        assert outcome_a is LeaveOutcome.LEFT
        assert outcome_b is LeaveOutcome.LEFT

        db_session.expire_all()
        remaining_a = await _get_membership_row(
            db_session, channel_id=channel_id, user_id=admin_a_id
        )
        remaining_b = await _get_membership_row(
            db_session, channel_id=channel_id, user_id=admin_b_id
        )
        remaining_early = await _get_membership_row(
            db_session, channel_id=channel_id, user_id=early_member_id
        )

        assert remaining_a is None
        assert remaining_b is None
        # The invariant that matters: succession ran exactly once — the
        # only remaining member is promoted to admin, never left at zero
        # admins (lost update) and never double-promoted (there's only
        # one other member to promote here, but the row lock is what
        # guarantees this happens deterministically rather than racily).
        assert remaining_early is not None
        assert remaining_early.role == ChannelMemberRole.ADMIN
