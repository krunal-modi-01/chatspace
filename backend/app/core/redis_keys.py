"""Namespaced Redis key/topic builders for the four Redis roles.

chatspace uses a single shared Redis instance for four distinct
responsibilities (technical spec §Architecture, CLAUDE.md ARCHITECTURE
NOTES). Every key a consumer touches must go through one of these
builders so the roles never collide in the shared keyspace and so the
canonical shapes below are produced from exactly one place:

1. **Pub/sub fan-out** (ADR-0004) — `chan:{channel_id}` / `dm:{a}:{b}`.
2. **Presence** (F49-F50) — per-user ref-count + last-seen-adjacent state.
3. **Rate-limit token buckets** (F62-F64) — per-subject, per-scope buckets.
4. **Session-revocation cache** (ADR-0006) — per-`sid` revocation state.

This module builds key/topic *strings* only — it does not read or write
Redis. The consumers that own each role (pub/sub relay, presence
service, rate limiter, revocation-cache populator) are out of scope for
T05 and are built on top of `app.db.redis.get_redis_client()` plus these
helpers.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

# --- 1. Pub/sub fan-out (ADR-0004) ------------------------------------------


def channel_topic(channel_id: UUID | str) -> str:
    """Return the pub/sub topic for a channel conversation.

    Canonical shape: `chan:{channel_id}` (ADR-0004, spec line 626/674).
    """

    return f"chan:{channel_id}"


def dm_topic(user_a_id: UUID | str, user_b_id: UUID | str) -> str:
    """Return the canonical pub/sub topic for a DM conversation.

    Canonical shape: `dm:{least}:{greatest}`, where `least`/`greatest` are
    the two participant ids ordered so a DM maps to exactly **one** topic
    regardless of who is sender vs. recipient (ADR-0002's canonical
    user-pair rule; ADR-0004 line 626; must mirror the DB design's
    `ix_messages_dm_history` `least(sender_id, recipient_id)` /
    `greatest(...)` expression so the app-level topic and the durable
    history index agree on DM identity).
    """

    first, second = str(user_a_id), str(user_b_id)
    least, greatest = (first, second) if first <= second else (second, first)
    return f"dm:{least}:{greatest}"


# --- 2. Presence (F49-F50) --------------------------------------------------


def presence_connection_count_key(user_id: UUID | str) -> str:
    """Redis key holding a user's live WebSocket connection ref-count.

    A user is `online` while this count is >= 1 (spec line 627); the
    presence service increments/decrements it per connect/disconnect and
    persists durable `last_seen` to Postgres only on the last disconnect.
    """

    return f"presence:conn_count:{user_id}"


def presence_state_key(user_id: UUID | str) -> str:
    """Redis key holding a user's cached presence state (e.g. online/offline)."""

    return f"presence:state:{user_id}"


def typing_indicator_key(conversation_topic: str) -> str:
    """Redis key namespacing typing-indicator state for a conversation.

    `conversation_topic` is the value returned by `channel_topic()` or
    `dm_topic()`, so typing state is namespaced identically to the pub/sub
    topic it rides alongside (F49-F50).
    """

    return f"presence:typing:{conversation_topic}"


# --- 3. Rate-limit token buckets (F62-F64) ----------------------------------


class RateLimitScope(StrEnum):
    """The three rate-limited operation classes (spec line 39, F62-F64)."""

    MESSAGE_SEND = "message_send"
    AUTH = "auth"
    MEDIA_UPLOAD = "media_upload"


def rate_limit_bucket_key(scope: RateLimitScope, subject: str) -> str:
    """Redis key for a token-bucket rate limiter.

    `subject` is the caller-supplied identity the bucket is keyed on per
    scope: a user id for `MESSAGE_SEND` (10/10s, burst 20) and
    `MEDIA_UPLOAD` (20/min); a composite `"{ip}:{identifier}"` string for
    `AUTH` (5/5min per IP + attempted identifier, non-enumerating). This
    helper does not construct that composite — callers pass whatever
    subject string their scope's policy defines.
    """

    return f"ratelimit:{scope.value}:{subject}"


# --- 4. Session-revocation cache (ADR-0006) ---------------------------------


def session_revocation_key(session_id: UUID | str) -> str:
    """Redis key caching a session's (`sid`) revocation/active state.

    O(1) hot-path cache in front of the durable Postgres `sessions` table
    (`revoked_at`, `uq_sessions_refresh_hash`, `ix_sessions_user_active`).
    Every authenticated REST request and WS heartbeat revalidation looks
    this up before falling back to Postgres (ADR-0006).
    """

    return f"session:revocation:{session_id}"
