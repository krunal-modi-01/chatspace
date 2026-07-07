"""SQLAlchemy ORM models.

`Session`/`User` are the two models needed by T10 (session store + auth
dependency). Import through this package (`from app.models import Session,
User`) rather than the submodules directly, so `app.db.base.Base.metadata`
sees every mapped class Alembic/tests need to inspect.
"""

from __future__ import annotations

from app.models.session import Session
from app.models.user import User

__all__ = ["Session", "User"]
