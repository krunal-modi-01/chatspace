"""`users` ORM model (T10 minimal slice).

No user-management task has landed an ORM model yet, but the session-store
/ auth-dependency work in T10 needs `users.is_active` to satisfy the
"deactivated user fails auth" invariant (ADR-0006), so this module defines
the mapping now, from the frozen DDL in
`docs/spec/chatspace-v1-database-design.md` / `alembic/versions/0001_initial_schema.py`.

This is intentionally a full column mapping (not a narrow "just is_active"
projection) so a later user-CRUD task can extend behavior on top of the
same model without a migration or a duplicate mapping — but no business
logic beyond what T10 needs (`is_active` gating) lives here.

`hashed_password` is mapped for completeness (it exists on the table) but
must never be selected into a response body or a log line — see
`app.core.redact` and CLAUDE.md SECURITY REQUIREMENTS.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    """Maps the `users` table (see database design doc, lines 301-464)."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    hashed_password: Mapped[str] = mapped_column(Text, nullable=False)
    first_name: Mapped[str] = mapped_column(Text, nullable=False)
    last_name: Mapped[str] = mapped_column(Text, nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    is_system_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # ADR-0009 compensating control for the env-seeded bootstrap admin (T12):
    # added by `alembic/versions/0002_admin_bootstrap_flags.py`, not the frozen
    # 0001 migration. Regular users default False for both; the bootstrap
    # routine sets both True on the seeded System Admin.
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
