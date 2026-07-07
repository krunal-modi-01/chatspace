"""SQLAlchemy ORM models.

`Session`/`User` are the two models needed by T10 (session store + auth
dependency); `PasswordResetToken` is added by T16 (password reset). Import
through this package (`from app.models import Session, User,
PasswordResetToken`) rather than the submodules directly, so
`app.db.base.Base.metadata` sees every mapped class Alembic/tests need to
inspect.
"""

from __future__ import annotations

from app.models.password_reset_token import PasswordResetToken
from app.models.session import Session
from app.models.user import User

__all__ = ["PasswordResetToken", "Session", "User"]
