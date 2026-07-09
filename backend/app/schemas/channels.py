"""Pydantic schemas for `/v1/channels*` (T18/T19, frozen contract).

`ChannelCreateRequest` is validated manually via
`app.core.request_body.parse_body` (not a typed FastAPI body parameter),
so a missing/wrong-type field maps to the contract's `400` — see that
module's docstring. Name length/charset (`1-80`, `[A-Za-z0-9 _-]`) is a
separate, semantic `422` check the route performs after structural
parsing succeeds (mirrors `app.api.invites.issue_invite`'s
email-format-vs-structural-parse split).

Three distinct response shapes, matched exactly to the frozen contract:

- `ChannelCreateResponse` (`201` of `POST /v1/channels`): no `my_role`.
- `ChannelDetailResponse` (`200` of `GET /v1/channels/{id}`): adds
  `my_role` (nullable — `null` for a non-member viewing a public
  channel).
- `PublicChannelItem` (an entry in `GET /v1/channels/public`'s `items`):
  the trimmed `{ id, name, is_private, member_count }` shape only.

T19 (membership mutation) adds:

- `MembershipResponse`: the `{ channel_id, user_id, role, joined_at }`
  shape shared by `POST /{id}/join`, `POST /{id}/members`, and `PATCH
  /{id}/members/{user_id}`.
- `MemberAddRequest` / `MemberRoleUpdateRequest`: request bodies for the
  same two mutating endpoints. `role` is deliberately typed `str` (not
  `ChannelRoleWire`) so an unknown value is caught by the route's own
  semantic `422` check rather than Pydantic's structural validation
  folding it into the `400` malformed-body path.
- `MemberListItem` / `MemberListResponse`: `GET /{id}/members`'s
  `{ items, total }` envelope.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.models.channel import Channel
from app.models.channel_member import ChannelMember, ChannelMemberRole
from app.models.user import User

ChannelRoleWire = Literal["member", "admin"]


class ChannelCreateRequest(BaseModel):
    """Body of `POST /v1/channels`.

    `name`'s length/charset is deliberately *not* enforced here (only
    structural presence/type) — the frozen contract distinguishes a
    malformed body (`400`, missing/wrong-type field) from an invalid name
    (`422`, length/charset), and only the route layer can tell the two
    apart by running the charset check after this structural parse
    succeeds.
    """

    name: str
    is_private: bool


class ChannelCreateResponse(BaseModel):
    """`201` body of `POST /v1/channels` — no `my_role` field."""

    id: UUID
    name: str
    is_private: bool
    created_by: UUID
    created_at: datetime
    member_count: int

    @classmethod
    def from_channel(cls, channel: Channel, *, member_count: int) -> ChannelCreateResponse:
        return cls(
            id=channel.id,
            name=channel.name,
            is_private=channel.is_private,
            created_by=channel.created_by,
            created_at=channel.created_at,
            member_count=member_count,
        )


class ChannelDetailResponse(BaseModel):
    """`200` body of `GET /v1/channels/{id}` — adds `my_role` over the create shape."""

    id: UUID
    name: str
    is_private: bool
    created_by: UUID
    created_at: datetime
    member_count: int
    my_role: ChannelRoleWire | None

    @classmethod
    def from_channel(
        cls, channel: Channel, *, member_count: int, my_role: ChannelMemberRole | None
    ) -> ChannelDetailResponse:
        return cls(
            id=channel.id,
            name=channel.name,
            is_private=channel.is_private,
            created_by=channel.created_by,
            created_at=channel.created_at,
            member_count=member_count,
            my_role=my_role.value if my_role is not None else None,
        )


class PublicChannelItem(BaseModel):
    """One entry of `GET /v1/channels/public`'s `items` array — trimmed shape."""

    id: UUID
    name: str
    is_private: Literal[False]
    member_count: int


class PublicChannelListResponse(BaseModel):
    """`200` envelope of `GET /v1/channels/public` — offset-pagination shape."""

    items: list[PublicChannelItem]
    total: int
    limit: int
    offset: int


class MembershipResponse(BaseModel):
    """`200` body shared by `POST /{id}/join`, `POST`/`PATCH .../members(/{user_id})`."""

    channel_id: UUID
    user_id: UUID
    role: ChannelRoleWire
    joined_at: datetime

    @classmethod
    def from_membership(cls, membership: ChannelMember) -> MembershipResponse:
        return cls(
            channel_id=membership.channel_id,
            user_id=membership.user_id,
            role=membership.role.value,
            joined_at=membership.joined_at,
        )


class MemberAddRequest(BaseModel):
    """Body of `POST /v1/channels/{id}/members`.

    `role`'s validity (`member`/`admin`) is deliberately *not* enforced
    here — only structural presence/type — so an unknown value maps to
    the frozen `422` (checked by the route after this structural parse
    succeeds) rather than Pydantic's own `400` malformed-body path.
    """

    user_id: UUID
    role: str


class MemberRoleUpdateRequest(BaseModel):
    """Body of `PATCH /v1/channels/{id}/members/{user_id}` — see `MemberAddRequest`."""

    role: str


class MemberListItem(BaseModel):
    """One entry of `GET /v1/channels/{id}/members`'s `items` array."""

    user_id: UUID
    username: str
    first_name: str
    last_name: str
    avatar_url: str | None
    role: ChannelRoleWire
    joined_at: datetime

    @classmethod
    def from_row(cls, user: User, membership: ChannelMember) -> MemberListItem:
        return cls(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            avatar_url=user.avatar_url,
            role=membership.role.value,
            joined_at=membership.joined_at,
        )


class MemberListResponse(BaseModel):
    """`200` envelope of `GET /v1/channels/{id}/members` — offset-pagination shape."""

    items: list[MemberListItem]
    total: int
