"""Per-frame `join`/`leave` conversation authorization (T23, F34).

The single re-check every `join` frame must run before subscribing a
connection to a topic — never trust a client-supplied `channel_id`/
`user_id` alone (CLAUDE.md security requirements). Reuses
`app.services.channels.get_membership`, the same primitive REST channel
routes use, so WS and REST membership checks never drift.

DM "participation" at the WS layer is narrower than the T22 REST
authorization (which also checks the *caller* is a participant of an
*existing* conversation): a DM has no `channels` row and no
prerequisite history, so the only thing to validate here is that the
requested peer is a distinct, existing, active user — the same
recipient-validity rule T22's `POST /v1/dms/{user_id}/messages` applies.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_keys import channel_topic, dm_topic
from app.models.user import User
from app.services.channels import get_membership
from app.ws.frames import ChannelConversation, Conversation, DMConversation


@dataclass(frozen=True, slots=True)
class ConversationAuthResult:
    authorized: bool
    topic: str | None
    error_code: str | None
    error_detail: str | None


async def authorize_conversation(
    db: AsyncSession, *, conversation: Conversation, caller_id: UUID
) -> ConversationAuthResult:
    """Re-check the caller's right to join/leave/type in `conversation`.

    Returns the canonical pub/sub topic string (`app.core.redis_keys`) on
    success, or a non-fatal `(error_code, error_detail)` pair on failure —
    callers turn the latter into an `error` frame without closing the
    socket.
    """

    if isinstance(conversation, ChannelConversation):
        membership = await get_membership(db, channel_id=conversation.channel_id, user_id=caller_id)
        if membership is None:
            return ConversationAuthResult(
                authorized=False,
                topic=None,
                error_code="unauthorized_join",
                error_detail="Not a member of this channel.",
            )
        return ConversationAuthResult(
            authorized=True,
            topic=channel_topic(conversation.channel_id),
            error_code=None,
            error_detail=None,
        )

    if isinstance(conversation, DMConversation):
        return await _authorize_dm(db, conversation=conversation, caller_id=caller_id)

    # Unreachable given the discriminated-union type, but keeps this
    # function total rather than silently falling through.
    return ConversationAuthResult(
        authorized=False,
        topic=None,
        error_code="invalid_conversation",
        error_detail="Unknown conversation kind.",
    )


async def _authorize_dm(
    db: AsyncSession, *, conversation: DMConversation, caller_id: UUID
) -> ConversationAuthResult:
    if conversation.user_id == caller_id:
        return ConversationAuthResult(
            authorized=False,
            topic=None,
            error_code="invalid_conversation",
            error_detail="Cannot open a DM conversation with yourself.",
        )

    peer = await db.get(User, conversation.user_id)
    if peer is None or not peer.is_active:
        return ConversationAuthResult(
            authorized=False,
            topic=None,
            error_code="unauthorized_join",
            error_detail="DM recipient does not exist or is inactive.",
        )

    return ConversationAuthResult(
        authorized=True,
        topic=dm_topic(caller_id, conversation.user_id),
        error_code=None,
        error_detail=None,
    )
