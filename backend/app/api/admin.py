"""`/v1/admin/*` — System Admin user directory + deactivate/reactivate (T44).

Three endpoints, every one behind `require_system_admin`:

- `GET /v1/admin/users` — cursor-paginated, searchable (`q` over
  first/last name, username, email, case-insensitive) user directory,
  including both active and deactivated users (F72). Reuses the T07
  keyset pagination utility, same `{ items, next_cursor }` envelope as
  `GET /v1/invites` (T43). Never returns `hashed_password` or any other
  secret (R55).
- `POST /v1/admin/users/{id}/deactivate` — the never-built T20 logic:
  sets `is_active=false`, revokes every active session for the target
  immediately (T10), runs channel succession for every channel where the
  target was the sole admin (F36/R51, `app.services.channels.
  run_sole_admin_succession`), and refuses to deactivate the last active
  System Admin (`409`, F27). Idempotent — an already-inactive target
  returns `200` with no further effect.
- `POST /v1/admin/users/{id}/reactivate` — sets `is_active=true`; does
  **not** restore any prior session (F26). Idempotent.

Frozen contract for deactivate/reactivate (`api-contract.md` lines
587-618): request body `{}`, response `{ id, is_active }`. `GET
/v1/admin/users`'s shape follows the T44 task-breakdown spec (PRD v2
§11/R55, FS F72) — this endpoint is not yet reflected in
`docs/spec/chatspace-v1-api-contract.md`, which the api-reviewer should
add for consumer-doc completeness (flagged, not a behavior gap).

Deactivate/reactivate bodies are parsed via `app.core.request_body.
parse_body` (not a typed FastAPI body parameter), mirroring
`app.api.invites.resend_invite`'s `{}`-body pattern, so a malformed body
maps to the contract's `400`. Content-free audit logging throughout:
never the target's name/email/PII, only user ids and counts (R24-style).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthenticatedUser, require_system_admin
from app.core.pagination import PaginationError, decode_cursor, resolve_limit
from app.core.request_body import openapi_request_body, parse_body
from app.db.redis import get_redis_client
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.admin import (
    AdminActionRequest,
    AdminUserActionResponse,
    AdminUserListItem,
    AdminUserListResponse,
)
from app.services.admin_users import (
    DeactivateOutcome,
    deactivate_user,
    list_admin_users,
    reactivate_user,
)
from app.services.session_revocation import invalidate_session_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

_NOT_FOUND_DETAIL = "No such user."
_INVALID_STATUS_DETAIL = "status must be one of: active, inactive."
_LAST_ADMIN_DETAIL = "Cannot deactivate the last active System Admin."

_VALID_USER_STATUS_FILTERS = {"active", "inactive"}

_SystemAdmin = Annotated[AuthenticatedUser, Depends(require_system_admin)]
_DbSession = Annotated[AsyncSession, Depends(get_db_session)]
_Payload = Annotated[dict[str, Any], Body(...)]


def _parse_limit(raw: str | None) -> int:
    """Parse `limit`, raising `PaginationError` (-> frozen `400`) on failure.

    Mirrors `app.api.invites._parse_list_limit` exactly — accepted as a
    raw string so a non-numeric value maps to the contract's `400` rather
    than FastAPI's automatic `422`.
    """

    if raw is None:
        return resolve_limit(None)
    try:
        value = int(raw)
    except ValueError:
        raise PaginationError(field="limit", detail="limit must be a positive integer") from None
    return resolve_limit(value)


async def _get_user_or_404(db: AsyncSession, user_id: UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)
    return user


@router.get("/users", response_model=AdminUserListResponse, status_code=status.HTTP_200_OK)
async def list_users_route(
    admin: _SystemAdmin,
    db: _DbSession,
    q: Annotated[str | None, Query()] = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[str | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
) -> AdminUserListResponse:
    if status_filter is not None and status_filter not in _VALID_USER_STATUS_FILTERS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_INVALID_STATUS_DETAIL)

    resolved_limit = _parse_limit(limit)
    cursor_key = decode_cursor(cursor) if cursor else None

    page = await list_admin_users(
        db,
        q=q,
        status_filter=status_filter,  # type: ignore[arg-type]
        limit=resolved_limit,
        cursor=cursor_key,
    )

    return AdminUserListResponse(
        items=[AdminUserListItem.from_user(user) for user in page.items],
        next_cursor=page.next_cursor,
    )


@router.post(
    "/users/{user_id}/deactivate",
    response_model=AdminUserActionResponse,
    status_code=status.HTTP_200_OK,
    openapi_extra=openapi_request_body(AdminActionRequest, {}),
)
async def deactivate_user_route(
    user_id: UUID,
    payload: _Payload,
    admin: _SystemAdmin,
    db: _DbSession,
) -> AdminUserActionResponse:
    # Frozen contract body is `{}` — validated for shape only (must be a
    # JSON object) via `_Payload`; no fields to parse.
    parse_body(AdminActionRequest, payload)

    target = await _get_user_or_404(db, user_id)
    result = await deactivate_user(db, target=target)

    if result.outcome is DeactivateOutcome.LAST_ACTIVE_SYSTEM_ADMIN:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_LAST_ADMIN_DETAIL)

    await db.commit()

    if result.outcome is DeactivateOutcome.DEACTIVATED:
        redis = get_redis_client()
        for session_id in result.revoked_session_ids:
            await invalidate_session_cache(redis, session_id)

        # Content-free audit event (R24-style): ids/counts only, never the
        # target's name/email.
        logger.info(
            "user deactivated",
            extra={
                "user_id": str(user_id),
                "deactivated_by": str(admin.user_id),
                "revoked_session_count": len(result.revoked_session_ids),
                "succession_channel_count": len(result.promoted_channel_ids),
            },
        )

    return AdminUserActionResponse(id=target.id, is_active=target.is_active)


@router.post(
    "/users/{user_id}/reactivate",
    response_model=AdminUserActionResponse,
    status_code=status.HTTP_200_OK,
    openapi_extra=openapi_request_body(AdminActionRequest, {}),
)
async def reactivate_user_route(
    user_id: UUID,
    payload: _Payload,
    admin: _SystemAdmin,
    db: _DbSession,
) -> AdminUserActionResponse:
    parse_body(AdminActionRequest, payload)

    target = await _get_user_or_404(db, user_id)
    changed = reactivate_user(target)
    # Capture the response fields *before* the commit/rollback below: a
    # `rollback()` expires `target`, so touching its attributes afterwards
    # would trigger a lazy reload (fresh pool checkout + pre-ping) outside
    # the async greenlet -> `MissingGreenlet`. `is_active` is `True` in
    # both branches (reactivate_user leaves the user active).
    response = AdminUserActionResponse(id=target.id, is_active=target.is_active)

    if changed:
        await db.commit()
        logger.info(
            "user reactivated",
            extra={"user_id": str(user_id), "reactivated_by": str(admin.user_id)},
        )
    else:
        await db.rollback()

    return response
