"""Pydantic schemas for `/v1/admin/*` (T44, frozen contract for deactivate/reactivate).

`AdminUserListItem`/`AdminUserListResponse` back `GET /v1/admin/users`: a
paginated, searchable user directory. Built explicitly field-by-field
from the ORM `User` model (mirroring `app.schemas.users.UserProfile`),
never via a blanket `model_validate` of the row — `hashed_password` (and
every other sensitive column) can never leak into this response by
accident, only fields this schema names explicitly. Reuses
`app.schemas.users._workspace_role` for the same `is_system_admin` ->
`role` projection `UserProfile` uses, so the wire `role` value is
identical everywhere a user appears in the API.

`AdminActionRequest`/`AdminUserActionResponse` back the frozen
`POST /v1/admin/users/{id}/deactivate` and `.../reactivate` contract
(`api-contract.md` lines 587-618): request body is `{}` (validated for
shape only, mirroring `InviteResendRequest`), response body is
`{ id, is_active }`.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.user import User
from app.schemas.users import WorkspaceRole, _workspace_role


class AdminUserListItem(BaseModel):
    """One row of `GET /v1/admin/users` — never includes `hashed_password`."""

    id: UUID
    first_name: str
    last_name: str
    username: str
    email: str
    role: WorkspaceRole
    is_active: bool
    last_seen: datetime | None

    @classmethod
    def from_user(cls, user: User) -> AdminUserListItem:
        return cls(
            id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
            email=user.email,
            role=_workspace_role(user),
            is_active=user.is_active,
            last_seen=user.last_seen,
        )


class AdminUserListResponse(BaseModel):
    """`200` body of `GET /v1/admin/users`: `{ items, next_cursor }`."""

    items: list[AdminUserListItem]
    next_cursor: str | None


class AdminActionRequest(BaseModel):
    """Body of deactivate/reactivate — frozen contract: `{}`."""


class AdminUserActionResponse(BaseModel):
    """`200` body of deactivate/reactivate: `{ id, is_active }` (frozen contract)."""

    id: UUID
    is_active: bool
