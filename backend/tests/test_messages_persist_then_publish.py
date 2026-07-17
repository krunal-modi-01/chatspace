"""End-to-end persist-then-publish tests for T24, driven through the real
`/v1/channels/{id}/messages` / `/v1/dms/{user_id}/messages` /
`/v1/messages/{id}` routes against real Postgres + Redis (skipped when
either is unreachable).

Proves, via a raw Redis `SUBSCRIBE` on the exact canonical topic (not
`ConnectionManager`/`PubSubRelay`, which are covered separately in
`tests/test_ws_fanout.py`):

- `message.created`/`edited`/`deleted` are published to the frozen
  envelope shape carrying the message id, only *after* the triggering
  request's transaction has committed — proven by independently
  re-reading the row over a brand-new DB connection at the moment the
  event is received.
- An idempotent replay (`send`) and a no-op (`edit`/`delete`) never
  produce a second publish.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.ids import generate_id
from app.core.jwt import create_access_token
from app.core.redis_keys import channel_topic, dm_topic
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


async def _make_channel(db: AsyncSession, *, creator: User) -> Channel:
    channel = Channel(
        id=generate_id(),
        name=f"channel-{generate_id().hex[-8:]}",
        is_private=False,
        created_by=creator.id,
    )
    db.add(channel)
    await db.flush()
    db.add(ChannelMember(channel_id=channel.id, user_id=creator.id, role=ChannelMemberRole.ADMIN))
    await db.flush()
    return channel


async def _make_attachment(db: AsyncSession, *, uploader: User) -> Attachment:
    attachment = Attachment(
        id=generate_id(),
        message_id=None,
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


async def _subscribe(redis: Any, topic: str) -> Any:
    pubsub = redis.pubsub()
    await pubsub.subscribe(topic)
    # Drain the subscribe confirmation itself.
    await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
    return pubsub


async def _next_event(pubsub: Any, *, timeout_seconds: float = 5.0) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while loop.time() < deadline:
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
        if message is not None:
            data = message["data"]
            assert isinstance(data, str)
            return json.loads(data)  # type: ignore[no-any-return]
    raise AssertionError(f"no event received within {timeout_seconds}s")


async def _no_further_event(pubsub: Any, *, wait_seconds: float = 0.5) -> None:
    """Assert nothing more arrives within `wait_seconds` (proves "no republish")."""

    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=wait_seconds)
    assert message is None, f"unexpected extra event: {message}"


async def _row_visible_over_a_fresh_connection(message_id: uuid.UUID) -> bool:
    """Query `message_id` over a brand-new engine/connection (not the app's
    pooled session), proving the row is durably committed — not just
    visible within the writer's own still-open session — at the moment
    the fan-out event is observed.
    """

    engine = create_async_engine(ASYNC_DATABASE_URL)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(select(Message).where(Message.id == message_id))
            return result.first() is not None
    finally:
        await engine.dispose()


@pytest.fixture
async def redis_client(redis_available: bool):  # type: ignore[no-untyped-def]
    """A throwaway Redis client, deliberately *not* the app's process-wide
    `get_redis_client()` singleton.

    `client.post`/`client.delete`/`client.patch` (via `TestClient`) run the
    real ASGI app on its own portal thread + event loop, distinct from
    this test coroutine's own loop. If this fixture instead primed/reused
    the cached `get_redis_client()` instance, the very first HTTP call
    would bind a pooled connection to the *portal's* loop, and this test's
    own `pubsub()` subscribe (running on the test's loop) could then pick
    up that same pooled connection and crash with redis-py's "attached to
    a different loop" error. A dedicated client, talking to the same
    Redis server but never shared with the app, sidesteps that entirely
    — the subscriber and the app's publisher are independent connections
    to the same server, exactly as they would be across two real
    processes/instances.
    """

    if not redis_available:
        pytest.skip("local Redis not reachable on localhost:6380")

    from redis.asyncio import Redis

    raw_client = Redis.from_url(REQUIRED_ENV["REDIS_URL"], decode_responses=True)
    yield raw_client
    await raw_client.aclose()


class TestChannelSendPublishesAfterCommit:
    async def test_created_event_arrives_with_the_committed_row_already_durable(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_client: Any,
    ) -> None:
        sender, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        await db_session.commit()

        topic = channel_topic(channel.id)
        pubsub = await _subscribe(redis_client, topic)
        try:
            response = client.post(
                f"/v1/channels/{channel.id}/messages",
                headers={**_auth_header(token), "Idempotency-Key": _idem_key()},
                json={"content": "shipping the release now"},
            )
            assert response.status_code == 201
            message_id = response.json()["id"]

            event = await _next_event(pubsub)

            assert event["type"] == "message.created"
            assert event["conversation"] == {"kind": "channel", "channel_id": str(channel.id)}
            assert event["data"]["id"] == message_id
            assert event["data"]["channel_id"] == str(channel.id)
            assert event["data"]["recipient_id"] is None
            assert event["data"]["content"] == "shipping the release now"
            assert event["data"]["media"] == []
            assert event["data"]["edited_at"] is None
            assert event["data"]["deleted_at"] is None

            # The event only ever fires after `db.commit()` returns — prove
            # the row is already durable (visible over an independent
            # connection) at the moment it's observed.
            assert await _row_visible_over_a_fresh_connection(uuid.UUID(message_id))
        finally:
            await pubsub.unsubscribe(topic)
            await pubsub.aclose()

    async def test_idempotent_replay_does_not_republish(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_client: Any,
    ) -> None:
        sender, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        await db_session.commit()

        topic = channel_topic(channel.id)
        pubsub = await _subscribe(redis_client, topic)
        try:
            key = _idem_key()
            headers = {**_auth_header(token), "Idempotency-Key": key}

            first = client.post(
                f"/v1/channels/{channel.id}/messages",
                headers=headers,
                json={"content": "hello"},
            )
            assert first.status_code == 201
            await _next_event(pubsub)

            second = client.post(
                f"/v1/channels/{channel.id}/messages",
                headers=headers,
                json={"content": "hello"},
            )
            assert second.status_code == 200
            assert second.json()["id"] == first.json()["id"]

            # The replay must not trigger a second publish.
            await _no_further_event(pubsub)
        finally:
            await pubsub.unsubscribe(topic)
            await pubsub.aclose()


class TestCreatedEventCarriesBoundMedia:
    """T29: the WS `message.created` payload's `media[]` must reflect the
    attachments this send just bound — not the T24-era hardcoded `[]`.
    """

    async def test_bound_attachment_appears_in_the_created_event(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_client: Any,
    ) -> None:
        sender, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        attachment = await _make_attachment(db_session, uploader=sender)
        await db_session.commit()

        topic = channel_topic(channel.id)
        pubsub = await _subscribe(redis_client, topic)
        try:
            response = client.post(
                f"/v1/channels/{channel.id}/messages",
                headers={**_auth_header(token), "Idempotency-Key": _idem_key()},
                json={"content": "shipping with a screenshot", "media_ids": [str(attachment.id)]},
            )
            assert response.status_code == 201
            message_id = response.json()["id"]

            event = await _next_event(pubsub)

            assert event["data"]["id"] == message_id
            assert event["data"]["media"] == [
                {
                    "media_id": str(attachment.id),
                    "kind": "image",
                    "filename": "screenshot.png",
                    "size": 1024,
                }
            ]
        finally:
            await pubsub.unsubscribe(topic)
            await pubsub.aclose()


class TestDMSendPublishesToCanonicalTopic:
    async def test_dm_created_event_uses_the_canonical_dm_topic(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_client: Any,
    ) -> None:
        sender, token = await _authed_user(db_session)
        recipient, _ = await _authed_user(db_session)
        await db_session.commit()

        topic = dm_topic(sender.id, recipient.id)
        pubsub = await _subscribe(redis_client, topic)
        try:
            response = client.post(
                f"/v1/dms/{recipient.id}/messages",
                headers={**_auth_header(token), "Idempotency-Key": _idem_key()},
                json={"content": "hey, got a minute?"},
            )
            assert response.status_code == 201
            message_id = response.json()["id"]

            event = await _next_event(pubsub)

            assert event["type"] == "message.created"
            assert event["conversation"] == {"kind": "dm", "user_id": str(recipient.id)}
            assert event["data"]["id"] == message_id
            assert event["data"]["channel_id"] is None
            assert event["data"]["recipient_id"] == str(recipient.id)
            assert event["data"]["sender_id"] == str(sender.id)
        finally:
            await pubsub.unsubscribe(topic)
            await pubsub.aclose()


class TestEditPublishesAfterCommit:
    async def test_edit_publishes_updated_content_and_carries_id(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_client: Any,
    ) -> None:
        sender, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        await db_session.commit()

        send = client.post(
            f"/v1/channels/{channel.id}/messages",
            headers={**_auth_header(token), "Idempotency-Key": _idem_key()},
            json={"content": "original"},
        )
        assert send.status_code == 201
        message_id = send.json()["id"]

        topic = channel_topic(channel.id)
        pubsub = await _subscribe(redis_client, topic)
        try:
            edit = client.patch(
                f"/v1/messages/{message_id}",
                headers=_auth_header(token),
                json={"content": "original (edited)"},
            )
            assert edit.status_code == 200

            event = await _next_event(pubsub)

            assert event["type"] == "message.edited"
            assert event["data"]["id"] == message_id
            assert event["data"]["content"] == "original (edited)"
            assert event["data"]["edited_at"] is not None
            assert await _row_visible_over_a_fresh_connection(uuid.UUID(message_id))
        finally:
            await pubsub.unsubscribe(topic)
            await pubsub.aclose()

    async def test_unchanged_content_edit_does_not_publish(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_client: Any,
    ) -> None:
        sender, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        await db_session.commit()

        send = client.post(
            f"/v1/channels/{channel.id}/messages",
            headers={**_auth_header(token), "Idempotency-Key": _idem_key()},
            json={"content": "same content"},
        )
        assert send.status_code == 201
        message_id = send.json()["id"]

        topic = channel_topic(channel.id)
        pubsub = await _subscribe(redis_client, topic)
        try:
            edit = client.patch(
                f"/v1/messages/{message_id}",
                headers=_auth_header(token),
                json={"content": "same content"},
            )
            assert edit.status_code == 200

            await _no_further_event(pubsub)
        finally:
            await pubsub.unsubscribe(topic)
            await pubsub.aclose()


class TestDeletePublishesAfterCommit:
    async def test_delete_publishes_id_conversation_and_deleted_at_only(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_client: Any,
    ) -> None:
        sender, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        await db_session.commit()

        send = client.post(
            f"/v1/channels/{channel.id}/messages",
            headers={**_auth_header(token), "Idempotency-Key": _idem_key()},
            json={"content": "to be deleted"},
        )
        assert send.status_code == 201
        message_id = send.json()["id"]

        topic = channel_topic(channel.id)
        pubsub = await _subscribe(redis_client, topic)
        try:
            delete = client.delete(f"/v1/messages/{message_id}", headers=_auth_header(token))
            assert delete.status_code == 204

            event = await _next_event(pubsub)

            assert event["type"] == "message.deleted"
            assert set(event["data"].keys()) == {"id", "conversation", "deleted_at"}
            assert event["data"]["id"] == message_id
            assert event["data"]["conversation"] == {
                "kind": "channel",
                "channel_id": str(channel.id),
            }
            assert event["data"]["deleted_at"] is not None
            assert await _row_visible_over_a_fresh_connection(uuid.UUID(message_id))
        finally:
            await pubsub.unsubscribe(topic)
            await pubsub.aclose()

    async def test_repeat_delete_does_not_republish(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        redis_client: Any,
    ) -> None:
        sender, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=sender)
        await db_session.commit()

        send = client.post(
            f"/v1/channels/{channel.id}/messages",
            headers={**_auth_header(token), "Idempotency-Key": _idem_key()},
            json={"content": "to be deleted twice"},
        )
        assert send.status_code == 201
        message_id = send.json()["id"]

        topic = channel_topic(channel.id)
        pubsub = await _subscribe(redis_client, topic)
        try:
            first_delete = client.delete(f"/v1/messages/{message_id}", headers=_auth_header(token))
            assert first_delete.status_code == 204
            await _next_event(pubsub)

            second_delete = client.delete(f"/v1/messages/{message_id}", headers=_auth_header(token))
            assert second_delete.status_code == 204

            await _no_further_event(pubsub)
        finally:
            await pubsub.unsubscribe(topic)
            await pubsub.aclose()
