"""`/v1/invites*` — System Admin invite issuance and lifecycle (T13, frozen contract).

Four endpoints:

- `POST /v1/invites` (Bearer, `system_admin` only): issues a single-use,
  7-day invite for an email and sends it via `EmailService` (T11)
  *synchronously* — unlike the password-reset flow (T16), this contract
  does not require non-enumeration (the caller is an authenticated System
  Admin, so there is no timing side-channel to defend against), so the
  email send happens inline and a delivery failure is surfaced as a fail-
  loud `502` to the caller (frozen contract). `409` if the email already
  belongs a registered user; `422` if the email is malformed.
- `GET /v1/invites/{token}` (public; the token is the credential): `200`
  with the locked email + expiry if the token is currently redeemable
  (`pending`, not yet expired), `410` uniformly otherwise (unknown token,
  already accepted, revoked, or expired) — does not consume the token.
- `POST /v1/invites/{id}/resend` (Bearer, `system_admin` only): rotates the
  token (the prior one becomes unresolvable -> `410`) and re-sends the
  invite email; `409` if the invite is not currently `pending`.
- `DELETE /v1/invites/{id}` (Bearer, `system_admin` only): revokes an
  unused invite; idempotent (`204` even if already revoked), `409` if the
  invite was already redeemed (`accepted`).
- `GET /v1/invites` (Bearer, `system_admin` only, T43): cursor-paginated
  browse of every invite ever issued, optionally narrowed by
  `?status=pending|accepted|revoked|expired`; returns
  `{ items, next_cursor }` (empty list, not an error, when nothing
  matches). Reuses the T07 keyset pagination utility over
  `(created_at, id)` for consistency with ADR-0003.

Every body is parsed via `app.core.request_body.parse_body` (not a typed
FastAPI body parameter) so a malformed body maps to the contract's `400`
rather than FastAPI's default `422` — see that module's docstring. The
raw invite token and the invitee's email are never logged by this module
(only invite ids and booleans — content-free audit events, R24).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.deps import AuthenticatedUser, require_system_admin
from app.core.email_validation import is_valid_email_format
from app.core.pagination import PaginationError, decode_cursor, resolve_limit
from app.core.request_body import openapi_request_body, parse_body
from app.db.session import get_db_session
from app.models.invite import Invite, InviteStatus
from app.schemas.invites import (
    InviteCreateRequest,
    InviteListItem,
    InviteListResponse,
    InviteResendRequest,
    InviteResendResponse,
    InviteResponse,
    InviteTokenValidationResponse,
)
from app.services.email import EmailDeliveryError, EmailService, get_email_service
from app.services.invites import (
    create_invite,
    find_valid_invite_by_token,
    is_email_registered,
    list_invites,
    revoke_invite,
    rotate_invite_token,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/invites", tags=["invites"])

_STALE_TOKEN_DETAIL = "Invite is expired, already used, or no longer valid."
_INVALID_EMAIL_DETAIL = "Must be a valid email address."
_ALREADY_REGISTERED_DETAIL = "This email address already belongs to a registered user."
_EMAIL_UNREACHABLE_DETAIL = "The invite email could not be delivered. Please try again."
_NOT_FOUND_DETAIL = "No such invite."
_NOT_PENDING_DETAIL = "Invite is not in a pending (resendable) state."
_ALREADY_USED_DETAIL = "Invite has already been redeemed and cannot be revoked."
_INVALID_STATUS_DETAIL = "status must be one of: pending, accepted, revoked, expired."

_VALID_LIST_STATUS_FILTERS = {"pending", "accepted", "revoked", "expired"}

_SystemAdmin = Annotated[AuthenticatedUser, Depends(require_system_admin)]
_DbSession = Annotated[AsyncSession, Depends(get_db_session)]
_AppSettings = Annotated[Settings, Depends(get_settings)]
_Email = Annotated[EmailService, Depends(get_email_service)]
_Payload = Annotated[dict[str, Any], Body(...)]


def _parse_list_limit(raw: str | None) -> int:
    """Parse `limit`, raising `PaginationError` (-> frozen `400`) on failure.

    Accepted as a raw string (not a typed FastAPI `int` query parameter)
    for the same reason as `app.api.channels._parse_pagination`: FastAPI's
    automatic coercion would raise its own `422` on a non-numeric value,
    but the contract calls for `400` on any invalid pagination parameter.
    """

    if raw is None:
        return resolve_limit(None)
    try:
        value = int(raw)
    except ValueError:
        raise PaginationError(field="limit", detail="limit must be a positive integer") from None
    return resolve_limit(value)


async def _get_invite_or_404(db: AsyncSession, invite_id: UUID) -> Invite:
    invite = await db.get(Invite, invite_id)
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)
    return invite


@router.post(
    "",
    response_model=InviteResponse,
    status_code=status.HTTP_201_CREATED,
    openapi_extra=openapi_request_body(InviteCreateRequest, {"email": "bob@co.com"}),
)
async def issue_invite(
    payload: _Payload,
    admin: _SystemAdmin,
    db: _DbSession,
    settings: _AppSettings,
    email_service: _Email,
) -> InviteResponse:
    body = parse_body(InviteCreateRequest, payload)
    email = body.email.strip()

    if not is_valid_email_format(email):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=_INVALID_EMAIL_DETAIL
        )

    if await is_email_registered(db, email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_ALREADY_REGISTERED_DETAIL)

    created = await create_invite(db, email=email, created_by=admin.user_id)
    invite_link = f"{settings.invite_url_base}?token={created.raw_token}"

    try:
        await email_service.send_invite_email(
            to_email=email, invite_link=invite_link, expires_at=created.invite.expires_at
        )
    except EmailDeliveryError:
        # Fail loudly: never leave a dangling, never-delivered invite row
        # behind — the whole issuance rolls back so the admin can retry
        # cleanly (frozen contract: `502 | Email delivery unreachable —
        # fail loudly`).
        await db.rollback()
        logger.error(
            "invite email delivery failed; issuance rolled back",
            extra={"issued_by": str(admin.user_id)},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=_EMAIL_UNREACHABLE_DETAIL
        ) from None

    await db.commit()

    # Content-free audit event (R45): id + issuer only, never the email
    # address or the raw token. Logged only after a successful commit —
    # see `app.services.invites.create_invite` for why.
    logger.info(
        "invite issued",
        extra={"invite_id": str(created.invite.id), "issued_by": str(admin.user_id)},
    )

    return InviteResponse.from_invite(created.invite)


@router.get(
    "/{token}",
    response_model=InviteTokenValidationResponse,
    status_code=status.HTTP_200_OK,
)
async def validate_invite_token(token: str, db: _DbSession) -> InviteTokenValidationResponse:
    invite = await find_valid_invite_by_token(db, token)
    if invite is None:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=_STALE_TOKEN_DETAIL)

    return InviteTokenValidationResponse(email=invite.email, expiry=invite.expires_at)


@router.post(
    "/{invite_id}/resend",
    response_model=InviteResendResponse,
    status_code=status.HTTP_200_OK,
    openapi_extra=openapi_request_body(InviteResendRequest, {}),
)
async def resend_invite(
    invite_id: UUID,
    payload: _Payload,
    admin: _SystemAdmin,
    db: _DbSession,
    settings: _AppSettings,
    email_service: _Email,
) -> InviteResendResponse:
    # Frozen contract body is `{}` — validated for shape only (must be a
    # JSON object) via the `_Payload` dependency; no fields to parse.
    del payload

    invite = await _get_invite_or_404(db, invite_id)
    if invite.status is not InviteStatus.PENDING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_NOT_PENDING_DETAIL)

    raw_token = await rotate_invite_token(db, invite)
    invite_link = f"{settings.invite_url_base}?token={raw_token}"

    try:
        await email_service.send_invite_email(
            to_email=invite.email, invite_link=invite_link, expires_at=invite.expires_at
        )
    except EmailDeliveryError:
        # Roll back the rotation too: the prior token must remain valid if
        # the new one could never be delivered (fail-loud, no silently
        # broken invite).
        await db.rollback()
        logger.error(
            "invite resend email delivery failed; rotation rolled back",
            extra={"invite_id": str(invite_id), "issued_by": str(admin.user_id)},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=_EMAIL_UNREACHABLE_DETAIL
        ) from None

    await db.commit()

    logger.info(
        "invite resent",
        extra={"invite_id": str(invite_id), "issued_by": str(admin.user_id)},
    )

    return InviteResendResponse.from_invite(invite)


@router.get("", response_model=InviteListResponse, status_code=status.HTTP_200_OK)
async def list_invites_route(
    admin: _SystemAdmin,
    db: _DbSession,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[str | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
) -> InviteListResponse:
    """`GET /v1/invites` (T43): paginated invite browse, admin-only.

    Never logs (this route does not log at all — a read has nothing to
    audit) and never selects the raw token; see `InviteListItem`.
    """

    if status_filter is not None and status_filter not in _VALID_LIST_STATUS_FILTERS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_INVALID_STATUS_DETAIL)

    resolved_limit = _parse_list_limit(limit)
    cursor_key = decode_cursor(cursor) if cursor else None

    page = await list_invites(
        db,
        status_filter=status_filter,  # type: ignore[arg-type]
        limit=resolved_limit,
        cursor=cursor_key,
    )

    return InviteListResponse(
        items=[InviteListItem.from_invite(invite) for invite in page.items],
        next_cursor=page.next_cursor,
    )


@router.delete("/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite_route(invite_id: UUID, admin: _SystemAdmin, db: _DbSession) -> Response:
    invite = await _get_invite_or_404(db, invite_id)

    if invite.status is InviteStatus.ACCEPTED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_ALREADY_USED_DETAIL)

    already_revoked = invite.status is InviteStatus.REVOKED
    revoke_invite(invite)
    await db.commit()

    if not already_revoked:
        # Content-free audit event (R45): id + issuer only, never the
        # email address or the raw token.
        logger.info(
            "invite revoked",
            extra={"invite_id": str(invite_id), "revoked_by": str(admin.user_id)},
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
