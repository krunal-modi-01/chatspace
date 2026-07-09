"""`/v1/channels*` — channel create/get/public browse/membership (T18/T19, frozen contract).

T18 (create/get/public browse):

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

T19 (membership mutation, F31-F37):

- `POST /v1/channels/{channel_id}/join`: join a public channel directly
  (F31); idempotent; `403` if private, uniform `404` if it doesn't exist.
- `POST /v1/channels/{channel_id}/leave`: leave a channel the caller
  belongs to; sole-admin succession runs first (F35/F36); never `409`
  (leaving is always allowed, even into the F37 zero-admin terminal
  state). Idempotent: a repeat/no-op leave by a non-member, and an
  absent channel, both return `204`.
- `GET /v1/channels/{channel_id}/members`: offset-paginated member list;
  caller must be a member. Privacy decides the non-member status: a
  private channel the caller doesn't belong to is a uniform `404`
  (non-enumerating, same as `GET /{channel_id}`); a public channel the
  caller isn't a member of is `403` (its existence is already
  discoverable).
- `POST /v1/channels/{channel_id}/members`: an admin adds a member
  (F32/F33); the only way into a private channel; `409` if the channel is
  in the F37 zero-admin frozen state.
- `PATCH /v1/channels/{channel_id}/members/{user_id}`: an admin changes a
  member's role (F33); idempotent no-op if unchanged; `409` if frozen.
- `DELETE /v1/channels/{channel_id}/members/{user_id}`: an admin removes
  a member (F33); sole-admin succession runs first if the target is the
  channel's only admin; idempotent (`204`) if the target isn't currently a
  member; `409` if frozen.

Every body is parsed via `app.core.request_body.parse_body` (not a typed
FastAPI body parameter) so a malformed body maps to the contract's `400`
rather than FastAPI's default `422` — see that module's docstring, and
`app.api.invites` for the same pattern. `limit`/`offset` are accepted as
raw strings and parsed manually for the same reason: FastAPI's automatic
`int` query-parameter coercion would raise its own `422` on a non-numeric
value, but the frozen contract calls for `400` on any invalid pagination
parameter. `join`/`leave` take no parsed body at all — the contract's
`{}` request is accepted-and-ignored, mirroring `app.api.auth.logout`.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthenticatedUser, require_auth
from app.core.request_body import openapi_request_body, parse_body
from app.db.session import get_db_session
from app.models.channel import Channel
from app.models.channel_member import ChannelMemberRole
from app.schemas.channels import (
    ChannelCreateRequest,
    ChannelCreateResponse,
    ChannelDetailResponse,
    MemberAddRequest,
    MemberListItem,
    MemberListResponse,
    MemberRoleUpdateRequest,
    MembershipResponse,
    PublicChannelItem,
    PublicChannelListResponse,
)
from app.services.channels import (
    CHANNEL_MEMBERS_DEFAULT_LIMIT,
    CHANNEL_MEMBERS_MAX_LIMIT,
    PUBLIC_CHANNELS_DEFAULT_LIMIT,
    PUBLIC_CHANNELS_MAX_LIMIT,
    AddMemberOutcome,
    ChangeRoleOutcome,
    JoinOutcome,
    LeaveOutcome,
    RemoveMemberOutcome,
    add_channel_member,
    change_member_role,
    create_channel,
    get_channel_view,
    get_membership,
    is_valid_channel_name,
    join_public_channel,
    leave_channel,
    list_channel_members,
    list_public_channels,
    remove_channel_member,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/channels", tags=["channels"])

_INVALID_NAME_DETAIL = "Channel name must be 1-80 characters of letters, digits, spaces, - or _."
_NAME_CONFLICT_DETAIL = "A channel with this name already exists."
_NOT_FOUND_DETAIL = "No such channel."
_INVALID_LIMIT_DETAIL = "limit must be a positive integer no greater than 50."
_INVALID_OFFSET_DETAIL = "offset must be a non-negative integer."
_PRIVATE_CHANNEL_DETAIL = "This channel is private; direct join is not allowed."
_NOT_A_MEMBER_DETAIL = "Not a member of this channel."
_TARGET_NOT_FOUND_DETAIL = "No such channel or target user."
_TARGET_NOT_MEMBER_DETAIL = "No such channel or member."
_CALLER_NOT_ADMIN_DETAIL = "This action requires being an admin of this channel."
_ZERO_ADMIN_DETAIL = "This channel currently has no admins; membership mutation is blocked."
_INVALID_ROLE_DETAIL = "role must be 'member' or 'admin'."

# Postgres SQLSTATE for `unique_violation` — same race-safe backstop
# pattern as `app.api.auth._is_unique_violation`.
_UNIQUE_VIOLATION_SQLSTATE = "23505"

_CurrentUser = Annotated[AuthenticatedUser, Depends(require_auth)]
_DbSession = Annotated[AsyncSession, Depends(get_db_session)]
_Payload = Annotated[dict[str, Any], Body(...)]

_ROLE_BY_WIRE_VALUE = {role.value: role for role in ChannelMemberRole}


def _is_unique_violation(exc: IntegrityError) -> bool:
    sqlstate = getattr(exc.orig, "sqlstate", None)
    return sqlstate == _UNIQUE_VIOLATION_SQLSTATE


def _parse_pagination(
    limit_raw: str | None, offset_raw: str | None, *, default_limit: int, max_limit: int
) -> tuple[int, int]:
    """Parse+validate `limit`/`offset`, raising the frozen `400` on failure.

    `limit` defaults to `default_limit` and is clamped down to `max_limit`
    (never raised above it); anything non-numeric or out of range
    (`limit < 1`, `offset < 0`) is a `400`, matching the contract's
    "Invalid pagination params" outcome.
    """

    limit = default_limit
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
        limit = min(limit, max_limit)

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


def _parse_role(raw_role: str) -> ChannelMemberRole:
    """Validate `raw_role` against the two known wire values, or raise the frozen `422`.

    Per the contract's cross-cutting convention ("Enum-typed fields ...
    are open sets; clients MUST tolerate unknown values") this is a
    server-side *input* validation, not a statement that the enum is
    closed on the wire — an unrecognized `role` on a request body is
    still a `422`, exactly as the contract's per-endpoint tables specify.
    """

    role = _ROLE_BY_WIRE_VALUE.get(raw_role)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=_INVALID_ROLE_DETAIL
        )
    return role


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
    resolved_limit, resolved_offset = _parse_pagination(
        limit,
        offset,
        default_limit=PUBLIC_CHANNELS_DEFAULT_LIMIT,
        max_limit=PUBLIC_CHANNELS_MAX_LIMIT,
    )

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


@router.post(
    "/{channel_id}/join",
    response_model=MembershipResponse,
    status_code=status.HTTP_200_OK,
)
async def join_channel_route(
    channel_id: UUID, current: _CurrentUser, db: _DbSession
) -> MembershipResponse:
    result = await join_public_channel(db, channel_id=channel_id, user_id=current.user_id)

    if result.outcome is JoinOutcome.NOT_FOUND:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)
    if result.outcome is JoinOutcome.PRIVATE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_PRIVATE_CHANNEL_DETAIL)

    await db.commit()
    assert result.membership is not None

    if result.outcome is JoinOutcome.JOINED:
        logger.info(
            "channel joined",
            extra={"channel_id": str(channel_id), "user_id": str(current.user_id)},
        )

    return MembershipResponse.from_membership(result.membership)


@router.post(
    "/{channel_id}/leave",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def leave_channel_route(channel_id: UUID, current: _CurrentUser, db: _DbSession) -> Response:
    outcome = await leave_channel(db, channel_id=channel_id, user_id=current.user_id)

    # Leaving is idempotent: a repeat/no-op leave by a non-member, and an
    # absent channel, both return `204` (no mutation, no error) rather than
    # `404` — this also keeps the endpoint non-enumerating, since a caller
    # cannot distinguish "already left"/"never a member" from "no such
    # channel" by status code alone.
    if outcome is LeaveOutcome.NOT_MEMBER:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    await db.commit()

    logger.info(
        "channel left",
        extra={"channel_id": str(channel_id), "user_id": str(current.user_id)},
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{channel_id}/members",
    response_model=MemberListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_channel_members_route(
    channel_id: UUID,
    current: _CurrentUser,
    db: _DbSession,
    limit: Annotated[str | None, Query()] = None,
    offset: Annotated[str | None, Query()] = None,
) -> MemberListResponse:
    resolved_limit, resolved_offset = _parse_pagination(
        limit,
        offset,
        default_limit=CHANNEL_MEMBERS_DEFAULT_LIMIT,
        max_limit=CHANNEL_MEMBERS_MAX_LIMIT,
    )

    channel = await db.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)

    membership = await get_membership(db, channel_id=channel_id, user_id=current.user_id)
    if membership is None:
        # Privacy decides which status a non-member gets: a private
        # channel is hidden behind the same uniform, non-enumerating `404`
        # as `GET /{channel_id}` (`get_channel_view`'s visibility gate) —
        # its existence must not be disclosed to a non-member. A public
        # channel's existence is already discoverable via `GET
        # /public`/direct-id lookup, so a non-member there gets `403`.
        if channel.is_private:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_NOT_A_MEMBER_DETAIL)

    page = await list_channel_members(
        db, channel_id=channel_id, limit=resolved_limit, offset=resolved_offset
    )

    items = [MemberListItem.from_row(row.user, row.membership) for row in page.rows]
    return MemberListResponse(items=items, total=page.total)


@router.post(
    "/{channel_id}/members",
    response_model=MembershipResponse,
    status_code=status.HTTP_200_OK,
    openapi_extra=openapi_request_body(MemberAddRequest, {"user_id": "01J...", "role": "member"}),
)
async def add_channel_member_route(
    channel_id: UUID, payload: _Payload, current: _CurrentUser, db: _DbSession
) -> MembershipResponse:
    body = parse_body(MemberAddRequest, payload)
    role = _parse_role(body.role)

    result = await add_channel_member(
        db,
        channel_id=channel_id,
        caller_id=current.user_id,
        target_user_id=body.user_id,
        role=role,
    )

    if result.outcome in (
        AddMemberOutcome.CHANNEL_NOT_FOUND,
        AddMemberOutcome.TARGET_USER_NOT_FOUND,
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_TARGET_NOT_FOUND_DETAIL)
    if result.outcome is AddMemberOutcome.CALLER_NOT_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_CALLER_NOT_ADMIN_DETAIL)
    if result.outcome is AddMemberOutcome.ZERO_ADMIN:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_ZERO_ADMIN_DETAIL)

    await db.commit()
    assert result.membership is not None

    if result.outcome is AddMemberOutcome.ADDED:
        logger.info(
            "channel member added",
            extra={
                "channel_id": str(channel_id),
                "user_id": str(body.user_id),
                "added_by": str(current.user_id),
            },
        )

    return MembershipResponse.from_membership(result.membership)


@router.patch(
    "/{channel_id}/members/{user_id}",
    response_model=MembershipResponse,
    status_code=status.HTTP_200_OK,
    openapi_extra=openapi_request_body(MemberRoleUpdateRequest, {"role": "admin"}),
)
async def update_channel_member_role_route(
    channel_id: UUID, user_id: UUID, payload: _Payload, current: _CurrentUser, db: _DbSession
) -> MembershipResponse:
    body = parse_body(MemberRoleUpdateRequest, payload)
    role = _parse_role(body.role)

    result = await change_member_role(
        db,
        channel_id=channel_id,
        caller_id=current.user_id,
        target_user_id=user_id,
        role=role,
    )

    if result.outcome in (
        ChangeRoleOutcome.CHANNEL_NOT_FOUND,
        ChangeRoleOutcome.TARGET_NOT_MEMBER,
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_TARGET_NOT_MEMBER_DETAIL)
    if result.outcome is ChangeRoleOutcome.CALLER_NOT_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_CALLER_NOT_ADMIN_DETAIL)
    if result.outcome is ChangeRoleOutcome.ZERO_ADMIN:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_ZERO_ADMIN_DETAIL)

    await db.commit()
    assert result.membership is not None

    if result.outcome is ChangeRoleOutcome.UPDATED:
        logger.info(
            "channel member role updated",
            extra={
                "channel_id": str(channel_id),
                "user_id": str(user_id),
                "updated_by": str(current.user_id),
                "role": role.value,
            },
        )

    return MembershipResponse.from_membership(result.membership)


@router.delete(
    "/{channel_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_channel_member_route(
    channel_id: UUID, user_id: UUID, current: _CurrentUser, db: _DbSession
) -> Response:
    outcome = await remove_channel_member(
        db, channel_id=channel_id, caller_id=current.user_id, target_user_id=user_id
    )

    if outcome in (
        RemoveMemberOutcome.CHANNEL_NOT_FOUND,
        RemoveMemberOutcome.TARGET_USER_NOT_FOUND,
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_TARGET_NOT_FOUND_DETAIL)
    if outcome is RemoveMemberOutcome.CALLER_NOT_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_CALLER_NOT_ADMIN_DETAIL)
    if outcome is RemoveMemberOutcome.ZERO_ADMIN:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_ZERO_ADMIN_DETAIL)

    await db.commit()

    if outcome is RemoveMemberOutcome.REMOVED:
        logger.info(
            "channel member removed",
            extra={
                "channel_id": str(channel_id),
                "user_id": str(user_id),
                "removed_by": str(current.user_id),
            },
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
