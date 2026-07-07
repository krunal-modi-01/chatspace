"""`PATCH /v1/me` update logic (T17, F19/F20/F21).

Kept separate from the route handler so the immutable-field guard and the
non-empty-name validation are independently unit-testable without going
through FastAPI/HTTP at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.user import User
from app.schemas.users import ProfileUpdateRequest


class ImmutableFieldChangeError(Exception):
    """Raised when the caller attempts to change `email` or `username` (F20)."""

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"'{field}' is immutable and cannot be changed.")


class EmptyNameError(Exception):
    """Raised when `first_name`/`last_name` would become empty (F19/R27)."""

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"'{field}' must not be empty.")


@dataclass(frozen=True, slots=True)
class ProfileUpdate:
    """The validated, applyable subset of a `PATCH /v1/me` request."""

    first_name: str | None
    last_name: str | None
    avatar_url: str | None
    # `avatar_url` explicitly set to `null` (clear the avatar, fall back to
    # initials — F21) must be distinguished from "not sent at all"; both
    # decode to `None` on `ProfileUpdateRequest.avatar_url`, so this flag
    # carries whether the client actually included the key.
    avatar_url_provided: bool


def validate_profile_update(user: User, request: ProfileUpdateRequest) -> ProfileUpdate:
    """Validate a `PATCH /v1/me` request against the current user row.

    Raises `ImmutableFieldChangeError` if `email`/`username` are present
    and differ from the caller's current value (F20 — a `400`). Sending
    the *same* value back is tolerated so the endpoint stays idempotent
    per the contract ("same body -> same resulting state") rather than
    erroring on a harmless no-op resend.

    Raises `EmptyNameError` if `first_name`/`last_name` are present but
    blank/whitespace-only (F19 — a `422`).
    """

    fields_set = request.model_fields_set

    if "email" in fields_set and request.email != user.email:
        raise ImmutableFieldChangeError("email")
    if "username" in fields_set and request.username != user.username:
        raise ImmutableFieldChangeError("username")

    first_name = request.first_name
    if "first_name" in fields_set:
        if first_name is None or not first_name.strip():
            raise EmptyNameError("first_name")

    last_name = request.last_name
    if "last_name" in fields_set:
        if last_name is None or not last_name.strip():
            raise EmptyNameError("last_name")

    return ProfileUpdate(
        first_name=first_name,
        last_name=last_name,
        avatar_url=request.avatar_url,
        avatar_url_provided="avatar_url" in fields_set,
    )


def apply_profile_update(user: User, update: ProfileUpdate) -> None:
    """Mutate `user` in place with the validated fields from `update`.

    Caller is responsible for flushing/committing the surrounding
    session. Only touches fields that were actually present in the
    request — `None` values not sent are never applied.
    """

    if update.first_name is not None:
        user.first_name = update.first_name
    if update.last_name is not None:
        user.last_name = update.last_name
    if update.avatar_url_provided:
        user.avatar_url = update.avatar_url
