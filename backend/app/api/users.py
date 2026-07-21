"""`GET /v1/users/search` — workspace user-directory search (T73, F76/R59, ADR-0016).

Scoped, minimal-field directory read backing the channel member-picker
(F32/F33) and the DM "new message" picker (F46, ADR-0017). Auth: any
active user (`require_auth` — deliberately **not** admin-gated), unlike
the System-Admin-only `GET /v1/admin/users` (F72, `app.api.admin`), which
this endpoint must never be confused with: the response here is
`{ id, username, first_name, last_name, avatar_url }` and never
`email`/`is_active`/`last_seen`/`role` (a hard security acceptance
criterion — see `app.schemas.user_search.UserSearchItem`).

`q` matches `username`/`first_name`/`last_name`, case-insensitive, and
must be at least 1 non-whitespace character (frozen contract: "min length
1") — both a missing `q` and a whitespace-only `q` map to the contract's
`400`, mirroring how `_parse_limit` rejects a malformed `limit` as `400`
rather than FastAPI's automatic `422` (matches `app.api.admin`'s
`status_filter` validation style). Cursor pagination per ADR-0003 (default
`limit` 50, server maximum 100), reusing the T07 keyset pagination
utility's opaque cursor encode/decode — see `app.services.user_search`
for why the actual keyset predicate/order differs from the generic
`(created_at, id)` tuple helper. Deactivated users are excluded by
default; there is no "include deactivated" toggle on this endpoint (that
capability lives only behind `GET /v1/admin/users`).

Rate-limited as a general authenticated read
(`Depends(enforce_general_read_rate_limit)`, `RateLimitScope.GENERAL_READ`,
T73) — a `429` + `Retry-After` on the shared per-user bucket, same shape
as every other rate-limited route in this codebase.

Never logs: like `app.api.invites.list_invites_route` and
`app.api.admin.list_users_route`, a read has nothing to audit, and the
search term `q` may itself contain PII (a partial name) that must never
reach a log line.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthenticatedUser, require_auth
from app.core.pagination import PaginationError, decode_cursor, resolve_limit
from app.core.rate_limit_deps import enforce_general_read_rate_limit
from app.db.session import get_db_session
from app.schemas.user_search import UserSearchItem, UserSearchResponse
from app.services.user_search import search_users

router = APIRouter(prefix="/users", tags=["users"])

_MISSING_Q_DETAIL = "q is required and must be at least 1 character."

_CurrentUser = Annotated[AuthenticatedUser, Depends(require_auth)]
_DbSession = Annotated[AsyncSession, Depends(get_db_session)]
_RateLimitGuard = Annotated[None, Depends(enforce_general_read_rate_limit)]


def _parse_limit(raw: str | None) -> int:
    """Parse `limit`, raising `PaginationError` (-> frozen `400`) on failure.

    Mirrors `app.api.admin._parse_limit` / `app.api.invites
    ._parse_list_limit` exactly.
    """

    if raw is None:
        return resolve_limit(None)
    try:
        value = int(raw)
    except ValueError:
        raise PaginationError(field="limit", detail="limit must be a positive integer") from None
    return resolve_limit(value)


@router.get("/search", response_model=UserSearchResponse, status_code=status.HTTP_200_OK)
async def search_users_route(
    current: _CurrentUser,
    db: _DbSession,
    _rate_limit_guard: _RateLimitGuard,
    q: Annotated[str | None, Query()] = None,
    limit: Annotated[str | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
) -> UserSearchResponse:
    del current  # any active user is authorized; identity itself is not used

    stripped_q = q.strip() if q is not None else ""
    if not stripped_q:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_MISSING_Q_DETAIL)

    resolved_limit = _parse_limit(limit)
    cursor_key = decode_cursor(cursor) if cursor else None

    page = await search_users(db, q=stripped_q, limit=resolved_limit, cursor=cursor_key)

    return UserSearchResponse(
        items=[UserSearchItem.from_user(user) for user in page.items],
        next_cursor=page.next_cursor,
    )
