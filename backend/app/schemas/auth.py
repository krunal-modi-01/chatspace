"""Request/response schemas for `/v1/auth/login` and `/v1/auth/refresh` (T15).

`/v1/auth/logout` takes an (ignored) `{}` body and returns `204` with no
schema; `/v1/auth/sessions` schemas live in `app.schemas.sessions` (T10).

Both request bodies are validated manually in `app.api.auth` (via
`model_validate` against a raw-parsed JSON body) rather than as a FastAPI
body-parameter type, so a malformed body maps to the frozen contract's
`400` — the framework's default `RequestValidationError` path (installed
globally in `app.core.errors`) renders `422`, which is reserved by this
contract for field-content validation failures (e.g. password policy),
not structural malformed-body failures.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.user import UserOut


class LoginRequest(BaseModel):
    email: str = Field(min_length=1)
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    refresh_token: str
    user: UserOut


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    refresh_token: str
