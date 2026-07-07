"""Pydantic schemas for `POST /v1/auth/register` (T14, frozen contract).

Validated manually via `app.core.request_body.parse_body` (not a typed
FastAPI body parameter), matching every other auth endpoint in this
package, so a missing/wrong-type field maps to the contract's `400`
rather than FastAPI's default `422` (reserved here for password-policy
failures, F23).

`RegisteredUser` is a **dedicated** response shape, not a reuse of
`app.schemas.user.UserOut` / `app.schemas.users.UserProfile`: the frozen
contract's `201` body for this endpoint lists exactly
`id, username, email, first_name, last_name, avatar_url, role,
created_at` — no `is_active`/`last_seen` — which is a narrower field set
than either of those existing shapes. Reusing one of them would leak two
extra fields the contract does not list for this response.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.user import User

_Role = Literal["system_admin", "user"]


class RegisterRequest(BaseModel):
    """Body of `POST /v1/auth/register`.

    `invite_token` is the raw, single-use credential validated via
    `app.services.invites.find_valid_invite_by_token` — never logged, never
    echoed back in any response.
    """

    invite_token: str = Field(min_length=1)
    username: str = Field(min_length=1)
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    password: str = Field(min_length=1)
    avatar_url: str | None = Field(default=None)


class RegisteredUser(BaseModel):
    """The `201` `user` object — verbatim per the frozen contract's field list.

    Never includes `hashed_password`, `is_active`, or `last_seen`; built
    explicitly field-by-field from a `User` ORM instance so an incautious
    future edit can never widen this shape by accident.
    """

    id: UUID
    username: str
    email: str
    first_name: str
    last_name: str
    avatar_url: str | None
    role: _Role
    created_at: datetime

    @classmethod
    def from_user(cls, user: User) -> RegisteredUser:
        return cls(
            id=user.id,
            username=user.username,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            avatar_url=user.avatar_url,
            role="system_admin" if user.is_system_admin else "user",
            created_at=user.created_at,
        )
