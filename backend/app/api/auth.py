"""`POST /v1/auth/login`, `/refresh`, `/logout`, `/register` (T14, T15, ADR-0006, ADR-0009).

`GET`/`DELETE /v1/auth/sessions` live in `app.api.sessions` (T10) and are
not touched here.

Request bodies for `login`/`refresh`/`register` are parsed manually (raw
JSON -> `model_validate`) rather than as FastAPI body-parameter types, so
a malformed body maps to the frozen contract's `400` rather than the
framework-default `422` that the globally installed
`RequestValidationError` handler produces (`app.core.errors`) — that `422`
path is reserved by this contract for field-content validation failures
(e.g. password policy, username length, blank names). `logout` takes no
parsed body at all (the contract's `{}` is accepted-and-ignored).

`POST /v1/auth/register` (T14) redeems a `pending`/unexpired invite
(`app.services.invites.find_valid_invite_by_token`, T13) and creates the
invited user with their email locked to the invite's address — there is
no invite-less registration path. Invite-validation, the `users` INSERT,
and the invite's `pending -> accepted` transition (`app.services.invites
.redeem_invite`) all happen in one transaction (`app.services
.registration.build_registered_user`) so a duplicate-username/email
failure never consumes the invite.
"""

from __future__ import annotations

import ipaddress
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.deps import AuthenticatedUser, require_auth
from app.core.password_policy import enforce_password_policy
from app.core.request_body import openapi_request_body
from app.db.redis import get_redis_client
from app.db.session import get_db_session
from app.schemas.auth import LoginRequest, LoginResponse, RefreshRequest, RefreshResponse
from app.schemas.auth_register import RegisteredUser, RegisterRequest
from app.schemas.user import UserOut
from app.services.auth import (
    AccountDeactivatedError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    MustChangePasswordError,
    authenticate_and_login,
    refresh_session,
)
from app.services.invites import find_valid_invite_by_token, redeem_invite
from app.services.registration import (
    DuplicateIdentityError,
    build_registered_user,
    check_identity_not_taken,
    validate_registration_fields,
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
_STALE_INVITE_DETAIL = "Invite token is expired, already used, or no longer valid."
_DUPLICATE_IDENTITY_DETAIL = "This username or email is already registered."

# Postgres SQLSTATE for `unique_violation` — same race-safe backstop
# pattern as `app.services.bootstrap._is_unique_violation`.
_UNIQUE_VIOLATION_SQLSTATE = "23505"


def _is_unique_violation(exc: IntegrityError) -> bool:
    sqlstate = getattr(exc.orig, "sqlstate", None)
    return sqlstate == _UNIQUE_VIOLATION_SQLSTATE


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


@router.post(
    "/login",
    response_model=LoginResponse,
    openapi_extra=openapi_request_body(
        LoginRequest, {"email": "alice@co.com", "password": "<password>"}
    ),
)
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


@router.post(
    "/refresh",
    response_model=RefreshResponse,
    openapi_extra=openapi_request_body(RefreshRequest, {"refresh_token": "<refresh_token>"}),
)
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


@router.post(
    "/register",
    response_model=RegisteredUser,
    status_code=status.HTTP_201_CREATED,
    openapi_extra=openapi_request_body(
        RegisterRequest,
        {
            "invite_token": "<invite_token>",
            "username": "alice",
            "first_name": "Alice",
            "last_name": "Ng",
            "password": "<password>",
            "avatar_url": None,
        },
    ),
)
async def register(request: Request, db: _DbSession) -> RegisteredUser:
    """Redeem a pending, unexpired invite and create the invited user (F5/F6).

    There is no invite-less registration path — `invite_token` is
    required and validated via
    `app.services.invites.find_valid_invite_by_token` (T13). Status
    mapping is exactly the frozen contract: `201` on success, `400`
    malformed body, `409` duplicate username/email (case-insensitive),
    `410` invite expired/used/revoked (F7), `422` password-policy or
    field-content validation failure.

    Invite-validation, the `users` INSERT, and the invite's
    `pending -> accepted` transition happen in one transaction: a
    duplicate-identity `IntegrityError` at flush time rolls both back, so
    a failed registration never consumes the invite (the frozen data
    model's transactional-integrity requirement).
    """

    body = await _parse_body(request, RegisterRequest)

    invite = await find_valid_invite_by_token(db, body.invite_token)
    if invite is None:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=_STALE_INVITE_DETAIL)

    # Password policy runs before any DB write and before the duplicate
    # check: a non-compliant password must never consume the invite or
    # even hint at whether the username/email is already taken.
    enforce_password_policy(body.password)

    # `RegistrationFieldError` (username length / blank name) is left to
    # propagate uncaught: `app.core.errors.registration_field_error_handler`
    # is registered globally and renders the frozen 422 problem+json shape
    # with a field-attributed `errors[]` array, mirroring
    # `enforce_password_policy`'s `PasswordPolicyError` just above.
    normalized_username = validate_registration_fields(
        username=body.username, first_name=body.first_name, last_name=body.last_name
    )

    try:
        await check_identity_not_taken(db, username=normalized_username, email=invite.email)
    except DuplicateIdentityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_DUPLICATE_IDENTITY_DETAIL
        ) from None

    user = build_registered_user(
        invite=invite,
        username=normalized_username,
        first_name=body.first_name,
        last_name=body.last_name,
        password=body.password,
        avatar_url=body.avatar_url,
    )
    db.add(user)
    redeem_invite(invite)

    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if not _is_unique_violation(exc):
            raise
        # Race-safe backstop: a concurrent registration won the unique
        # index between our pre-check and this flush. The invite remains
        # `pending` (this whole transaction rolled back), so the caller
        # can retry with a different identity using the same token.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_DUPLICATE_IDENTITY_DETAIL
        ) from None

    await db.commit()

    logger.info(
        "user registered via invite redemption",
        extra={"user_id": str(user.id), "invite_id": str(invite.id)},
    )

    return RegisteredUser.from_user(user)
