"""`user` object shape shared by login, `/v1/me`, and future user endpoints.

Verbatim per the frozen API contract:

    { id, username, email, first_name, last_name, avatar_url, role,
      is_active, last_seen, created_at }

`hashed_password` is never selected into this shape — `from_user` reads
every other column directly off the ORM `User` model and never touches
`hashed_password` at all, so there is no risk of it leaking even by
accident (R1/R24, F18).

`role` is not a stored column: the frozen database design encodes
workspace role as `users.is_system_admin` (boolean) rather than an enum
(see `docs/spec/chatspace-v1-database-design.md`, lines 149/496 — "v1 has
exactly two workspace roles, so a boolean `is_system_admin` ... is the
simpler faithful encoding"). `from_user` is the single place that maps
`is_system_admin` to the contract's `role: "system_admin" | "user"`
string so every wire response (login, `/v1/me`, later admin listings)
derives it identically.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.models.user import User

_Role = Literal["system_admin", "user"]


class UserOut(BaseModel):
    """The frozen `user` object shape. Never constructed from raw ORM
    attribute-mapping (`from_attributes`) since `role` requires a
    derivation, not a 1:1 column mapping — always build via `from_user`.
    """

    id: UUID
    username: str
    email: str
    first_name: str
    last_name: str
    avatar_url: str | None
    role: _Role
    is_active: bool
    last_seen: datetime | None
    created_at: datetime

    @classmethod
    def from_user(cls, user: User) -> UserOut:
        """Build the wire shape from a `User` ORM instance.

        Deliberately enumerates every field by hand (rather than
        `model_validate(user, from_attributes=True)`) so `hashed_password`
        can never be included by an incautious future edit, and so `role`
        gets its derived (not column-mapped) value.
        """

        return cls(
            id=user.id,
            username=user.username,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            avatar_url=user.avatar_url,
            role="system_admin" if user.is_system_admin else "user",
            is_active=user.is_active,
            last_seen=user.last_seen,
            created_at=user.created_at,
        )
