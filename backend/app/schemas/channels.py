"""Pydantic schemas for `/v1/channels*` (T18, frozen contract).

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
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.models.channel import Channel
from app.models.channel_member import ChannelMemberRole

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
