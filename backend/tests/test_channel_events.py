"""Unit tests for `app.services.channel_events` (T49 envelope + publish).

Pure envelope-shape assertions plus a mocked-Redis publish-path test
(fail-open on `RedisError`) — no real Postgres/Redis needed. Cross-instance
delivery via the real `user:*` pattern subscription is covered by
`tests/test_ws_fanout.py`; end-to-end route-level publish is covered by
`tests/test_channels_membership_api.py`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from redis.exceptions import RedisError

from app.core.ids import generate_id
from app.core.redis_keys import user_topic
from app.models.channel import Channel
from app.models.channel_member import ChannelMemberRole
from app.services.channel_events import (
    build_member_added_event,
    build_member_removed_event,
    publish_channel_event,
    publish_member_added,
    publish_member_removed,
)


def _channel(**overrides: object) -> Channel:
    defaults: dict[str, object] = {
        "id": generate_id(),
        "name": "engineering",
        "is_private": False,
        "created_by": uuid4(),
        "created_at": datetime(2026, 7, 2, 14, 31, 7, 482000, tzinfo=UTC),
    }
    defaults.update(overrides)
    return Channel(**defaults)  # type: ignore[arg-type]


class TestBuildMemberAddedEvent:
    def test_matches_the_frozen_envelope_shape(self) -> None:
        channel = _channel()
        user_id = uuid4()
        joined_at = datetime(2026, 7, 3, 9, 0, 0, tzinfo=UTC)

        event = build_member_added_event(
            channel,
            user_id=user_id,
            role=ChannelMemberRole.MEMBER,
            joined_at=joined_at,
            member_count=3,
        )

        assert event["type"] == "channel.member_added"
        assert event["conversation"] == {"kind": "channel", "channel_id": str(channel.id)}
        assert event["data"] == {
            "channel": {
                "id": str(channel.id),
                "name": channel.name,
                "is_private": channel.is_private,
                "created_by": str(channel.created_by),
                "created_at": channel.created_at.isoformat(),
                "member_count": 3,
            },
            "user_id": str(user_id),
            "role": "member",
            "joined_at": joined_at.isoformat(),
        }

    def test_channel_summary_has_exactly_six_fields_no_my_role(self) -> None:
        """Contract note: `data.channel` deliberately has no `my_role`,
        unlike a `GET /v1/channels` row.
        """

        event = build_member_added_event(
            _channel(),
            user_id=uuid4(),
            role=ChannelMemberRole.ADMIN,
            joined_at=datetime.now(UTC),
            member_count=1,
        )

        assert set(event["data"]["channel"].keys()) == {
            "id",
            "name",
            "is_private",
            "created_by",
            "created_at",
            "member_count",
        }

    def test_admin_role_serializes_to_its_wire_value(self) -> None:
        event = build_member_added_event(
            _channel(),
            user_id=uuid4(),
            role=ChannelMemberRole.ADMIN,
            joined_at=datetime.now(UTC),
            member_count=1,
        )

        assert event["data"]["role"] == "admin"

    def test_is_json_serializable(self) -> None:
        event = build_member_added_event(
            _channel(),
            user_id=uuid4(),
            role=ChannelMemberRole.MEMBER,
            joined_at=datetime.now(UTC),
            member_count=1,
        )

        json.loads(json.dumps(event))


class TestBuildMemberRemovedEvent:
    def test_data_is_exactly_channel_id_and_user_id_no_channel_metadata(self) -> None:
        channel_id = uuid4()
        user_id = uuid4()

        event = build_member_removed_event(channel_id=channel_id, user_id=user_id)

        assert event["type"] == "channel.member_removed"
        assert event["conversation"] == {"kind": "channel", "channel_id": str(channel_id)}
        assert event["data"] == {"channel_id": str(channel_id), "user_id": str(user_id)}

    def test_no_channel_summary_fields_leak_in(self) -> None:
        event = build_member_removed_event(channel_id=uuid4(), user_id=uuid4())

        assert "channel" not in event["data"]
        assert "name" not in event["data"]
        assert "is_private" not in event["data"]

    def test_is_json_serializable(self) -> None:
        event = build_member_removed_event(channel_id=uuid4(), user_id=uuid4())

        json.loads(json.dumps(event))


class TestPublishTopicIsThePerUserTopic:
    """Both publish helpers must target the affected user's own `user:{id}` topic."""

    async def test_member_added_publishes_to_the_added_users_own_topic(self) -> None:
        channel = _channel()
        added_user_id = uuid4()
        redis = AsyncMock()

        await publish_member_added(
            redis,
            channel,
            user_id=added_user_id,
            role=ChannelMemberRole.MEMBER,
            joined_at=datetime.now(UTC),
            member_count=2,
        )

        redis.publish.assert_awaited_once()
        topic, _payload = redis.publish.await_args.args
        assert topic == user_topic(added_user_id)

    async def test_member_removed_publishes_to_the_removed_users_own_topic(self) -> None:
        removed_user_id = uuid4()
        redis = AsyncMock()

        await publish_member_removed(redis, channel_id=uuid4(), user_id=removed_user_id)

        topic, _payload = redis.publish.await_args.args
        assert topic == user_topic(removed_user_id)

    async def test_never_publishes_to_a_channel_or_dm_topic(self) -> None:
        """Privacy: membership events never ride the shared channel topic —
        only the affected user's own per-user topic.
        """

        channel = _channel()
        redis = AsyncMock()

        await publish_member_added(
            redis,
            channel,
            user_id=uuid4(),
            role=ChannelMemberRole.MEMBER,
            joined_at=datetime.now(UTC),
            member_count=1,
        )

        topic, _payload = redis.publish.await_args.args
        assert not topic.startswith("chan:")
        assert not topic.startswith("dm:")


class TestPublishFailsOpen:
    """A Redis error must never propagate out of a publish call (ADR-0004)."""

    async def test_redis_error_is_swallowed_not_raised(self) -> None:
        redis = AsyncMock()
        redis.publish.side_effect = RedisError("boom")

        # Must not raise.
        await publish_member_added(
            redis,
            _channel(),
            user_id=uuid4(),
            role=ChannelMemberRole.MEMBER,
            joined_at=datetime.now(UTC),
            member_count=1,
        )
        await publish_member_removed(redis, channel_id=uuid4(), user_id=uuid4())

    async def test_transport_timeout_is_also_swallowed(self) -> None:
        redis = AsyncMock()
        redis.publish.side_effect = TimeoutError("timed out")

        await publish_member_removed(redis, channel_id=uuid4(), user_id=uuid4())

    async def test_a_non_redis_bug_still_propagates(self) -> None:
        redis = AsyncMock()
        not_serializable = {"type": "channel.member_added", "data": {"bad": {1, 2, 3}}}

        with pytest.raises(TypeError):
            await publish_channel_event(redis, not_serializable, topic="user:x")

        redis.publish.assert_not_awaited()
