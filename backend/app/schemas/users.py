"""Pydantic schemas for the `user` object and `/v1/me` (frozen contract, T17).

The `user` object shape (verbatim from the contract, shared by
`GET /v1/me`, `PATCH /v1/me`, login, and register):

    { id, username, email, first_name, last_name, avatar_url, role,
      is_active, last_seen, created_at }

`hashed_password` is never part of this schema (F18/R24) — `UserProfile`
is built explicitly field-by-field from the ORM `User` model, never via a
blanket `model_validate` of the whole row, so a future column addition to
`User` can never leak into a response by accident.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.user import User

# Workspace-level role is a derived, two-valued open enum (contract line 20:
# "Enum-typed fields ... are documented as open sets; clients MUST tolerate
# unknown values") backed by `users.is_system_admin` — see the database
# design doc's "Workspace-role encoding" note. There is no `role` column;
# this is the wire projection of that boolean.
WorkspaceRole = Literal["system_admin", "user"]


def _workspace_role(user: User) -> WorkspaceRole:
    return "system_admin" if user.is_system_admin else "user"


class UserProfile(BaseModel):
    """The `user` object returned by `GET /v1/me` and `PATCH /v1/me`."""

    id: UUID
    username: str
    email: str
    first_name: str
    last_name: str
    avatar_url: str | None
    role: WorkspaceRole
    is_active: bool
    last_seen: datetime | None
    created_at: datetime

    @classmethod
    def from_user(cls, user: User) -> UserProfile:
        """Build a `UserProfile` explicitly from a `User` row.

        Never `hashed_password`, `is_system_admin` (raw), `must_change_password`,
        or `email_verified` — only the fields the frozen contract lists.
        """

        return cls(
            id=user.id,
            username=user.username,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            avatar_url=user.avatar_url,
            role=_workspace_role(user),
            is_active=user.is_active,
            last_seen=user.last_seen,
            created_at=user.created_at,
        )


class ProfileUpdateRequest(BaseModel):
    """`PATCH /v1/me` request body.

    `first_name`/`last_name`/`avatar_url` are the only fields this
    endpoint may change (F19). `email`/`username` are accepted here too,
    purely so an attempt to *send* them can be detected and turned into a
    `400` (F20, immutable) rather than being silently ignored as unknown
    fields — silently ignoring a client's explicit change request would
    be a worse API than rejecting it outright.

    Field-level validation (non-empty name -> 422) is intentionally left
    to the route handler rather than a Pydantic validator here: an empty
    `first_name`/`last_name` must produce a `422` problem+json body only
    when that field is actually present in the request (a PATCH that
    omits the field entirely must not fail just because some hypothetical
    default is empty), so `None`-vs-"not sent" has to be distinguished via
    `model_fields_set`, which is more natural to check in the handler.
    """

    first_name: str | None = Field(default=None)
    last_name: str | None = Field(default=None)
    avatar_url: str | None = Field(default=None)
    email: str | None = Field(default=None)
    username: str | None = Field(default=None)
