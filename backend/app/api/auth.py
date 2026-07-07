"""`POST /v1/auth/login`, `/refresh`, `/logout` (T15, ADR-0006, ADR-0009).

`GET`/`DELETE /v1/auth/sessions` live in `app.api.sessions` (T10) and are
not touched here.

Request bodies for `login`/`refresh` are parsed manually (raw JSON ->
`model_validate`) rather than as FastAPI body-parameter types, so a
malformed body maps to the frozen contract's `400` rather than the
framework-default `422` that the globally installed
`RequestValidationError` handler produces (`app.core.errors`) — that `422`
path is reserved by this contract for field-content validation failures
(e.g. password policy), not structurally malformed JSON. `logout` takes no
parsed body at all (the contract's `{}` is accepted-and-ignored).
"""

from __future__ import annotations

import ipaddress
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.deps import AuthenticatedUser, require_auth
from app.db.redis import get_redis_client
from app.db.session import get_db_session
from app.schemas.auth import LoginRequest, LoginResponse, RefreshRequest, RefreshResponse
from app.schemas.user import UserOut
from app.services.auth import (
    AccountDeactivatedError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    MustChangePasswordError,
    authenticate_and_login,
    refresh_session,
)
from app.services.session_revocation import invalidate_session_cache
from app.services.sessions import revoke_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_DbSession = Annotated[AsyncSession, Depends(get_db_session)]
_SettingsDep = Annotated[Settings, Depends(get_settings)]
_CurrentUser = Annotated[AuthenticatedUser, Depends(require_auth)]

_INVALID_CREDENTIALS_DETAIL = "The email or password is incorrect."
_ACCOUNT_DEACTIVATED_DETAIL = "This account has been deactivated."
_INVALID_REFRESH_TOKEN_DETAIL = "The refresh token is invalid, revoked, or expired."


def _client_ip(request: Request) -> str | None:
    """Return the caller's IP, or `None` if it isn't a real IP address.

    `sessions.ip_address` is a Postgres `INET` column, so anything that
    doesn't parse as an IPv4/IPv6 address (e.g. the test client's literal
    `"testclient"` host, or a malformed/hostname value from an
    unconventional proxy) must be dropped rather than sent to asyncpg,
    which raises a hard `DataError` for a non-IP value instead of
    coercing it.
    """

    host = request.client.host if request.client else None
    if host is None:
        return None
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return None
    return host


async def _parse_body[T: BaseModel](request: Request, model: type[T]) -> T:
    """Parse and validate the raw JSON request body against `model`.

    Any structural failure (invalid JSON, missing/mistyped fields) raises
    `HTTPException(400, ...)` — the frozen contract's "Malformed body"
    outcome for these endpoints — rather than letting FastAPI's automatic
    body-parameter validation raise `RequestValidationError` (which the
    globally installed handler renders as `422`).
    """

    try:
        raw = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Request body is not valid JSON."
        ) from None

    try:
        return model.model_validate(raw)
    except ValidationError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body is missing or has malformed fields.",
        ) from None


@router.post("/login", response_model=LoginResponse)
async def login(request: Request, db: _DbSession, settings: _SettingsDep) -> LoginResponse:
    """Authenticate and issue a new session (F10).

    Status mapping is exactly the frozen contract: `200` on success,
    `400` malformed body, `401` bad credentials (uniform, non-field-
    revealing — F11), `403` deactivated account. The ADR-0009
    `must_change_password` compensating control (see
    `app.services.auth.MustChangePasswordError` /
    `app.core.errors.must_change_password_error_handler`) also renders as
    `403`, but with a distinct `problem+json` `type` — a documented,
    additive contract gap (see the T15 CONTRACT-GAP notice), not a
    silent extension of the frozen `403 -> account deactivated` meaning.
    """

    body = await _parse_body(request, LoginRequest)

    try:
        result = await authenticate_and_login(
            db,
            email=body.email,
            password=body.password,
            settings=settings,
            user_agent=request.headers.get("user-agent"),
            ip_address=_client_ip(request),
        )
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_CREDENTIALS_DETAIL
        ) from None
    except AccountDeactivatedError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_ACCOUNT_DEACTIVATED_DETAIL
        ) from None
    except MustChangePasswordError:
        # Re-raised as-is: `app.core.errors.must_change_password_error_handler`
        # is registered globally and renders the distinct 403 problem+json shape.
        raise

    return LoginResponse(
        access_token=result.access_token,
        token_type="Bearer",
        expires_in=result.expires_in,
        refresh_token=result.refresh_token,
        user=UserOut.from_user(result.user),
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(request: Request, db: _DbSession, settings: _SettingsDep) -> RefreshResponse:
    """Exchange a refresh token for a fresh access token, rotating it (F12).

    Status mapping: `200` success, `400` malformed body, `401` invalid /
    revoked / expired refresh token (uniform — F12).
    """

    body = await _parse_body(request, RefreshRequest)

    try:
        result = await refresh_session(db, raw_refresh_token=body.refresh_token, settings=settings)
    except InvalidRefreshTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_REFRESH_TOKEN_DETAIL
        ) from None

    return RefreshResponse(
        access_token=result.access_token,
        token_type="Bearer",
        expires_in=result.expires_in,
        refresh_token=result.refresh_token,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(current: _CurrentUser, db: _DbSession) -> Response:
    """Revoke the caller's *current* session only (F14).

    Any other request body is accepted and ignored (the contract's request
    shape is always `{}`) — this endpoint takes no parsed body. Reuses
    `app.services.sessions.revoke_session`, which is already idempotent on
    an already-revoked session, matching the contract's "re-revoke -> 204"
    note; note that in practice a *repeat* call authenticated with the
    very same (now-revoked) access token instead fails `require_auth`
    with `401`, since every protected route — including this one —
    re-validates the session on every call (ADR-0006). Idempotency here
    means "revoking an already-revoked session id is a no-op success",
    not "the exact same request replays safely once its own credential is
    dead", which no bearer-token-scoped endpoint can offer.
    """

    await revoke_session(db, session_id=current.session_id, user_id=current.user_id)

    # Commit durably *before* busting the cache — mirrors
    # `app.api.sessions.delete_session`'s reasoning exactly: without an
    # explicit commit here, a concurrent request (this instance or
    # another) could cache-miss, read Postgres before this transaction's
    # commit is visible, and re-cache "active" for up to the cache TTL.
    await db.commit()
    await invalidate_session_cache(get_redis_client(), current.session_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
