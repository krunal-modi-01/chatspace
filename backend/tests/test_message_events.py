"""Unit tests for `app.services.message_events` (T24 envelope + publish).

Pure envelope-shape assertions plus a mocked-Redis publish-path test
(fail-open on `RedisError`) — no real Postgres/Redis needed. The
real-Redis end-to-end fan-out is covered by `tests/test_ws_fanout.py`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from redis.exceptions import RedisError

from app.core.ids import generate_id
from app.core.redis_keys import channel_topic, dm_topic
from app.models.attachment import Attachment, AttachmentKind
from app.models.message import Message
from app.services.message_events import (
    build_created_event,
    build_deleted_event,
    build_edited_event,
    publish_message_created,
    publish_message_deleted,
    publish_message_edited,
    publish_message_event,
)


def _attachment(**overrides: object) -> Attachment:
    defaults: dict[str, object] = {
        "id": generate_id(),
        "message_id": None,
        "uploader_id": uuid4(),
        "kind": AttachmentKind.IMAGE,
        "content_type": "image/png",
        "storage_key": f"key-{generate_id()}",
        "filename": "screenshot.png",
        "byte_size": 20481,
        "created_at": datetime(2026, 7, 2, 14, 31, 7, 482000, tzinfo=UTC),
    }
    defaults.update(overrides)
    return Attachment(**defaults)  # type: ignore[arg-type]


def _channel_message(**overrides: object) -> Message:
    defaults: dict[str, object] = {
        "id": generate_id(),
        "channel_id": uuid4(),
        "recipient_id": None,
        "sender_id": uuid4(),
        "content": "shipping the release now",
        "created_at": datetime(2026, 7, 2, 14, 31, 7, 482000, tzinfo=UTC),
        "edited_at": None,
        "deleted_at": None,
    }
    defaults.update(overrides)
    return Message(**defaults)  # type: ignore[arg-type]


def _dm_message(**overrides: object) -> Message:
    defaults: dict[str, object] = {
        "id": generate_id(),
        "channel_id": None,
        "recipient_id": uuid4(),
        "sender_id": uuid4(),
        "content": "hey, got a minute?",
        "created_at": datetime(2026, 7, 2, 14, 31, 7, 482000, tzinfo=UTC),
        "edited_at": None,
        "deleted_at": None,
    }
    defaults.update(overrides)
    return Message(**defaults)  # type: ignore[arg-type]


class TestBuildCreatedEvent:
    def test_matches_the_frozen_channel_envelope_shape(self) -> None:
        message = _channel_message()

        event = build_created_event(message)

        assert event["type"] == "message.created"
        assert event["conversation"] == {"kind": "channel", "channel_id": str(message.channel_id)}
        assert event["data"] == {
            "id": str(message.id),
            "channel_id": str(message.channel_id),
            "recipient_id": None,
            "sender_id": str(message.sender_id),
            "content": message.content,
            "media": [],
            "created_at": message.created_at.isoformat(),
            "edited_at": None,
            "deleted_at": None,
        }

    def test_media_is_always_present_and_empty_when_none_passed(self) -> None:
        """The frozen envelope's `data.media` field must never be dropped —
        an empty array when the caller passes no attachments (the default).
        """

        event = build_created_event(_channel_message())

        assert "media" in event["data"]
        assert event["data"]["media"] == []

    def test_bound_attachment_is_serialized_to_the_frozen_media_element_shape(self) -> None:
        """T29: a bound attachment must appear in `data.media[]` using the
        exact `{media_id, kind, filename, size}` element shape (contract
        line 710) — no `content_type`/`url` (those are T35's presigned-GET
        concern).
        """

        message = _channel_message()
        attachment = _attachment(
            kind=AttachmentKind.IMAGE, filename="screenshot.png", byte_size=20481
        )

        event = build_created_event(message, media=[attachment])

        assert event["data"]["media"] == [
            {
                "media_id": str(attachment.id),
                "kind": "image",
                "filename": "screenshot.png",
                "size": 20481,
            }
        ]

    def test_multiple_attachments_preserve_call_order(self) -> None:
        message = _channel_message()
        first = _attachment(filename="a.png")
        second = _attachment(filename="b.png")

        event = build_created_event(message, media=[first, second])

        assert [m["filename"] for m in event["data"]["media"]] == ["a.png", "b.png"]

    def test_dm_conversation_uses_the_persisted_recipient_id(self) -> None:
        message = _dm_message()

        event = build_created_event(message)

        assert event["conversation"] == {"kind": "dm", "user_id": str(message.recipient_id)}
        assert event["data"]["channel_id"] is None
        assert event["data"]["recipient_id"] == str(message.recipient_id)

    def test_is_json_serializable(self) -> None:
        event = build_created_event(_channel_message())

        # Must round-trip cleanly — this is exactly what gets published.
        json.loads(json.dumps(event))


class TestBuildEditedEvent:
    def test_carries_updated_content_and_non_null_edited_at(self) -> None:
        edited_at = datetime(2026, 7, 2, 15, 0, 0, tzinfo=UTC)
        message = _channel_message(content="shipping the release now (edited)", edited_at=edited_at)

        event = build_edited_event(message)

        assert event["type"] == "message.edited"
        assert event["data"]["content"] == "shipping the release now (edited)"
        assert event["data"]["edited_at"] == edited_at.isoformat()

    def test_id_and_conversation_unchanged_from_created(self) -> None:
        message = _channel_message()

        created = build_created_event(message)
        edited = build_edited_event(message)

        assert edited["data"]["id"] == created["data"]["id"]
        assert edited["conversation"] == created["conversation"]

    def test_currently_bound_media_is_carried_through(self) -> None:
        """T29: an edit doesn't change bound attachments, but the envelope's
        `data.media[]` must still reflect them, not a hardcoded `[]`.
        """

        message = _channel_message(edited_at=datetime.now(UTC))
        attachment = _attachment()

        event = build_edited_event(message, media=[attachment])

        assert event["data"]["media"] == [
            {
                "media_id": str(attachment.id),
                "kind": "image",
                "filename": attachment.filename,
                "size": attachment.byte_size,
            }
        ]


class TestBuildDeletedEvent:
    def test_data_is_exactly_id_conversation_deleted_at(self) -> None:
        deleted_at = datetime(2026, 7, 2, 16, 0, 0, tzinfo=UTC)
        message = _channel_message(deleted_at=deleted_at)

        event = build_deleted_event(message)

        assert event["type"] == "message.deleted"
        assert set(event["data"].keys()) == {"id", "conversation", "deleted_at"}
        assert event["data"]["id"] == str(message.id)
        assert event["data"]["conversation"] == event["conversation"]
        assert event["data"]["deleted_at"] == deleted_at.isoformat()

    def test_content_is_omitted(self) -> None:
        event = build_deleted_event(_channel_message(deleted_at=datetime.now(UTC)))

        assert "content" not in event["data"]
        assert "sender_id" not in event["data"]
        assert "media" not in event["data"]


class TestPublishForwardsMedia:
    """T29: `publish_message_created`/`publish_message_edited` must forward
    the `media` kwarg into the published payload, not silently drop it.
    """

    async def test_publish_message_created_forwards_media_into_the_payload(self) -> None:
        message = _channel_message()
        attachment = _attachment()
        redis = AsyncMock()

        await publish_message_created(redis, message, media=[attachment])

        redis.publish.assert_awaited_once()
        _topic, payload = redis.publish.await_args.args
        published = json.loads(payload)
        assert published["data"]["media"] == [
            {
                "media_id": str(attachment.id),
                "kind": "image",
                "filename": attachment.filename,
                "size": attachment.byte_size,
            }
        ]

    async def test_publish_message_edited_forwards_media_into_the_payload(self) -> None:
        message = _channel_message(edited_at=datetime.now(UTC))
        attachment = _attachment()
        redis = AsyncMock()

        await publish_message_edited(redis, message, media=[attachment])

        _topic, payload = redis.publish.await_args.args
        published = json.loads(payload)
        assert published["data"]["media"][0]["media_id"] == str(attachment.id)


class TestTopicDerivation:
    """Publish must land on the exact `redis_keys` topic builders' output."""

    async def test_channel_message_publishes_to_channel_topic(self) -> None:
        message = _channel_message()
        redis = AsyncMock()

        await publish_message_created(redis, message)

        redis.publish.assert_awaited_once()
        topic, _payload = redis.publish.await_args.args
        assert topic == channel_topic(message.channel_id)

    async def test_dm_message_publishes_to_canonical_dm_topic_regardless_of_direction(self) -> None:
        message = _dm_message()
        redis = AsyncMock()

        await publish_message_created(redis, message)

        topic, _payload = redis.publish.await_args.args
        assert topic == dm_topic(message.sender_id, message.recipient_id)
        assert topic == dm_topic(message.recipient_id, message.sender_id)


class TestPublishFailsOpen:
    """A Redis error must never propagate out of a publish call (ADR-0004)."""

    async def test_redis_error_is_swallowed_not_raised(self) -> None:
        redis = AsyncMock()
        redis.publish.side_effect = RedisError("boom")

        # Must not raise.
        await publish_message_created(redis, _channel_message())
        await publish_message_edited(redis, _channel_message(edited_at=datetime.now(UTC)))
        await publish_message_deleted(redis, _channel_message(deleted_at=datetime.now(UTC)))

    async def test_transport_timeout_is_also_swallowed(self) -> None:
        redis = AsyncMock()
        redis.publish.side_effect = TimeoutError("timed out")

        await publish_message_created(redis, _channel_message())

    async def test_a_non_redis_bug_still_propagates(self) -> None:
        """Fail-open only covers Redis/transport errors — a genuine bug (a
        non-JSON-serializable event) must not be silently swallowed.
        """

        redis = AsyncMock()
        not_serializable = {"type": "message.created", "data": {"bad": {1, 2, 3}}}

        with pytest.raises(TypeError):
            await publish_message_event(redis, not_serializable, topic="chan:x")

        redis.publish.assert_not_awaited()
