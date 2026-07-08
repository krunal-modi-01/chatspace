"""Pydantic schemas for `/v1/invites*` (T13, frozen contract).

`InviteCreateRequest` is validated manually via `app.core.request_body.parse_body`
(not a typed FastAPI body parameter), so a missing/blank/wrong-type `email`
field maps to the contract's `400` — see that module's docstring. A
syntactically-present-but-invalid email address (e.g. `"not-an-email"`)
passes this structural check and is instead rejected with the frozen `422`
by `app.core.email_validation.is_valid_email_format` at the route layer.

The raw invite token is never a field on any response schema here — see
`app.services.invites`.

`InviteListItem`/`InviteListResponse` back `GET /v1/invites` (T43): unlike
`InviteWireStatus` above (fixed `"pending"`, the only status a freshly
*issued* invite can have), the list surface must also project
`"accepted"`/`"revoked"`/and a derived `"expired"` — the last one is never
a persisted `InviteStatus` value (see `app.models.invite`'s docstring for
why), so `_invite_list_wire_status` derives it at read time from
`status is pending AND expires_at <= now`, exactly mirroring
`app.services.invites.find_valid_invite_by_token`'s own expiry check.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.invite import Invite, InviteStatus

InviteWireStatus = Literal["pending"]
InviteListWireStatus = Literal["pending", "accepted", "revoked", "expired"]


class InviteCreateRequest(BaseModel):
    """Body of `POST /v1/invites`."""

    email: str = Field(min_length=1)


class InviteResendRequest(BaseModel):
    """Body of `POST /v1/invites/{id}/resend` — frozen contract: `{}`."""


class InviteResponse(BaseModel):
    """`201` body of `POST /v1/invites` — raw token **never** included."""

    id: UUID
    email: str
    status: InviteWireStatus
    expiry: datetime
    issued_by: UUID
    created_at: datetime

    @classmethod
    def from_invite(cls, invite: Invite) -> InviteResponse:
        return cls(
            id=invite.id,
            email=invite.email,
            status="pending",
            expiry=invite.expires_at,
            issued_by=invite.created_by,
            created_at=invite.created_at,
        )


class InviteResendResponse(BaseModel):
    """`200` body of `POST /v1/invites/{id}/resend`."""

    id: UUID
    email: str
    status: InviteWireStatus
    expiry: datetime

    @classmethod
    def from_invite(cls, invite: Invite) -> InviteResendResponse:
        return cls(id=invite.id, email=invite.email, status="pending", expiry=invite.expires_at)


class InviteTokenValidationResponse(BaseModel):
    """`200` body of `GET /v1/invites/{token}` — locked email for form pre-fill."""

    email: str
    expiry: datetime


def _invite_list_wire_status(
    invite: Invite, *, now: datetime | None = None
) -> InviteListWireStatus:
    ts = now or datetime.now(UTC)
    if invite.status is InviteStatus.PENDING and invite.expires_at <= ts:
        return "expired"
    return invite.status.value  # "pending" | "accepted" | "revoked"


class InviteListItem(BaseModel):
    """One row of `GET /v1/invites` (T43) — raw token never included."""

    id: UUID
    email: str
    status: InviteListWireStatus
    expiry: datetime
    issued_at: datetime

    @classmethod
    def from_invite(cls, invite: Invite, *, now: datetime | None = None) -> InviteListItem:
        return cls(
            id=invite.id,
            email=invite.email,
            status=_invite_list_wire_status(invite, now=now),
            expiry=invite.expires_at,
            issued_at=invite.created_at,
        )


class InviteListResponse(BaseModel):
    """`200` body of `GET /v1/invites` (T43): `{ items, next_cursor }`."""

    items: list[InviteListItem]
    next_cursor: str | None
