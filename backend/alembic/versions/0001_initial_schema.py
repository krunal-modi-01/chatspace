"""Initial schema — enums, tables, indexes, constraints (T04).

Greenfield / additive-only migration authoring the exact DDL from the
frozen database design doc
(`docs/spec/chatspace-v1-database-design.md`, lines 301-464). Nothing in
this file may ever be edited once shipped — future schema changes are new
migrations (CLAUDE.md `do_not_touch: alembic/versions/*`).

Design invariants encoded here (see the DB design doc for the full
rationale):

- Every `id` column is `uuid PRIMARY KEY` with **no DB default** — ids are
  app-generated UUIDv7 (`uuid6` package), never `gen_random_uuid()`.
- Every table has `created_at timestamptz NOT NULL DEFAULT now()`.
- No Postgres extension is required — case-insensitive uniqueness uses
  functional `lower(...)` unique indexes, not `citext`/`pgcrypto`.
- Token columns are `*_token_hash` only; raw tokens are never persisted.
- Autogenerate cannot express functional/partial indexes, `CASE`-based
  CHECKs, or "no default on id" correctly, so all DDL here is authored by
  hand via `op.execute` / explicit `op.create_index(..., postgresql_where=...)`.

Revision ID: 0001
Revises:
Create Date: 2026-07-06

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Enum type names, defined once so upgrade/downgrade stay in lockstep.
CHANNEL_MEMBER_ROLE = postgresql.ENUM(
    "member", "admin", name="channel_member_role", create_type=False
)
INVITE_STATUS = postgresql.ENUM(
    "pending", "accepted", "revoked", name="invite_status", create_type=False
)
ATTACHMENT_KIND = postgresql.ENUM(
    "image", "file", "video", name="attachment_kind", create_type=False
)


def upgrade() -> None:
    """Upgrade schema."""

    # --- Enums (created explicitly, before any table references them) -----
    CHANNEL_MEMBER_ROLE.create(op.get_bind(), checkfirst=False)
    INVITE_STATUS.create(op.get_bind(), checkfirst=False)
    ATTACHMENT_KIND.create(op.get_bind(), checkfirst=False)

    # --- users --------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("hashed_password", sa.Text(), nullable=False),
        sa.Column("first_name", sa.Text(), nullable=False),
        sa.Column("last_name", sa.Text(), nullable=False),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_system_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("char_length(username) BETWEEN 1 AND 32", name="username_len"),
        sa.CheckConstraint(
            "btrim(first_name) <> '' AND btrim(last_name) <> ''",
            name="names_present",
        ),
    )
    op.create_index("uq_users_username_lower", "users", [sa.text("lower(username)")], unique=True)
    op.create_index("uq_users_email_lower", "users", [sa.text("lower(email)")], unique=True)

    # --- channels -------------------------------------------------------------
    op.create_table(
        "channels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("is_private", sa.Boolean(), nullable=False),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("name ~ '^[A-Za-z0-9 _-]{1,80}$'", name="name"),
    )
    op.create_index("uq_channels_name_lower", "channels", [sa.text("lower(name)")], unique=True)

    # --- channel_members --------------------------------------------------
    op.create_table(
        "channel_members",
        sa.Column(
            "channel_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "role",
            CHANNEL_MEMBER_ROLE,
            nullable=False,
            server_default="member",
        ),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("channel_id", "user_id", name="pk_channel_members"),
    )
    op.create_index("ix_channel_members_user", "channel_members", ["user_id"])
    op.create_index(
        "ix_channel_members_admin_succession",
        "channel_members",
        ["channel_id", "joined_at"],
        postgresql_where=sa.text("role = 'admin'"),
    )

    # --- messages -----------------------------------------------------------
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "channel_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("channels.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "recipient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "sender_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(channel_id IS NOT NULL AND recipient_id IS NULL) OR "
            "(channel_id IS NULL AND recipient_id IS NOT NULL AND recipient_id <> sender_id)",
            name="target_xor",
        ),
        sa.CheckConstraint(
            "char_length(content) <= 4000 AND btrim(content) <> ''",
            name="content",
        ),
    )
    op.create_index(
        "ix_messages_channel_history",
        "messages",
        ["channel_id", "created_at", "id"],
        postgresql_where=sa.text("deleted_at IS NULL AND channel_id IS NOT NULL"),
    )
    op.create_index(
        "ix_messages_dm_history",
        "messages",
        [
            sa.text("least(sender_id, recipient_id)"),
            sa.text("greatest(sender_id, recipient_id)"),
            sa.text("created_at"),
            sa.text("id"),
        ],
        postgresql_where=sa.text("recipient_id IS NOT NULL AND deleted_at IS NULL"),
    )

    # --- attachments -----------------------------------------------------
    op.create_table(
        "attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "uploader_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", ATTACHMENT_KIND, nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("byte_size > 0", name="size_positive"),
        sa.CheckConstraint(
            "byte_size <= CASE kind "
            "WHEN 'image' THEN 10485760 "
            "WHEN 'file' THEN 52428800 "
            "WHEN 'video' THEN 209715200 END",
            name="size_cap",
        ),
    )
    op.create_index(
        "ix_attachments_message",
        "attachments",
        ["message_id"],
        postgresql_where=sa.text("message_id IS NOT NULL"),
    )
    op.create_index(
        "ix_attachments_orphans",
        "attachments",
        ["created_at"],
        postgresql_where=sa.text("message_id IS NULL"),
    )

    # --- invites -------------------------------------------------------------
    op.create_table(
        "invites",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("status", INVITE_STATUS, nullable=False, server_default="pending"),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("uq_invites_token_hash", "invites", ["token_hash"], unique=True)
    op.create_index(
        "ix_invites_email_pending",
        "invites",
        ["email"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    # --- password_reset_tokens --------------------------------------------
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("uq_prt_token_hash", "password_reset_tokens", ["token_hash"], unique=True)
    op.create_index(
        "ix_prt_user_active",
        "password_reset_tokens",
        ["user_id"],
        postgresql_where=sa.text("used_at IS NULL"),
    )

    # --- sessions -------------------------------------------------------------
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("refresh_token_hash", sa.Text(), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("uq_sessions_refresh_hash", "sessions", ["refresh_token_hash"], unique=True)
    op.create_index(
        "ix_sessions_user_active",
        "sessions",
        ["user_id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    """Downgrade schema — exact reverse of `upgrade`, total round-trip to base."""

    # Indexes are dropped implicitly by `DROP TABLE`; only the tables (in
    # exact reverse FK order) and the enum types need explicit teardown.
    op.drop_table("sessions")
    op.drop_table("password_reset_tokens")
    op.drop_table("invites")
    op.drop_table("attachments")
    op.drop_table("messages")
    op.drop_table("channel_members")
    op.drop_table("channels")
    op.drop_table("users")

    ATTACHMENT_KIND.drop(op.get_bind(), checkfirst=False)
    INVITE_STATUS.drop(op.get_bind(), checkfirst=False)
    CHANNEL_MEMBER_ROLE.drop(op.get_bind(), checkfirst=False)
