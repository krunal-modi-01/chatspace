"""`/v1/channels*` — channel create/get/public browse (T18, frozen contract).

Three endpoints:

- `POST /v1/channels` (Bearer, any active user): creates a public or
  private channel and records the caller as its first `admin` (F29, R4).
  `400` malformed body; `422` invalid name (length/charset, R36); `409`
  case-insensitive name collision (Flow E.1a).
- `GET /v1/channels/{channel_id}` (Bearer, any active user): a member may
  read any channel; a private channel a non-member cannot see returns the
  same uniform `404` as a truly missing channel (non-enumerating).
- `GET /v1/channels/public` (Bearer, any active user): offset-paginated
  browse of public channels the caller does not already belong to (F30).
  Page size default and maximum are 50; an invalid `limit`/`offset` is
  `400`.

Every body is parsed via `app.core.request_body.parse_body` (not a typed
FastAPI body parameter) so a malformed body maps to the contract's `400`
rather than FastAPI's default `422` — see that module's docstring, and
`app.api.invites` for the same pattern. `limit`/`offset` are accepted as
raw strings and parsed manually for the same reason: FastAPI's automatic
`int` query-parameter coercion would raise its own `422` on a non-numeric
value, but the frozen contract calls for `400` on any invalid pagination
parameter.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthenticatedUser, require_auth
from app.core.request_body import openapi_request_body, parse_body
from app.db.session import get_db_session
from app.schemas.channels import (
    ChannelCreateRequest,
    ChannelCreateResponse,
    ChannelDetailResponse,
    PublicChannelItem,
    PublicChannelListResponse,
)
from app.services.channels import (
    PUBLIC_CHANNELS_DEFAULT_LIMIT,
    PUBLIC_CHANNELS_MAX_LIMIT,
    create_channel,
    get_channel_view,
    is_valid_channel_name,
    list_public_channels,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/channels", tags=["channels"])

_INVALID_NAME_DETAIL = "Channel name must be 1-80 characters of letters, digits, spaces, - or _."
_NAME_CONFLICT_DETAIL = "A channel with this name already exists."
_NOT_FOUND_DETAIL = "No such channel."
_INVALID_LIMIT_DETAIL = "limit must be a positive integer no greater than 50."
_INVALID_OFFSET_DETAIL = "offset must be a non-negative integer."

# Postgres SQLSTATE for `unique_violation` — same race-safe backstop
# pattern as `app.api.auth._is_unique_violation`.
_UNIQUE_VIOLATION_SQLSTATE = "23505"

_CurrentUser = Annotated[AuthenticatedUser, Depends(require_auth)]
_DbSession = Annotated[AsyncSession, Depends(get_db_session)]
_Payload = Annotated[dict[str, Any], Body(...)]


def _is_unique_violation(exc: IntegrityError) -> bool:
    sqlstate = getattr(exc.orig, "sqlstate", None)
    return sqlstate == _UNIQUE_VIOLATION_SQLSTATE


def _parse_pagination(limit_raw: str | None, offset_raw: str | None) -> tuple[int, int]:
    """Parse+validate `limit`/`offset`, raising the frozen `400` on failure.

    `limit` defaults to 50 and is clamped down to the max of 50 (never
    raised above it); anything non-numeric or out of range (`limit < 1`,
    `offset < 0`) is a `400`, matching the contract's "Invalid pagination
    params" outcome.
    """

    limit = PUBLIC_CHANNELS_DEFAULT_LIMIT
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=_INVALID_LIMIT_DETAIL
            ) from None
        if limit < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=_INVALID_LIMIT_DETAIL
            )
        limit = min(limit, PUBLIC_CHANNELS_MAX_LIMIT)

    offset = 0
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=_INVALID_OFFSET_DETAIL
            ) from None
        if offset < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=_INVALID_OFFSET_DETAIL
            )

    return limit, offset


@router.post(
    "",
    response_model=ChannelCreateResponse,
    status_code=status.HTTP_201_CREATED,
    openapi_extra=openapi_request_body(
        ChannelCreateRequest, {"name": "engineering", "is_private": False}
    ),
)
async def create_channel_route(
    payload: _Payload, current: _CurrentUser, db: _DbSession
) -> ChannelCreateResponse:
    body = parse_body(ChannelCreateRequest, payload)

    if not is_valid_channel_name(body.name):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=_INVALID_NAME_DETAIL
        )

    try:
        channel = await create_channel(
            db, name=body.name, is_private=body.is_private, created_by=current.user_id
        )
    except IntegrityError as exc:
        await db.rollback()
        if not _is_unique_violation(exc):
            raise
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_NAME_CONFLICT_DETAIL
        ) from None

    await db.commit()

    logger.info(
        "channel created",
        extra={"channel_id": str(channel.id), "created_by": str(current.user_id)},
    )

    return ChannelCreateResponse.from_channel(channel, member_count=1)


@router.get(
    "/public",
    response_model=PublicChannelListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_public_channels_route(
    current: _CurrentUser,
    db: _DbSession,
    limit: Annotated[str | None, Query()] = None,
    offset: Annotated[str | None, Query()] = None,
) -> PublicChannelListResponse:
    resolved_limit, resolved_offset = _parse_pagination(limit, offset)

    page = await list_public_channels(
        db, caller_id=current.user_id, limit=resolved_limit, offset=resolved_offset
    )

    items = [
        PublicChannelItem(
            id=row.channel.id,
            name=row.channel.name,
            is_private=False,
            member_count=row.member_count,
        )
        for row in page.rows
    ]

    return PublicChannelListResponse(
        items=items, total=page.total, limit=resolved_limit, offset=resolved_offset
    )


@router.get(
    "/{channel_id}",
    response_model=ChannelDetailResponse,
    status_code=status.HTTP_200_OK,
)
async def get_channel_route(
    channel_id: UUID, current: _CurrentUser, db: _DbSession
) -> ChannelDetailResponse:
    view = await get_channel_view(db, channel_id=channel_id, caller_id=current.user_id)
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)

    return ChannelDetailResponse.from_channel(
        view.channel, member_count=view.member_count, my_role=view.my_role
    )
