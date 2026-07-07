"""Add must_change_password / email_verified flags to users (T12 review fix).

ADR-0009's compensating control for the env-seeded bootstrap System Admin
requires the seeded account to be created flagged to **force a password
change on first login** and with **email marked verified**. Neither had
schema support: `0001_initial_schema.py` predates ADR-0009's decision and
is frozen (CLAUDE.md `do_not_touch: alembic/versions/*` — never edit a
shipped migration, only add new ones). This migration adds exactly those
two columns, additively, to the existing `users` table.

Both columns use `server_default` (not just an ORM-side default) so the
`ADD COLUMN` back-fills every pre-existing row with a valid, explicit
value in the same statement — no separate `UPDATE` pass, no nullable
transition period, and no table rewrite (adding a `NOT NULL` column with
a constant `DEFAULT` is a fast, metadata-only change on Postgres 11+,
per the project's target: build for 1,000 users, not a `pg_dump`-and-
restore migration budget). Regular (non-bootstrap) users default to
`false` for both — enforcing the flag at login/registration is out of
scope here (see T15); this migration only adds the columns and lets
`app.services.bootstrap.ensure_system_admin_bootstrapped` set them to
`true` for the seeded admin.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-06

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""

    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    """Downgrade schema — drop both columns, exact reverse of `upgrade`."""

    op.drop_column("users", "email_verified")
    op.drop_column("users", "must_change_password")
