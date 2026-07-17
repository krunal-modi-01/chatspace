"""Integration tests for `/v1/channels/{id}/messages` + `/v1/messages/{id}` (T21).

Exercises the real routes end-to-end against Postgres + Redis (skipped
when unreachable): idempotent create-or-replay (F40), server-side
membership enforcement (F34), content validation (F39/`ck_messages_content`
mirror), media ownership/unbound validation (F39), cursor-paginated
history excluding soft-deleted rows (F44), and author-only edit/delete
(F42/F43) including the edit-after-delete `409` and delete-is-idempotent
`204` semantics.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.core.metrics import reset_metrics
from app.core.metrics import snapshot as metrics_snapshot
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.ids import generate_id
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.models.attachment import Attachment, AttachmentKind
from app.models.channel import Channel
from app.models.channel_member import ChannelMember, ChannelMemberRole
from app.models.message import Message
from app.models.session import Session
from app.models.user import User
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
    is_private: bool = False,
    members: list[User] | None = None,
) -> Channel:
    channel = Channel(
        id=generate_id(),
        name=f"channel-{generate_id().hex[-8:]}",
        is_private=is_private,
        created_by=creator.id,
    )
    db.add(channel)
    await db.flush()

    db.add(ChannelMember(channel_id=channel.id, user_id=creator.id, role=ChannelMemberRole.ADMIN))
    for member in members or []:
        db.add(
            ChannelMember(channel_id=channel.id, user_id=member.id, role=ChannelMemberRole.MEMBER)
        )
    await db.flush()
    return channel


async def _make_attachment(
    db: AsyncSession, *, uploader: User, message_id: object | None = None
) -> Attachment:
    attachment = Attachment(
        id=generate_id(),
        message_id=message_id,
        uploader_id=uploader.id,
        kind=AttachmentKind.IMAGE,
        content_type="image/png",
        storage_key=f"key-{generate_id()}",
        filename="screenshot.png",
        byte_size=1024,
    )
    db.add(attachment)
    await db.flush()
    return attachment


def _idem_key() -> str:
    return str(uuid.uuid4())


class TestSendChannelMessage:
    async def test_sends_message_and_returns_201(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        sender, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        await db_session.commit()

        reset_metrics()
        response = client.post(
            f"/v1/channels/{channel.id}/messages",
            headers={**_auth_header(token), "Idempotency-Key": _idem_key()},
            json={"content": "hello world"},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["channel_id"] == str(channel.id)
        assert body["recipient_id"] is None
        assert body["sender_id"] == str(sender.id)
        assert body["content"] == "hello world"
        assert body["media"] == []
        assert body["edited_at"] is None
        assert body["deleted_at"] is None
        uuid.UUID(body["id"])  # app-generated UUIDv7, well-formed

        # Key metric (technical spec §9): "message send throughput" —
        # a first-time (non-replay) channel send increments the
        # `message_send_success_total{conversation_kind=channel,replay=false}`
        # counter (T39; code review finding 1/2).
        counters = metrics_snapshot()["counters"]["message_send_success_total"]
        assert counters["conversation_kind=channel,replay=false"] == 1

    async def test_missing_idempotency_key_is_400(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        sender, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        await db_session.commit()

        response = client.post(
            f"/v1/channels/{channel.id}/messages",
            headers=_auth_header(token),
            json={"content": "hello"},
        )

        assert response.status_code == 400
        assert response.headers["content-type"] == "application/problem+json"

    async def test_malformed_idempotency_key_is_400(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        sender, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        await db_session.commit()

        response = client.post(
            f"/v1/channels/{channel.id}/messages",
            headers={**_auth_header(token), "Idempotency-Key": "not-a-uuid"},
            json={"content": "hello"},
        )

        assert response.status_code == 400

    async def test_replay_of_same_key_returns_original_row_exactly_once(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        sender, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        await db_session.commit()

        reset_metrics()
        key = _idem_key()
        first = client.post(
            f"/v1/channels/{channel.id}/messages",
            headers={**_auth_header(token), "Idempotency-Key": key},
            json={"content": "hello world"},
        )
        second = client.post(
            f"/v1/channels/{channel.id}/messages",
            headers={**_auth_header(token), "Idempotency-Key": key},
            json={"content": "hello world"},
        )

        assert first.status_code == 201
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]

        # Exactly one row landed in Postgres for this key.
        from sqlalchemy import func, select

        count = await db_session.scalar(
            select(func.count()).select_from(Message).where(Message.sender_id == sender.id)
        )
        assert count == 1

        # Code review finding 2: an idempotent replay must not be counted
        # as real throughput -- the first send is `replay=false`, the
        # replay is `replay=true`, and they are tracked as distinct label
        # combinations so a throughput reader can exclude replays.
        counters = metrics_snapshot()["counters"]["message_send_success_total"]
        assert counters["conversation_kind=channel,replay=false"] == 1
        assert counters["conversation_kind=channel,replay=true"] == 1

    async def test_non_member_is_403(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, _ = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=creator)
        _, outsider_token = await _authed_user(db_session)
        await db_session.commit()

        reset_metrics()
        response = client.post(
            f"/v1/channels/{channel.id}/messages",
            headers={**_auth_header(outsider_token), "Idempotency-Key": _idem_key()},
            json={"content": "hello"},
        )

        assert response.status_code == 403
        assert response.headers["content-type"] == "application/problem+json"

        # Key metric (technical spec §9): "message send error rate" —
        # the not-a-member business-rule rejection increments
        # `message_send_error_total{conversation_kind=channel,error_type=not_member}`
        # (T39; code review finding 1).
        counters = metrics_snapshot()["counters"]["message_send_error_total"]
        assert counters["conversation_kind=channel,error_type=not_member"] == 1

    async def test_missing_channel_is_404(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, token = await _authed_user(db_session)

        response = client.post(
            f"/v1/channels/{generate_id()}/messages",
            headers={**_auth_header(token), "Idempotency-Key": _idem_key()},
            json={"content": "hello"},
        )

        assert response.status_code == 404

    @pytest.mark.parametrize("content", ["", "   ", "x" * 4001])
    async def test_invalid_content_is_422(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        content: str,
    ) -> None:
        sender, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        await db_session.commit()

        response = client.post(
            f"/v1/channels/{channel.id}/messages",
            headers={**_auth_header(token), "Idempotency-Key": _idem_key()},
            json={"content": content},
        )

        assert response.status_code == 422
        assert response.headers["content-type"] == "application/problem+json"

    async def test_unknown_media_id_is_422(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        sender, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        await db_session.commit()

        response = client.post(
            f"/v1/channels/{channel.id}/messages",
            headers={**_auth_header(token), "Idempotency-Key": _idem_key()},
            json={"content": "hello", "media_ids": [str(generate_id())]},
        )

        assert response.status_code == 422

    async def test_media_not_owned_by_sender_is_422(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        sender, token = await _authed_user(db_session)
        other_uploader, _ = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        attachment = await _make_attachment(db_session, uploader=other_uploader)
        await db_session.commit()

        response = client.post(
            f"/v1/channels/{channel.id}/messages",
            headers={**_auth_header(token), "Idempotency-Key": _idem_key()},
            json={"content": "hello", "media_ids": [str(attachment.id)]},
        )

        assert response.status_code == 422

    async def test_already_bound_media_is_422(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        sender, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        other_message = Message(
            id=generate_id(), channel_id=channel.id, sender_id=sender.id, content="prior message"
        )
        db_session.add(other_message)
        await db_session.flush()
        attachment = await _make_attachment(
            db_session, uploader=sender, message_id=other_message.id
        )
        await db_session.commit()

        response = client.post(
            f"/v1/channels/{channel.id}/messages",
            headers={**_auth_header(token), "Idempotency-Key": _idem_key()},
            json={"content": "hello", "media_ids": [str(attachment.id)]},
        )

        assert response.status_code == 422

    async def test_sends_with_valid_unbound_media(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        sender, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        attachment = await _make_attachment(db_session, uploader=sender)
        await db_session.commit()

        response = client.post(
            f"/v1/channels/{channel.id}/messages",
            headers={**_auth_header(token), "Idempotency-Key": _idem_key()},
            json={"content": "hello", "media_ids": [str(attachment.id)]},
        )

        assert response.status_code == 201
        body = response.json()
        assert len(body["media"]) == 1
        assert body["media"][0]["media_id"] == str(attachment.id)
        assert body["media"][0]["kind"] == "image"
        assert body["media"][0]["filename"] == "screenshot.png"
        assert body["media"][0]["size"] == 1024

        await db_session.refresh(attachment)
        assert attachment.message_id == uuid.UUID(body["id"])

    async def test_missing_auth_is_401(self, migrated_db: None, client: TestClient) -> None:
        response = client.post(
            f"/v1/channels/{generate_id()}/messages",
            headers={"Idempotency-Key": _idem_key()},
            json={"content": "hello"},
        )

        assert response.status_code == 401


class TestChannelMessageHistory:
    async def test_returns_messages_excluding_soft_deleted(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        sender, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)

        visible = Message(
            id=generate_id(), channel_id=channel.id, sender_id=sender.id, content="visible"
        )
        deleted = Message(
            id=generate_id(),
            channel_id=channel.id,
            sender_id=sender.id,
            content="deleted",
            deleted_at=datetime.now(UTC),
        )
        db_session.add_all([visible, deleted])
        await db_session.commit()

        response = client.get(f"/v1/channels/{channel.id}/messages", headers=_auth_header(token))

        assert response.status_code == 200
        body = response.json()
        ids = [item["id"] for item in body["items"]]
        assert str(visible.id) in ids
        assert str(deleted.id) not in ids

    async def test_cursor_pagination_walks_full_history(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        sender, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)

        created_ids: list[str] = []
        base = datetime.now(UTC)
        for i in range(5):
            message = Message(
                id=generate_id(),
                channel_id=channel.id,
                sender_id=sender.id,
                content=f"message {i}",
                created_at=base + timedelta(seconds=i),
            )
            db_session.add(message)
            await db_session.flush()
            created_ids.append(str(message.id))
        await db_session.commit()

        collected: list[str] = []
        cursor: str | None = None
        for _ in range(10):  # bound the loop in case of a pagination bug
            params = {"limit": "2"}
            if cursor is not None:
                params["cursor"] = cursor
            response = client.get(
                f"/v1/channels/{channel.id}/messages",
                headers=_auth_header(token),
                params=params,
            )
            assert response.status_code == 200
            body = response.json()
            collected.extend(item["id"] for item in body["items"])
            cursor = body["next_cursor"]
            if cursor is None:
                break

        assert set(collected) == set(created_ids)
        assert len(collected) == len(created_ids)

    async def test_non_member_is_403(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        creator, _ = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=creator)
        _, outsider_token = await _authed_user(db_session)
        await db_session.commit()

        response = client.get(
            f"/v1/channels/{channel.id}/messages", headers=_auth_header(outsider_token)
        )

        assert response.status_code == 403

    async def test_missing_channel_is_404(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, token = await _authed_user(db_session)

        response = client.get(f"/v1/channels/{generate_id()}/messages", headers=_auth_header(token))

        assert response.status_code == 404

    async def test_invalid_cursor_is_400(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        sender, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        await db_session.commit()

        response = client.get(
            f"/v1/channels/{channel.id}/messages",
            headers=_auth_header(token),
            params={"cursor": "not-valid-base64!!"},
        )

        assert response.status_code == 400

    async def test_invalid_limit_is_400(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        sender, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        await db_session.commit()

        response = client.get(
            f"/v1/channels/{channel.id}/messages",
            headers=_auth_header(token),
            params={"limit": "0"},
        )

        assert response.status_code == 400


class TestEditMessage:
    async def test_author_can_edit(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        sender, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        message = Message(
            id=generate_id(), channel_id=channel.id, sender_id=sender.id, content="original"
        )
        db_session.add(message)
        await db_session.commit()

        response = client.patch(
            f"/v1/messages/{message.id}",
            headers=_auth_header(token),
            json={"content": "edited"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["content"] == "edited"
        assert body["edited_at"] is not None

    async def test_non_author_is_403(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        sender, _ = await _authed_user(db_session)
        other, other_token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender, members=[other])
        message = Message(
            id=generate_id(), channel_id=channel.id, sender_id=sender.id, content="original"
        )
        db_session.add(message)
        await db_session.commit()

        response = client.patch(
            f"/v1/messages/{message.id}",
            headers=_auth_header(other_token),
            json={"content": "hijacked"},
        )

        assert response.status_code == 403

    async def test_non_member_gets_uniform_404(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        sender, _ = await _authed_user(db_session)
        _, outsider_token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        message = Message(
            id=generate_id(), channel_id=channel.id, sender_id=sender.id, content="original"
        )
        db_session.add(message)
        await db_session.commit()

        response = client.patch(
            f"/v1/messages/{message.id}",
            headers=_auth_header(outsider_token),
            json={"content": "hijacked"},
        )

        assert response.status_code == 404

    async def test_missing_message_is_404(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, token = await _authed_user(db_session)

        response = client.patch(
            f"/v1/messages/{generate_id()}",
            headers=_auth_header(token),
            json={"content": "hello"},
        )

        assert response.status_code == 404

    async def test_edit_after_delete_is_409(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        sender, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        message = Message(
            id=generate_id(),
            channel_id=channel.id,
            sender_id=sender.id,
            content="original",
            deleted_at=datetime.now(UTC),
        )
        db_session.add(message)
        await db_session.commit()

        response = client.patch(
            f"/v1/messages/{message.id}",
            headers=_auth_header(token),
            json={"content": "too late"},
        )

        assert response.status_code == 409

    @pytest.mark.parametrize("content", ["", "   ", "x" * 4001])
    async def test_invalid_content_is_422(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        content: str,
    ) -> None:
        sender, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        message = Message(
            id=generate_id(), channel_id=channel.id, sender_id=sender.id, content="original"
        )
        db_session.add(message)
        await db_session.commit()

        response = client.patch(
            f"/v1/messages/{message.id}",
            headers=_auth_header(token),
            json={"content": content},
        )

        assert response.status_code == 422

    async def test_resending_same_content_is_safe_noop(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        sender, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        message = Message(
            id=generate_id(), channel_id=channel.id, sender_id=sender.id, content="original"
        )
        db_session.add(message)
        await db_session.commit()

        response = client.patch(
            f"/v1/messages/{message.id}",
            headers=_auth_header(token),
            json={"content": "original"},
        )

        assert response.status_code == 200
        assert response.json()["content"] == "original"
        assert response.json()["edited_at"] is None


class TestDeleteMessage:
    async def test_author_can_delete(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        sender, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        message = Message(
            id=generate_id(), channel_id=channel.id, sender_id=sender.id, content="original"
        )
        db_session.add(message)
        await db_session.commit()

        response = client.delete(f"/v1/messages/{message.id}", headers=_auth_header(token))

        assert response.status_code == 204

        await db_session.refresh(message)
        assert message.deleted_at is not None

    async def test_repeat_delete_is_still_204(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        sender, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        message = Message(
            id=generate_id(),
            channel_id=channel.id,
            sender_id=sender.id,
            content="original",
            deleted_at=datetime.now(UTC),
        )
        db_session.add(message)
        await db_session.commit()

        response = client.delete(f"/v1/messages/{message.id}", headers=_auth_header(token))

        assert response.status_code == 204

    async def test_non_author_is_403(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        sender, _ = await _authed_user(db_session)
        other, other_token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender, members=[other])
        message = Message(
            id=generate_id(), channel_id=channel.id, sender_id=sender.id, content="original"
        )
        db_session.add(message)
        await db_session.commit()

        response = client.delete(f"/v1/messages/{message.id}", headers=_auth_header(other_token))

        assert response.status_code == 403

    async def test_missing_message_is_404(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, token = await _authed_user(db_session)

        response = client.delete(f"/v1/messages/{generate_id()}", headers=_auth_header(token))

        assert response.status_code == 404

    async def test_missing_auth_is_401(self, migrated_db: None, client: TestClient) -> None:
        response = client.delete(f"/v1/messages/{generate_id()}")

        assert response.status_code == 401


class TestSendChannelMessageIdempotencyTimeout:
    """Direct unit coverage of the `503` fail-closed path (code-review finding).

    Unlike `TestSendChannelMessageIdempotencyConcurrency` below (which
    exercises the real bounded resolve loop against real Postgres/Redis to
    prove exactly-one-row), this only needs the route's own error mapping:
    monkeypatch `send_channel_message` itself to raise
    `IdempotencyResolutionTimeoutError` and assert the `503` + `Retry-After`
    + problem+json envelope `app.api.messages` builds for it. No real
    concurrent race, no Redis probing — so no `postgres_available`/
    `redis_available` skip guard here beyond what `client`/`db_session`
    already need to stand up an authed user and channel.
    """

    async def test_resolution_timeout_returns_503_with_retry_after(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.services.messages import IdempotencyResolutionTimeoutError

        sender, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        await db_session.commit()

        async def _always_times_out(*args: object, **kwargs: object) -> None:
            raise IdempotencyResolutionTimeoutError("forced for test")

        monkeypatch.setattr("app.api.messages.send_channel_message", _always_times_out)

        response = client.post(
            f"/v1/channels/{channel.id}/messages",
            headers={**_auth_header(token), "Idempotency-Key": _idem_key()},
            json={"content": "hello world"},
        )

        assert response.status_code == 503
        assert response.headers["Retry-After"] == "1"
        assert response.headers["content-type"] == "application/problem+json"

        body = response.json()
        assert body["status"] == 503
        assert body["type"]
        assert body["title"]
        assert body["detail"]
        assert body["correlation_id"]


class TestSendChannelMessageIdempotencyConcurrency:
    """Regression test for the F40 concurrent-replay-race bug.

    Analogous to `test_admin_api.py::TestLastAdminGuardConcurrency` and
    `test_channels_membership_api.py::TestSoleAdminSuccessionConcurrency`:
    fires two `send_channel_message` calls with the *same* `(sender_id,
    idempotency_key)` concurrently on independent sessions/connections
    (bypassing `TestClient`, which is synchronous and cannot express this
    race). Without the bounded resolve loop in
    `app.services.messages._resolve_existing_claim`, the loser could read
    the winner's still-uncommitted claim, find no visible row under READ
    COMMITTED, and fall through to a blind insert — landing two rows for
    one key. The resolve loop's retries let the winner's commit land before
    the loser gives up, so exactly one row is ever created.
    """

    async def test_concurrent_sends_same_key_yield_exactly_one_row(
        self,
        migrated_db: None,
        db_session: AsyncSession,
        postgres_available: bool,
        redis_available: bool,
    ) -> None:
        if not postgres_available:
            pytest.skip("local Postgres not reachable on localhost:5425")
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        from app.db.redis import dispose_redis_client, get_redis_client
        from app.services.messages import send_channel_message

        sender, _ = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        await db_session.commit()

        sender_id, channel_id = sender.id, channel.id
        key = _idem_key()
        # `get_redis_client` is a process-wide `lru_cache`; a client built
        # under a *different* test function's event loop (which
        # pytest-asyncio tears down per-test) holds a dead connection pool.
        # Force a fresh client bound to this test's running loop, and
        # dispose it again on the way out so the next test isn't left
        # holding a client bound to *this* loop once it closes.
        await dispose_redis_client()
        redis = get_redis_client()

        engine = create_async_engine(ASYNC_DATABASE_URL)
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

        async def _send() -> tuple[uuid.UUID, bool]:
            async with sessionmaker() as session:
                result = await send_channel_message(
                    session,
                    redis,
                    channel_id=channel_id,
                    sender_id=sender_id,
                    content="racey idempotent send",
                    media_ids=[],
                    idempotency_key=key,
                )
                return result.message.id, result.created

        try:
            (id_a, created_a), (id_b, created_b) = await asyncio.gather(_send(), _send())
        finally:
            await engine.dispose()
            await dispose_redis_client()

        # Exactly one of the two calls actually created the row (the `201`
        # case); the other observed it as a replay (the `200` case) — never
        # both `True` (that would mean two rows) and never both `False`
        # (that would mean neither call ever created anything).
        assert sorted([created_a, created_b]) == [False, True]
        # Both calls reference the very same message id.
        assert id_a == id_b

        from sqlalchemy import func, select

        count = await db_session.scalar(
            select(func.count()).select_from(Message).where(Message.sender_id == sender_id)
        )
        assert count == 1


class TestSendChannelMessageMediaBindConcurrency:
    """Regression test for the F39 media-bind TOCTOU race.

    Two concurrent sends (distinct `Idempotency-Key`s, so this is
    exercising the media bind, not the idempotency claim) both try to bind
    the *same* unbound attachment. Without the atomic guarded `UPDATE` in
    `app.services.messages._bind_media_atomically`, both could read the
    attachment as unbound before either wrote, both assign
    `attachment.message_id`, and both commit — leaving the last writer's
    message as the attachment's final owner despite the other message's
    response having already claimed it too. The atomic `UPDATE ...  WHERE
    message_id IS NULL`'s row lock serializes the two, so exactly one call
    succeeds and the other observes the now-bound attachment as unusable
    (`422`).
    """

    async def test_concurrent_sends_binding_same_media_id_exactly_one_wins(
        self,
        migrated_db: None,
        db_session: AsyncSession,
        postgres_available: bool,
        redis_available: bool,
    ) -> None:
        if not postgres_available:
            pytest.skip("local Postgres not reachable on localhost:5425")
        if not redis_available:
            pytest.skip("local Redis not reachable on localhost:6380")

        from app.db.redis import dispose_redis_client, get_redis_client
        from app.services.messages import InvalidMediaError, send_channel_message

        sender, _ = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        attachment = await _make_attachment(db_session, uploader=sender)
        await db_session.commit()

        sender_id, channel_id, media_id = sender.id, channel.id, attachment.id
        # See `TestSendChannelMessageIdempotencyConcurrency` for why the
        # cached client must be rebuilt under this test's own event loop.
        await dispose_redis_client()
        redis = get_redis_client()

        engine = create_async_engine(ASYNC_DATABASE_URL)
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

        async def _send(idempotency_key: str) -> tuple[str, uuid.UUID | None]:
            async with sessionmaker() as session:
                try:
                    result = await send_channel_message(
                        session,
                        redis,
                        channel_id=channel_id,
                        sender_id=sender_id,
                        content="racey media bind",
                        media_ids=[media_id],
                        idempotency_key=idempotency_key,
                    )
                except InvalidMediaError:
                    return "422", None
                return "ok", result.message.id

        try:
            outcome_a, outcome_b = await asyncio.gather(_send(_idem_key()), _send(_idem_key()))
        finally:
            await engine.dispose()
            await dispose_redis_client()

        # Exactly one call binds the attachment; the other is rejected —
        # never both succeeding (double-bound) and never both rejected
        # (the attachment was genuinely unbound and available to one of
        # them).
        assert sorted(outcome[0] for outcome in (outcome_a, outcome_b)) == ["422", "ok"]

        winning_outcome = outcome_a if outcome_a[0] == "ok" else outcome_b
        winning_message_id = winning_outcome[1]
        assert winning_message_id is not None

        db_session.expire_all()
        await db_session.refresh(attachment)
        assert attachment.message_id == winning_message_id

        # Exactly one message row exists for this sender (the winner's) —
        # the loser's insert was fully rolled back, not left as an
        # unbound-media orphan row.
        from sqlalchemy import func, select

        count = await db_session.scalar(
            select(func.count()).select_from(Message).where(Message.sender_id == sender_id)
        )
        assert count == 1
