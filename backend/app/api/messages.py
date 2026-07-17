"""`/v1/channels/{id}/messages` + `/v1/messages/{id}` + `/v1/dms/{user_id}/messages`
— T21/T22, frozen contract.

Persist-then-publish (T24): send/edit/delete each pass the process-wide
`get_redis_client()` client through to their `app.services.messages`
call, which publishes the corresponding `message.created`/`edited`/
`deleted` Redis pub/sub fan-out event strictly after its own commit
returns (see that module's docstring for the exact rules — e.g. an
idempotent replay or a no-op edit/delete never re-publishes). Six
endpoints:

- `POST /v1/channels/{channel_id}/messages`: send a channel message.
  Required `Idempotency-Key` header (client UUID); missing/malformed is
  `400` (F40). Server-side membership check (F34) reuses
  `app.services.channels.get_membership` via
  `app.services.messages.ensure_channel_and_membership`. `201` on first
  create, `200` (same row) on replay. `503` (with `Retry-After`) in the
  rare case a concurrent request holding the same `Idempotency-Key`'s
  claim never resolves within the bounded retry window — the fail-closed
  outcome that replaces inserting a duplicate row, see
  `app.services.messages.IdempotencyResolutionTimeoutError`. This is an
  additive response not yet reflected in the frozen contract's status
  table — flagged for `api-reviewer` sign-off.
- `GET /v1/channels/{channel_id}/messages`: cursor-paginated history,
  soft-deleted excluded, reusing `app.core.pagination` (T07).
- `PATCH /v1/messages/{message_id}`: author-only edit; `409` if already
  deleted.
- `DELETE /v1/messages/{message_id}`: author-only soft delete; `204`,
  idempotent on repeat.
- `POST /v1/dms/{user_id}/messages` (T22): send a 1:1 DM to `user_id` (the
  recipient). Same required `Idempotency-Key`/`400` and `503` fail-closed
  shape as the channel send, reusing `app.services.messages
  ._claim_and_persist_message` (T21's shared send/idempotency helper).
  Self-DM (`user_id` == caller) is `422`, not `404`; a missing or inactive
  recipient is `404`.
- `GET /v1/dms/{user_id}/messages` (T22): cursor-paginated DM history with
  `user_id`, keyed on the canonical `least(sender_id,
  recipient_id)`/`greatest(...)` user pair (`ix_messages_dm_history`).
  Self-conversation (`user_id` == caller) is `422`; a nonexistent other
  participant is `404` (uniform, no `is_active` distinction on this path).

Every body is parsed via `app.core.request_body.parse_body` (not a typed
FastAPI body parameter), matching `app.api.channels`'s existing
malformed-body-vs-invalid-value split (`400` vs `422`).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import HEADER_NAME
from app.core.deps import AuthenticatedUser, require_auth
from app.core.errors import PROBLEM_CONTENT_TYPE, build_problem_body
from app.core.metrics import increment_counter
from app.core.pagination import CursorKey, PaginationError, decode_cursor, resolve_limit
from app.core.rate_limit_deps import enforce_message_send_rate_limit
from app.core.request_body import openapi_request_body, parse_body
from app.db.redis import get_redis_client
from app.db.session import get_db_session
from app.schemas.messages import (
    MessageEditRequest,
    MessageHistoryResponse,
    MessageObject,
    MessageSendRequest,
)
from app.services.messages import (
    ChannelNotFoundError,
    IdempotencyResolutionTimeoutError,
    InvalidContentError,
    InvalidMediaError,
    MessageAlreadyDeletedError,
    MessageNotFoundError,
    NotChannelMemberError,
    NotMessageAuthorError,
    RecipientNotFoundError,
    SelfDMError,
    delete_message,
    edit_message,
    ensure_channel_and_membership,
    ensure_dm_history_access,
    get_channel_message_history,
    get_dm_message_history,
    get_media_for_messages,
    get_message_media,
    send_channel_message,
    send_dm_message,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["messages"])

_CHANNEL_NOT_FOUND_DETAIL = "No such channel."
_NOT_MEMBER_DETAIL = "You are not a member of this channel."
_INVALID_CONTENT_DETAIL = "content must be 1-4000 non-whitespace characters."
_INVALID_MEDIA_DETAIL = "One or more media_ids are unusable by this sender."
_MESSAGE_NOT_FOUND_DETAIL = "No such message."
_NOT_AUTHOR_DETAIL = "Only the message's author may perform this action."
_ALREADY_DELETED_DETAIL = "This message has already been deleted."
_MISSING_IDEMPOTENCY_KEY_DETAIL = "Idempotency-Key header must be a valid UUID."
_INVALID_LIMIT_DETAIL = "limit must be a positive integer."
_IDEMPOTENCY_TIMEOUT_DETAIL = (
    "Could not confirm this send in time; retry with the same Idempotency-Key."
)
# Short, fixed hint — well above `_RESOLVE_MAX_ATTEMPTS * _RESOLVE_BACKOFF_SECONDS`
# (the resolve loop's own worst-case duration) so an immediate client retry is
# very likely to land on an already-settled claim rather than repeating the
# same timeout.
_IDEMPOTENCY_TIMEOUT_RETRY_AFTER_SECONDS = "1"
_SELF_DM_SEND_DETAIL = "You cannot send a DM to yourself."
_SELF_DM_HISTORY_DETAIL = "user_id must not be your own id; there is no self-conversation."
_RECIPIENT_NOT_FOUND_DETAIL = "Recipient does not exist or is inactive."
_DM_PARTICIPANT_NOT_FOUND_DETAIL = "No such user."

_CurrentUser = Annotated[AuthenticatedUser, Depends(require_auth)]
_DbSession = Annotated[AsyncSession, Depends(get_db_session)]
_Payload = Annotated[dict[str, Any], Body(...)]


def _parse_idempotency_key(raw: str | None) -> str:
    """Validate the `Idempotency-Key` header, raising the frozen `400` on failure.

    Per the contract: "A malformed/absent key on message-create is
    rejected with 400." The key itself is a client-generated UUID; the
    canonical string form (`str(UUID(raw))`) is what gets used as the
    Redis claim's identity, so two textually-different-but-equal UUID
    spellings (e.g. differing case) collide on the same claim.
    """

    if raw is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=_MISSING_IDEMPOTENCY_KEY_DETAIL
        )
    try:
        return str(UUID(raw))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=_MISSING_IDEMPOTENCY_KEY_DETAIL
        ) from None


def _parse_limit(raw: str | None) -> int:
    if raw is None:
        return resolve_limit(None)
    try:
        raw_limit = int(raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=_INVALID_LIMIT_DETAIL
        ) from None
    try:
        return resolve_limit(raw_limit)
    except PaginationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.detail) from exc


def _parse_cursor(raw: str | None) -> CursorKey | None:
    if raw is None:
        return None
    try:
        return decode_cursor(raw)
    except PaginationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.detail) from exc


def _idempotency_timeout_response(*, instance: str) -> JSONResponse:
    """Shared `503` + `Retry-After` problem+json builder for the fail-closed
    `IdempotencyResolutionTimeoutError` path — identical for channel send
    and DM send (T22 reuses T21's shape verbatim, only `instance` differs).
    """

    problem_body = build_problem_body(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=_IDEMPOTENCY_TIMEOUT_DETAIL,
        instance=instance,
    )
    problem_response = JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=problem_body,
        media_type=PROBLEM_CONTENT_TYPE,
        headers={"Retry-After": _IDEMPOTENCY_TIMEOUT_RETRY_AFTER_SECONDS},
    )
    problem_response.headers[HEADER_NAME] = problem_body["correlation_id"]
    return problem_response


@router.post(
    "/channels/{channel_id}/messages",
    response_model=MessageObject,
    openapi_extra=openapi_request_body(
        MessageSendRequest, {"content": "shipping the release now", "media_ids": []}
    ),
)
async def send_channel_message_route(
    channel_id: UUID,
    payload: _Payload,
    current: _CurrentUser,
    db: _DbSession,
    _rate_limit_guard: Annotated[None, Depends(enforce_message_send_rate_limit)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Any:
    key = _parse_idempotency_key(idempotency_key)
    body = parse_body(MessageSendRequest, payload)

    redis = get_redis_client()

    try:
        result = await send_channel_message(
            db,
            redis,
            channel_id=channel_id,
            sender_id=current.user_id,
            content=body.content,
            media_ids=body.media_ids,
            idempotency_key=key,
        )
    except ChannelNotFoundError:
        increment_counter(
            "message_send_error_total", conversation_kind="channel", error_type="channel_not_found"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_CHANNEL_NOT_FOUND_DETAIL
        ) from None
    except NotChannelMemberError:
        increment_counter(
            "message_send_error_total", conversation_kind="channel", error_type="not_member"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_NOT_MEMBER_DETAIL
        ) from None
    except InvalidContentError:
        increment_counter(
            "message_send_error_total", conversation_kind="channel", error_type="invalid_content"
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=_INVALID_CONTENT_DETAIL
        ) from None
    except InvalidMediaError:
        increment_counter(
            "message_send_error_total", conversation_kind="channel", error_type="invalid_media"
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=_INVALID_MEDIA_DETAIL
        ) from None
    except IdempotencyResolutionTimeoutError:
        # Fail-closed per F40 (see `app.services.messages` module docstring):
        # a concurrent claim on this Idempotency-Key never resolved to a
        # visible row within the bounded retry window. Never insert a
        # duplicate here — surface a transient 503 with `Retry-After`
        # instead, matching the problem+json envelope every other error on
        # this surface uses (built directly rather than via `HTTPException`,
        # which does not carry custom response headers through
        # `app.core.errors.http_exception_handler`).
        increment_counter(
            "message_send_error_total",
            conversation_kind="channel",
            error_type="idempotency_timeout",
        )
        logger.warning(
            "idempotency claim resolution timed out",
            extra={"channel_id": str(channel_id), "sender_id": str(current.user_id)},
        )
        return _idempotency_timeout_response(instance=f"/v1/channels/{channel_id}/messages")

    # Key metric (technical spec §9): "message send throughput and error rate".
    # `replay=true` marks an idempotent replay (no new row written) so a
    # client retry storm cannot silently inflate the real send-throughput
    # signal (code review finding 2) -- callers computing throughput should
    # filter/aggregate on `replay=false` only.
    increment_counter(
        "message_send_success_total",
        conversation_kind="channel",
        replay=str(not result.created).lower(),
    )
    logger.info(
        "channel message sent",
        extra={
            "channel_id": str(channel_id),
            "message_id": str(result.message.id),
            "sender_id": str(current.user_id),
            "idempotent_replay": not result.created,
        },
    )

    response_body = MessageObject.from_message(result.message, media=result.media)
    status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    return JSONResponse(status_code=status_code, content=response_body.model_dump(mode="json"))


@router.get(
    "/channels/{channel_id}/messages",
    response_model=MessageHistoryResponse,
    status_code=status.HTTP_200_OK,
)
async def get_channel_message_history_route(
    channel_id: UUID,
    current: _CurrentUser,
    db: _DbSession,
    limit: Annotated[str | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
) -> MessageHistoryResponse:
    resolved_limit = _parse_limit(limit)
    resolved_cursor = _parse_cursor(cursor)

    try:
        await ensure_channel_and_membership(db, channel_id=channel_id, user_id=current.user_id)
    except ChannelNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_CHANNEL_NOT_FOUND_DETAIL
        ) from None
    except NotChannelMemberError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_NOT_MEMBER_DETAIL
        ) from None

    page = await get_channel_message_history(
        db,
        channel_id=channel_id,
        caller_id=current.user_id,
        limit=resolved_limit,
        cursor=resolved_cursor,
    )

    media_by_message = await get_media_for_messages(db, [m.id for m in page.items])
    items = [
        MessageObject.from_message(message, media=media_by_message.get(message.id, []))
        for message in page.items
    ]

    return MessageHistoryResponse(items=items, next_cursor=page.next_cursor)


@router.patch(
    "/messages/{message_id}",
    response_model=MessageObject,
    status_code=status.HTTP_200_OK,
    openapi_extra=openapi_request_body(
        MessageEditRequest, {"content": "shipping the release now (edited)"}
    ),
)
async def edit_message_route(
    message_id: UUID, payload: _Payload, current: _CurrentUser, db: _DbSession
) -> MessageObject:
    body = parse_body(MessageEditRequest, payload)
    redis = get_redis_client()

    try:
        message = await edit_message(
            db, redis, message_id=message_id, caller_id=current.user_id, content=body.content
        )
    except MessageNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_MESSAGE_NOT_FOUND_DETAIL
        ) from None
    except NotMessageAuthorError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_NOT_AUTHOR_DETAIL
        ) from None
    except MessageAlreadyDeletedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_ALREADY_DELETED_DETAIL
        ) from None
    except InvalidContentError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=_INVALID_CONTENT_DETAIL
        ) from None

    logger.info(
        "message edited",
        extra={"message_id": str(message_id), "sender_id": str(current.user_id)},
    )

    media = await get_message_media(db, message_id)
    return MessageObject.from_message(message, media=media)


@router.delete(
    "/messages/{message_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_message_route(message_id: UUID, current: _CurrentUser, db: _DbSession) -> None:
    redis = get_redis_client()
    try:
        await delete_message(db, redis, message_id=message_id, caller_id=current.user_id)
    except MessageNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_MESSAGE_NOT_FOUND_DETAIL
        ) from None
    except NotMessageAuthorError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_NOT_AUTHOR_DETAIL
        ) from None

    logger.info(
        "message deleted",
        extra={"message_id": str(message_id), "sender_id": str(current.user_id)},
    )


@router.post(
    "/dms/{user_id}/messages",
    response_model=MessageObject,
    openapi_extra=openapi_request_body(
        MessageSendRequest, {"content": "hey, got a minute?", "media_ids": []}
    ),
)
async def send_dm_message_route(
    user_id: UUID,
    payload: _Payload,
    current: _CurrentUser,
    db: _DbSession,
    _rate_limit_guard: Annotated[None, Depends(enforce_message_send_rate_limit)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Any:
    """`POST /v1/dms/{user_id}/messages` (T22) — `user_id` is the recipient.

    Reuses T21's `Idempotency-Key` parsing/claim-and-persist helper
    verbatim (`app.services.messages._claim_and_persist_message` via
    `send_dm_message`); only the business-rule gates (self-DM,
    recipient existence/active-state) and the resulting row shape
    (`recipient_id` set, `channel_id` NULL) differ from the channel send.
    """

    key = _parse_idempotency_key(idempotency_key)
    body = parse_body(MessageSendRequest, payload)

    redis = get_redis_client()

    try:
        result = await send_dm_message(
            db,
            redis,
            recipient_id=user_id,
            sender_id=current.user_id,
            content=body.content,
            media_ids=body.media_ids,
            idempotency_key=key,
        )
    except SelfDMError:
        increment_counter("message_send_error_total", conversation_kind="dm", error_type="self_dm")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=_SELF_DM_SEND_DETAIL
        ) from None
    except RecipientNotFoundError:
        increment_counter(
            "message_send_error_total", conversation_kind="dm", error_type="recipient_not_found"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_RECIPIENT_NOT_FOUND_DETAIL
        ) from None
    except InvalidContentError:
        increment_counter(
            "message_send_error_total", conversation_kind="dm", error_type="invalid_content"
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=_INVALID_CONTENT_DETAIL
        ) from None
    except InvalidMediaError:
        increment_counter(
            "message_send_error_total", conversation_kind="dm", error_type="invalid_media"
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=_INVALID_MEDIA_DETAIL
        ) from None
    except IdempotencyResolutionTimeoutError:
        # Fail-closed per F40 (see `app.services.messages` module docstring)
        # — identical rationale/shape to the channel-send `503` above.
        increment_counter(
            "message_send_error_total", conversation_kind="dm", error_type="idempotency_timeout"
        )
        logger.warning(
            "dm idempotency claim resolution timed out",
            extra={"recipient_id": str(user_id), "sender_id": str(current.user_id)},
        )
        return _idempotency_timeout_response(instance=f"/v1/dms/{user_id}/messages")

    # Key metric (technical spec §9): "message send throughput and error rate".
    # `replay=true` marks an idempotent replay (no new row written) --
    # matches the channel-send counter's labeling (code review finding 2).
    increment_counter(
        "message_send_success_total",
        conversation_kind="dm",
        replay=str(not result.created).lower(),
    )
    logger.info(
        "dm sent",
        extra={
            "recipient_id": str(user_id),
            "message_id": str(result.message.id),
            "sender_id": str(current.user_id),
            "idempotent_replay": not result.created,
        },
    )

    response_body = MessageObject.from_message(result.message, media=result.media)
    status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    return JSONResponse(status_code=status_code, content=response_body.model_dump(mode="json"))


@router.get(
    "/dms/{user_id}/messages",
    response_model=MessageHistoryResponse,
    status_code=status.HTTP_200_OK,
)
async def get_dm_message_history_route(
    user_id: UUID,
    current: _CurrentUser,
    db: _DbSession,
    limit: Annotated[str | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
) -> MessageHistoryResponse:
    """`GET /v1/dms/{user_id}/messages` (T22) — cursor-paginated 1:1 DM history.

    Keyed on the canonical unordered `(sender_id, recipient_id)` pair
    (ADR-0002) via `app.services.messages.get_dm_message_history`, which
    hits the shipped functional+partial `ix_messages_dm_history` index.
    The caller is always one of the two participants by construction (JWT
    subject + path `user_id`); `ensure_dm_history_access` only needs to
    reject a self-conversation (`422`) and confirm the other participant
    exists (`404`, uniform).
    """

    resolved_limit = _parse_limit(limit)
    resolved_cursor = _parse_cursor(cursor)

    try:
        await ensure_dm_history_access(db, other_user_id=user_id, caller_id=current.user_id)
    except SelfDMError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=_SELF_DM_HISTORY_DETAIL
        ) from None
    except RecipientNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_DM_PARTICIPANT_NOT_FOUND_DETAIL
        ) from None

    page = await get_dm_message_history(
        db,
        caller_id=current.user_id,
        other_user_id=user_id,
        limit=resolved_limit,
        cursor=resolved_cursor,
    )

    media_by_message = await get_media_for_messages(db, [m.id for m in page.items])
    items = [
        MessageObject.from_message(message, media=media_by_message.get(message.id, []))
        for message in page.items
    ]

    return MessageHistoryResponse(items=items, next_cursor=page.next_cursor)
