from __future__ import annotations

from uuid import uuid4

from app.core.redis_keys import (
    RateLimitScope,
    channel_topic,
    dm_topic,
    presence_connection_count_key,
    presence_state_key,
    rate_limit_bucket_key,
    session_revocation_key,
    typing_indicator_key,
)


class TestChannelTopic:
    def test_produces_canonical_chan_prefix(self) -> None:
        channel_id = uuid4()

        assert channel_topic(channel_id) == f"chan:{channel_id}"

    def test_accepts_plain_string_id(self) -> None:
        assert channel_topic("abc-123") == "chan:abc-123"


class TestDmTopic:
    """The DM key-builder must produce the canonical `dm:{least}:{greatest}` topic."""

    def test_orders_ids_ascending_regardless_of_argument_order(self) -> None:
        user_a = uuid4()
        user_b = uuid4()
        least, greatest = sorted((str(user_a), str(user_b)))

        assert dm_topic(user_a, user_b) == f"dm:{least}:{greatest}"
        assert dm_topic(user_b, user_a) == f"dm:{least}:{greatest}"

    def test_sender_order_does_not_change_the_topic(self) -> None:
        """A DM must map to exactly one topic regardless of sender/recipient order.

        Directly exercises ADR-0002's canonical user-pair rule, mirrored by
        the DB design's `least(sender_id, recipient_id)` / `greatest(...)`
        index expression.
        """

        user_1 = "11111111-1111-1111-1111-111111111111"
        user_2 = "22222222-2222-2222-2222-222222222222"

        topic_when_1_sends = dm_topic(user_1, user_2)
        topic_when_2_sends = dm_topic(user_2, user_1)

        assert topic_when_1_sends == topic_when_2_sends
        assert topic_when_1_sends == f"dm:{user_1}:{user_2}"

    def test_exact_canonical_shape_with_known_uuids(self) -> None:
        least = "00000000-0000-0000-0000-000000000001"
        greatest = "00000000-0000-0000-0000-000000000002"

        assert dm_topic(greatest, least) == f"dm:{least}:{greatest}"

    def test_identical_ids_produce_a_single_repeated_pair(self) -> None:
        user_id = uuid4()

        assert dm_topic(user_id, user_id) == f"dm:{user_id}:{user_id}"


class TestPresenceKeys:
    def test_connection_count_key_is_namespaced_per_user(self) -> None:
        user_id = uuid4()

        assert presence_connection_count_key(user_id) == f"presence:conn_count:{user_id}"

    def test_state_key_is_namespaced_per_user(self) -> None:
        user_id = uuid4()

        assert presence_state_key(user_id) == f"presence:state:{user_id}"

    def test_typing_indicator_key_wraps_the_conversation_topic(self) -> None:
        topic = channel_topic(uuid4())

        assert typing_indicator_key(topic) == f"presence:typing:{topic}"

    def test_typing_indicator_key_distinguishes_channel_and_dm_topics(self) -> None:
        channel_id = uuid4()
        user_a, user_b = uuid4(), uuid4()

        channel_key = typing_indicator_key(channel_topic(channel_id))
        dm_key = typing_indicator_key(dm_topic(user_a, user_b))

        assert channel_key != dm_key


class TestRateLimitBucketKey:
    def test_message_send_bucket_is_namespaced_per_user(self) -> None:
        user_id = str(uuid4())

        key = rate_limit_bucket_key(RateLimitScope.MESSAGE_SEND, user_id)

        assert key == f"ratelimit:message_send:{user_id}"

    def test_auth_bucket_accepts_a_composite_subject(self) -> None:
        subject = "203.0.113.7:someone@example.com"

        key = rate_limit_bucket_key(RateLimitScope.AUTH, subject)

        assert key == f"ratelimit:auth:{subject}"

    def test_media_upload_bucket_is_namespaced_per_user(self) -> None:
        user_id = str(uuid4())

        key = rate_limit_bucket_key(RateLimitScope.MEDIA_UPLOAD, user_id)

        assert key == f"ratelimit:media_upload:{user_id}"

    def test_scopes_never_collide_for_the_same_subject(self) -> None:
        subject = str(uuid4())

        keys = {rate_limit_bucket_key(scope, subject) for scope in RateLimitScope}

        assert len(keys) == len(RateLimitScope)


class TestSessionRevocationKey:
    def test_is_namespaced_per_session_id(self) -> None:
        session_id = uuid4()

        assert session_revocation_key(session_id) == f"session:revocation:{session_id}"

    def test_never_embeds_a_raw_refresh_token(self) -> None:
        """The revocation cache key is keyed on `sid`, never on token material."""

        session_id = uuid4()

        key = session_revocation_key(session_id)

        assert "refresh" not in key
        assert "token" not in key


class TestCrossRoleNamespaceIsolation:
    """Keys for the four roles must never collide in the shared keyspace."""

    def test_same_id_used_across_roles_produces_distinct_keys(self) -> None:
        shared_id = uuid4()

        keys = {
            channel_topic(shared_id),
            presence_connection_count_key(shared_id),
            presence_state_key(shared_id),
            rate_limit_bucket_key(RateLimitScope.MESSAGE_SEND, str(shared_id)),
            session_revocation_key(shared_id),
        }

        assert len(keys) == 5
