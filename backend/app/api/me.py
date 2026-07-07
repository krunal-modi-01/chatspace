"""`/v1/me` — own profile (frozen contract, T17).

`GET /v1/me` returns the caller's profile (F18); `PATCH /v1/me` updates
`first_name`/`last_name`/`avatar_url` only — `email`/`username` are
immutable (F19/F20). Never returns `hashed_password` (F18/R24):
`UserProfile.from_user` builds the response explicitly field-by-field,
never via a blanket ORM-to-schema dump.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthenticatedUser, require_auth
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.users import ProfileUpdateRequest, UserProfile
from app.services.profile import (
    EmptyNameError,
    ImmutableFieldChangeError,
    apply_profile_update,
    validate_profile_update,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["me"])

_CurrentUser = Annotated[AuthenticatedUser, Depends(require_auth)]
_DbSession = Annotated[AsyncSession, Depends(get_db_session)]


async def _load_current_user(db: AsyncSession, user_id: object) -> User:
    # `require_auth` already proved this user exists and is active for
    # this same request, but it does not hand back the loaded row (only
    # the id) — re-fetch here rather than re-deriving fields from the JWT.
    user = await db.get(User, user_id)
    if user is None:
        # Unreachable in practice (require_auth would already have raised
        # 401), but never surface an unhandled 500 for a caller whose
        # user row vanished between dependencies within the same request.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed. Provide a valid access token.",
        )
    return user


@router.get("/me", response_model=UserProfile)
async def get_me(current: _CurrentUser, db: _DbSession) -> UserProfile:
    """Return the caller's own profile (F18). Never includes the password hash."""

    user = await _load_current_user(db, current.user_id)
    return UserProfile.from_user(user)


@router.patch("/me", response_model=UserProfile)
async def patch_me(
    body: ProfileUpdateRequest,
    current: _CurrentUser,
    db: _DbSession,
) -> UserProfile:
    """Update the caller's `first_name`/`last_name`/`avatar_url` (F19).

    `email`/`username` are immutable — an attempt to change either to a
    different value is a `400` (F20). Empty `first_name`/`last_name` is a
    `422` (F19/R27, backed by `ck_users_names_present`).
    """

    user = await _load_current_user(db, current.user_id)

    try:
        update = validate_profile_update(user, body)
    except ImmutableFieldChangeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{exc.field}' is immutable and cannot be changed.",
        ) from exc
    except EmptyNameError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"'{exc.field}' must not be empty.",
        ) from exc

    apply_profile_update(user, update)
    await db.flush()
    await db.commit()

    logger.info("profile updated", extra={"user_id": str(current.user_id)})

    return UserProfile.from_user(user)
