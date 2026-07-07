"""`password_reset_tokens` ORM model (T16 — password reset, F15-F17, R48).

Maps the `password_reset_tokens` table exactly as authored in
`alembic/versions/0001_initial_schema.py` / the frozen database design doc.
No schema change: this is a read/write mapping over an already-shipped
table.

`token_hash` is the **only** persisted form of the single-use reset
token — the raw value is minted and returned once by
`app.services.password_reset.create_password_reset_token` and never
stored, logged, or re-derivable from this column (see
`app.core.token_hash.hash_reset_token`).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# All timestamps on `password_reset_tokens` are `timestamptz` (UTC) per the
# frozen database design — mirrors `app.models.session`'s same convention.
_TIMESTAMPTZ = DateTime(timezone=True)


class PasswordResetToken(Base):
    """Maps the `password_reset_tokens` table (single-use reset token, F15-F17).

    Only the most recently issued, unused, unexpired token for a given
    user validates (F17) — enforced in application logic
    (`app.services.password_reset`), not by a DB constraint, per the
    frozen database design's explicit note.
    """

    __tablename__ = "password_reset_tokens"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # No `unique=True` here for the same reason as `Session.refresh_token_hash`:
    # uniqueness is already enforced by the shipped `uq_prt_token_hash` unique
    # *index*, not a table-level unique *constraint* SQLAlchemy would infer.
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(_TIMESTAMPTZ, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(_TIMESTAMPTZ, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        _TIMESTAMPTZ, nullable=False, server_default=text("now()")
    )
