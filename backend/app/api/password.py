"""`/v1/auth/password*` — password reset and password change (T16, frozen contract).

Three endpoints:

- `POST /v1/auth/password-reset` (public, non-enumerating F15/F17):
  uniform `202` whether or not the email matches an account. On a match,
  issues a single-use 1-hour reset token (sweeping any earlier one, F17)
  and emails it via `EmailService` (T11) — a delivery failure still
  returns the uniform `202` and is instead surfaced as a server-side
  alert (`logger.error`), never a different client-visible outcome.
- `POST /v1/auth/password-reset/confirm` (public; the reset token is the
  credential): `410` on a stale/used/unknown/superseded token (F17),
  `422` on a new password that fails policy (F23), otherwise sets the
  password and revokes every one of the user's active sessions (F16 —
  there is no initiating session to keep, since this flow is
  unauthenticated).
- `POST /v1/auth/password/change` (Bearer): `401` if the current password
  is wrong (password left unchanged), `422` on policy failure, otherwise
  sets the password, keeps the initiating session alive, and revokes
  every other active session (F22).

Every body is parsed via `app.core.request_body.parse_body` (not a typed
FastAPI body parameter) so a malformed body maps to the contract's `400`
rather than FastAPI's default `422` — see that module's docstring. The
raw reset token, current/new passwords, and the requester's email are
never logged by this module.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.deps import AuthenticatedUser, require_auth
from app.core.password_policy import enforce_password_policy
from app.core.request_body import parse_body
from app.core.security import hash_password, verify_password
from app.db.redis import get_redis_client
from app.db.session import get_db_session, get_sessionmaker
from app.models.user import User
from app.schemas.auth_password import (
    PasswordChangeRequest,
    PasswordResetAcceptedResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
)
from app.services.email import EmailDeliveryError, EmailService, get_email_service
from app.services.password_reset import (
    create_password_reset_token,
    find_valid_reset_token,
    mark_reset_token_used,
)
from app.services.session_revocation import invalidate_session_cache
from app.services.sessions import revoke_sessions_for_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth-password"])

# Verbatim uniform message, frozen contract (F15) — identical whether or
# not the requested email matches an account.
_UNIFORM_RESET_MESSAGE = "If an account exists for that email, a reset link has been sent."

_STALE_TOKEN_DETAIL = "Reset token is expired, already used, or no longer valid."
_WRONG_CURRENT_PASSWORD_DETAIL = "Current password is incorrect."

_CurrentUser = Annotated[AuthenticatedUser, Depends(require_auth)]
_DbSession = Annotated[AsyncSession, Depends(get_db_session)]
_AppSettings = Annotated[Settings, Depends(get_settings)]
_Email = Annotated[EmailService, Depends(get_email_service)]
_Payload = Annotated[dict[str, Any], Body(...)]


async def _get_user_by_email(db: AsyncSession, email: str) -> User | None:
    """Case-insensitive lookup, mirroring `uq_users_email_lower`."""

    result = await db.execute(select(User).where(func.lower(User.email) == email.strip().lower()))
    return result.scalar_one_or_none()


async def _process_password_reset_request(
    *, email: str, settings: Settings, email_service: EmailService
) -> None:
    """Background job: look up the account, issue a token, and email it.

    Runs entirely *after* the uniform `202` has already been sent to the
    caller (F15) — this is the fix for the HIGH-severity timing
    side-channel found in security review: previously, the "account
    exists" branch did a DB write + commit + a synchronous, retried SMTP
    send *before* returning, while the "no such account" branch returned
    after a single `SELECT`. That wall-clock gap let an attacker
    enumerate valid emails by timing the response. Now both branches of
    the request handler do the same negligible amount of work (parse the
    body, schedule this task) before returning `202`, so response timing
    carries no signal about whether `email` matched an account.

    This function is invoked via `BackgroundTasks`, which run *after* the
    response has been sent — by which point the request-scoped session
    from `get_db_session` has already been committed/rolled back and
    closed. It therefore opens its **own** `AsyncSession` from the
    process-wide `get_sessionmaker()` factory (same pattern as
    `get_db_session`, just managed manually since there is no request to
    scope it to) rather than reusing the injected `db` dependency.

    The DB unit of work (lookup + token issuance + commit) is closed out
    and the session released back to the pool *before* the SMTP call
    runs, so a slow/retried email send never holds a pooled DB connection
    idle.
    """

    session_factory = get_sessionmaker()
    reset_link: str | None = None
    expires_at: datetime | None = None
    recipient_email: str | None = None
    user_id: UUID | None = None

    async with session_factory() as db:
        try:
            user = await _get_user_by_email(db, email)

            # Content-free audit event (F15): records that a reset was
            # requested and whether it matched an account, but never the
            # raw email address itself — the JSON log formatter would
            # redact an "email" key anyway (defense in depth), but this
            # module never passes it in the first place.
            logger.info(
                "password reset requested",
                extra={
                    "account_found": user is not None,
                    "user_id": str(user.id) if user is not None else None,
                },
            )

            if user is not None:
                created = await create_password_reset_token(db, user_id=user.id)
                # Commit the token durably *before* attempting delivery: a
                # slow or failing SMTP send must never roll back the
                # already-issued token.
                await db.commit()

                reset_link = f"{settings.password_reset_url_base}?token={created.raw_token}"
                expires_at = created.token.expires_at
                recipient_email = user.email
                user_id = user.id
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()

    if reset_link is None or expires_at is None or recipient_email is None:
        return

    try:
        await email_service.send_password_reset_email(
            to_email=recipient_email,
            reset_link=reset_link,
            expires_at=expires_at,
        )
    except EmailDeliveryError:
        # Fail-loud internally, uniform externally (F15/ADR-0010): the
        # requester already received the uniform 202 — this is a
        # server-side alert only, never a different client-visible
        # outcome (which would re-introduce an enumeration signal).
        logger.error(
            "password reset email delivery failed; uniform response preserved",
            extra={"user_id": str(user_id)},
        )


@router.post(
    "/password-reset",
    response_model=PasswordResetAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_password_reset(
    payload: _Payload,
    background_tasks: BackgroundTasks,
    settings: _AppSettings,
    email_service: _Email,
) -> PasswordResetAcceptedResponse:
    body = parse_body(PasswordResetRequest, payload)

    # Timing fix (HIGH, security review — F15 non-enumeration): the
    # entire account-dependent sequence (user lookup, token issuance, and
    # the SMTP send) is deferred to `_process_password_reset_request`,
    # scheduled as a `BackgroundTasks` job that FastAPI runs *after* this
    # response has been sent. No DB or SMTP round-trip happens before
    # returning below, so this handler does the same negligible amount of
    # work regardless of whether `body.email` matches an account —
    # response latency carries no enumeration signal. See that function's
    # docstring for why it must open its own DB session rather than
    # reuse a request-scoped one.
    background_tasks.add_task(
        _process_password_reset_request,
        email=body.email,
        settings=settings,
        email_service=email_service,
    )

    return PasswordResetAcceptedResponse(message=_UNIFORM_RESET_MESSAGE)


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_password_reset(payload: _Payload, db: _DbSession) -> Response:
    body = parse_body(PasswordResetConfirmRequest, payload)

    token = await find_valid_reset_token(db, body.reset_token)
    if token is None:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=_STALE_TOKEN_DETAIL)

    # Policy check runs *before* consuming the token: a policy failure
    # (422) must not burn the single-use token, so the requester can
    # retry with a compliant password using the same still-valid link.
    enforce_password_policy(body.new_password, field_name="new_password")

    user = await db.get(User, token.user_id)
    if user is None:
        # The user row was deleted (FK CASCADE) between issue and confirm
        # — treat identically to any other invalid token rather than
        # leaking that the token itself was once well-formed.
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=_STALE_TOKEN_DETAIL)

    mark_reset_token_used(token)
    user.hashed_password = hash_password(body.new_password)
    # T42/ADR-0011: proving control of the reset token (mailed, single-use)
    # is a stronger bar than knowing the original temp/bootstrap password,
    # so successfully completing this flow also clears any forced
    # password-change requirement — this is the only exit path for an
    # account with must_change_password=true (see ADR-0009/ADR-0011).
    user.must_change_password = False
    # F16: every one of the user's other active sessions is invalidated —
    # there is no initiating session to keep here (reset is unauthenticated).
    revoked_session_ids = await revoke_sessions_for_user(db, user_id=user.id)

    await db.commit()

    redis = get_redis_client()
    for session_id in revoked_session_ids:
        await invalidate_session_cache(redis, session_id)

    logger.info("password reset completed", extra={"user_id": str(user.id)})

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/password/change", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(payload: _Payload, current: _CurrentUser, db: _DbSession) -> Response:
    body = parse_body(PasswordChangeRequest, payload)

    user = await db.get(User, current.user_id)
    if user is None or not verify_password(body.current_password, user.hashed_password):
        # F22: password left unchanged, no session touched, current
        # password never logged.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_WRONG_CURRENT_PASSWORD_DETAIL,
        )

    enforce_password_policy(body.new_password, field_name="new_password")

    user.hashed_password = hash_password(body.new_password)
    # T42/ADR-0011: an authenticated session hitting this endpoint while
    # must_change_password is set has also proven the current password —
    # clear the flag so it does not block a future login.
    user.must_change_password = False
    # F22: keep the initiating session alive, revoke every other one.
    revoked_session_ids = await revoke_sessions_for_user(
        db, user_id=user.id, except_session_id=current.session_id
    )

    await db.commit()

    redis = get_redis_client()
    for session_id in revoked_session_ids:
        await invalidate_session_cache(redis, session_id)

    logger.info("password changed", extra={"user_id": str(user.id)})

    return Response(status_code=status.HTTP_204_NO_CONTENT)
