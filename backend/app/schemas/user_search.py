"""Pydantic schemas for `GET /v1/users/search` (T73, F76/R59, ADR-0016).

`UserSearchItem`/`UserSearchResponse` back the scoped workspace
user-directory search that fronts the channel member-picker (F32/F33) and
the DM "new message" picker (F46). Field minimization is a hard security
acceptance criterion here — this is deliberately a *narrower* projection
than `app.schemas.admin.AdminUserListItem` (`GET /v1/admin/users`, F72):
`UserSearchItem` is built explicitly field-by-field from the ORM `User`
model, never via a blanket `model_validate` of the row, so it can never
leak `email`, `is_active`, `is_system_admin`/`role`, `last_seen`,
`hashed_password`, or `created_at` even if `User` grows new columns later
-- only the fields named below ever reach a caller.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from app.models.user import User


class UserSearchItem(BaseModel):
    """One directory match — minimal public identity only (R59/ADR-0016).

    Never `email`, `is_active`, `last_seen`, or `role` — this is the
    contractual line separating this endpoint from the System-Admin-only
    `GET /v1/admin/users`.
    """

    id: UUID
    username: str
    first_name: str
    last_name: str
    avatar_url: str | None

    @classmethod
    def from_user(cls, user: User) -> UserSearchItem:
        return cls(
            id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            avatar_url=user.avatar_url,
        )


class UserSearchResponse(BaseModel):
    """`200` body of `GET /v1/users/search`: `{ items, next_cursor }`."""

    items: list[UserSearchItem]
    next_cursor: str | None
