"""`sessions` ORM model (T10 — session store, ADR-0006).

Maps the `sessions` table exactly as authored in
`alembic/versions/0001_initial_schema.py` / the frozen database design doc
(lines 301-464). No schema change: this is a read/write mapping over an
already-shipped table.

`refresh_token_hash` is the **only** persisted form of the refresh token —
the raw token is minted and returned once by `app.services.sessions` and
never stored, logged, or re-derivable from this column (see
`app.core.token_hash`).
"""

from __future__ import annotations

from datetime import datetime
from ipaddress import IPv4Address, IPv6Address
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# All timestamps on `sessions` are `timestamptz` (UTC) per the frozen
# database design — `DateTime(timezone=True)` mirrors that exactly so
# asyncpg round-trips timezone-aware `datetime` values instead of naive
# ones (a naive `datetime` sent for a `timestamptz` column raises at the
# driver level).
_TIMESTAMPTZ = DateTime(timezone=True)


class Session(Base):
    """Maps the `sessions` table (revocable session store, ADR-0006).

    `id` doubles as the `sid` claim minted into access JWTs
    (`app.core.jwt.create_access_token`).
    """

    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # No `unique=True` here: the uniqueness guarantee is already enforced
    # by the shipped `uq_sessions_refresh_hash` unique *index* (created via
    # `op.create_index(..., unique=True)` in `0001_initial_schema.py`), not
    # a table-level unique *constraint*. `mapped_column(unique=True)` would
    # make SQLAlchemy's autogenerate believe this column owns a constraint
    # it doesn't recognize the existing index as satisfying, and emit a
    # spurious duplicate `ADD CONSTRAINT` on the next `alembic revision
    # --autogenerate`.
    refresh_token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[IPv4Address | IPv6Address | str | None] = mapped_column(INET, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(_TIMESTAMPTZ, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(_TIMESTAMPTZ, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(_TIMESTAMPTZ, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(_TIMESTAMPTZ, nullable=True)
