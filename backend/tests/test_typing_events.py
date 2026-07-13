"""Unit tests for `app.ws.typing_events` (T26 envelope + publish).

Pure envelope-shape assertions plus a mocked-Redis publish-path test
(fail-open on `RedisError`) — mirrors `tests/test_message_events.py`'s
structure for T24. Real-Redis cross-connection relay + self-exclusion is
covered by `tests/test_ws_fanout.py` and `tests/test_ws_connection_manager.py`.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from redis.exceptions import RedisError

from app.core.redis_keys import channel_topic, dm_topic
from app.ws.frames import ChannelConversation, DMConversation
from app.ws.typing_events import build_typing_event, publish_typing_event


class TestBuildTypingEvent:
    def test_matches_the_frozen_channel_envelope_shape(self) -> None:
        user_id = uuid4()
        channel_id = uuid4()
        conversation = ChannelConversation(kind="channel", channel_id=channel_id)

        event = build_typing_event(user_id=user_id, conversation=conversation)

        assert event["type"] == "typing"
        assert event["conversation"] == {"kind": "channel", "channel_id": str(channel_id)}
        assert event["data"] == {
            "user_id": str(user_id),
            "conversation": {"kind": "channel", "channel_id": str(channel_id)},
        }

    def test_matches_the_frozen_dm_envelope_shape(self) -> None:
        user_id = uuid4()
        peer_id = uuid4()
        conversation = DMConversation(kind="dm", user_id=peer_id)

        event = build_typing_event(user_id=user_id, conversation=conversation)

        assert event["type"] == "typing"
        assert event["conversation"] == {"kind": "dm", "user_id": str(peer_id)}
        assert event["data"]["user_id"] == str(user_id)
        assert event["data"]["conversation"] == {"kind": "dm", "user_id": str(peer_id)}

    def test_data_user_id_is_the_typer_not_the_dm_peer(self) -> None:
        """`data.user_id` must identify who is typing (F56) — distinct from
        the DM `conversation.user_id`, which identifies the other party
        of the conversation, not the typer.
        """

        typer_id = uuid4()
        peer_id = uuid4()
        conversation = DMConversation(kind="dm", user_id=peer_id)

        event = build_typing_event(user_id=typer_id, conversation=conversation)

        assert event["data"]["user_id"] == str(typer_id)
        assert event["data"]["user_id"] != str(peer_id)

    def test_is_json_serializable(self) -> None:
        event = build_typing_event(
            user_id=uuid4(), conversation=ChannelConversation(kind="channel", channel_id=uuid4())
        )

        json.loads(json.dumps(event))

    def test_no_stop_semantics_present_in_the_envelope(self) -> None:
        """The frozen contract has no `typing.stop`/explicit-stop frame —
        the envelope must never grow a `stop`-shaped field.
        """

        event = build_typing_event(
            user_id=uuid4(), conversation=ChannelConversation(kind="channel", channel_id=uuid4())
        )

        assert set(event.keys()) == {"type", "conversation", "data"}
        assert set(event["data"].keys()) == {"user_id", "conversation"}


class TestPublishTypingEvent:
    async def test_publishes_the_exact_event_to_the_given_topic(self) -> None:
        redis = AsyncMock()
        event = build_typing_event(
            user_id=uuid4(), conversation=ChannelConversation(kind="channel", channel_id=uuid4())
        )
        topic = channel_topic(uuid4())

        await publish_typing_event(redis, event, topic=topic)

        redis.publish.assert_awaited_once()
        published_topic, published_payload = redis.publish.await_args.args
        assert published_topic == topic
        assert json.loads(published_payload) == event

    async def test_dm_topic_is_canonical_regardless_of_direction(self) -> None:
        redis = AsyncMock()
        user_a, user_b = uuid4(), uuid4()
        event = build_typing_event(
            user_id=user_a, conversation=DMConversation(kind="dm", user_id=user_b)
        )

        await publish_typing_event(redis, event, topic=dm_topic(user_a, user_b))

        topic, _payload = redis.publish.await_args.args
        assert topic == dm_topic(user_a, user_b)
        assert topic == dm_topic(user_b, user_a)


class TestPublishFailsOpen:
    """A Redis error must never propagate out of a publish call — there is
    no durable history to recover a missed typing indicator from, so a
    failed publish is simply accepted as a missed live update.
    """

    async def test_redis_error_is_swallowed_not_raised(self) -> None:
        redis = AsyncMock()
        redis.publish.side_effect = RedisError("boom")
        event = build_typing_event(
            user_id=uuid4(), conversation=ChannelConversation(kind="channel", channel_id=uuid4())
        )

        await publish_typing_event(redis, event, topic="chan:x")

    async def test_transport_timeout_is_also_swallowed(self) -> None:
        redis = AsyncMock()
        redis.publish.side_effect = TimeoutError("timed out")
        event = build_typing_event(
            user_id=uuid4(), conversation=ChannelConversation(kind="channel", channel_id=uuid4())
        )

        await publish_typing_event(redis, event, topic="chan:x")

    async def test_a_non_redis_bug_still_propagates(self) -> None:
        redis = AsyncMock()
        not_serializable = {"type": "typing", "data": {"bad": {1, 2, 3}}}

        with pytest.raises(TypeError):
            await publish_typing_event(redis, not_serializable, topic="chan:x")

        redis.publish.assert_not_awaited()
