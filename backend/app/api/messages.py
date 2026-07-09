"""`/v1/channels/{id}/messages` + `/v1/messages/{id}` — T21, frozen contract.

Persist-only (T21 scope): none of these routes publish a WS event or
Redis pub/sub message — `message.created`/`edited`/`deleted` fan-out is
T24's job. Four endpoints:

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
from app.core.pagination import CursorKey, PaginationError, decode_cursor, resolve_limit
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
    delete_message,
    edit_message,
    ensure_channel_and_membership,
    get_channel_message_history,
    get_media_for_messages,
    get_message_media,
    send_channel_message,
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_CHANNEL_NOT_FOUND_DETAIL
        ) from None
    except NotChannelMemberError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_NOT_MEMBER_DETAIL
        ) from None
    except InvalidContentError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=_INVALID_CONTENT_DETAIL
        ) from None
    except InvalidMediaError:
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
        logger.warning(
            "idempotency claim resolution timed out",
            extra={"channel_id": str(channel_id), "sender_id": str(current.user_id)},
        )
        problem_body = build_problem_body(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_IDEMPOTENCY_TIMEOUT_DETAIL,
            instance=f"/v1/channels/{channel_id}/messages",
        )
        problem_response = JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=problem_body,
            media_type=PROBLEM_CONTENT_TYPE,
            headers={"Retry-After": _IDEMPOTENCY_TIMEOUT_RETRY_AFTER_SECONDS},
        )
        problem_response.headers[HEADER_NAME] = problem_body["correlation_id"]
        return problem_response

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

    try:
        message = await edit_message(
            db, message_id=message_id, caller_id=current.user_id, content=body.content
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
    try:
        await delete_message(db, message_id=message_id, caller_id=current.user_id)
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
