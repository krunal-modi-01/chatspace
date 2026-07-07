"""`/v1/auth/sessions` — list and revoke sessions (frozen contract).

`POST /v1/auth/login`, `/v1/auth/refresh`, and `POST /v1/auth/logout` are
explicitly out of scope for T10 (T15) — this module only covers the two
endpoints that exist purely to exercise the session store + `require_auth`
end-to-end: listing a caller's own active sessions and revoking one of
them by id.
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthenticatedUser, require_auth
from app.db.redis import get_redis_client
from app.db.session import get_db_session
from app.schemas.sessions import SessionListResponse, SessionSummary
from app.services.session_revocation import invalidate_session_cache
from app.services.sessions import RevokeOutcome, list_active_sessions_for_user, revoke_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth-sessions"])

_CurrentUser = Annotated[AuthenticatedUser, Depends(require_auth)]
_DbSession = Annotated[AsyncSession, Depends(get_db_session)]


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    current: _CurrentUser,
    db: _DbSession,
) -> SessionListResponse:
    """List every active session belonging to the caller.

    Never includes token material (`refresh_token`/`refresh_token_hash`) —
    see `app.schemas.sessions.SessionSummary`.
    """

    sessions = await list_active_sessions_for_user(db, current.user_id)
    items = [
        SessionSummary(
            session_id=session.id,
            created_at=session.issued_at,
            last_seen_at=session.last_used_at,
            device_label=session.user_agent,
            current=session.id == current.session_id,
        )
        for session in sessions
    ]
    return SessionListResponse(items=items)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: UUID,
    current: _CurrentUser,
    db: _DbSession,
) -> Response:
    """Revoke a session owned by the caller.

    Status mapping is exactly the frozen contract table: `204` revoked
    (idempotent — an already-revoked owned session also returns `204`),
    `403` if `session_id` belongs to another user, `404` if no such
    session exists at all.
    """

    outcome = await revoke_session(db, session_id=session_id, user_id=current.user_id)

    if outcome is RevokeOutcome.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No such session for this user.",
        )
    if outcome is RevokeOutcome.FORBIDDEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This session belongs to another user.",
        )

    # Commit the revoke durably *before* busting the cache. `revoke_session`
    # only flushes (visible within this transaction, not to others);
    # without an explicit commit here, `get_db_session`'s teardown commit
    # would only land *after* `invalidate_session_cache` returns, leaving a
    # window where a concurrent reader (or a second app instance) can
    # cache-miss, read Postgres before this commit is visible, see the
    # session as still active, and re-cache "active" for up to the cache's
    # TTL — so a revoked session would keep authenticating (violates
    # ADR-0006's "revoked fails within one request" guarantee).
    await db.commit()

    # Bust the Redis revocation cache immediately so the revoked session
    # fails `require_auth` within the very next request, rather than
    # waiting for the cache TTL to lapse (ADR-0006).
    await invalidate_session_cache(get_redis_client(), session_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
