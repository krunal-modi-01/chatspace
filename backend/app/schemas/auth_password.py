"""Pydantic schemas for `/v1/auth/password*` (T16, frozen contract).

These are validated manually via `app.core.request_body.parse_body`
rather than declared as a route's typed body parameter, so a
missing/wrong-type field maps to the contract's `400` (not FastAPI's
default `422`) — see that module's docstring.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PasswordResetRequest(BaseModel):
    """Body of `POST /v1/auth/password-reset`."""

    email: str = Field(min_length=1)


class PasswordResetAcceptedResponse(BaseModel):
    """`202` uniform envelope — identical whether or not the email exists (F15)."""

    message: str


class PasswordResetConfirmRequest(BaseModel):
    """Body of `POST /v1/auth/password-reset/confirm`.

    `reset_token` is the raw single-use credential — never logged, never
    echoed back in any response (see `app.services.password_reset`).
    """

    reset_token: str = Field(min_length=1)
    new_password: str = Field(min_length=1)


class PasswordChangeRequest(BaseModel):
    """Body of `POST /v1/auth/password/change`."""

    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=1)
