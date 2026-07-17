"""T04: initial schema migration round-trips and matches the frozen DDL.

These tests drive real Alembic upgrade/downgrade against the local test
Postgres (see `conftest.postgres_available`) — skipped (not failed) when
no local Postgres is reachable, mirroring the pattern in `test_db.py`.
Inspection uses the project's existing `asyncpg`/`sqlalchemy[asyncio]`
stack (via `run_sync`) rather than adding a new sync DB driver dependency.

They assert three things the frozen database design doc calls out as easy
to get wrong when hand-authoring DDL via `op.execute`/`op.create_table`:

1. `upgrade head` creates every enum, table, and the functional/partial
   indexes with the exact names from the DB design doc (autogenerate
   cannot produce these, so a typo/omission here is a real regression).
2. Constraint names on hand-authored `CheckConstraint`s land exactly as
   the frozen doc specifies, not doubled by `Base.metadata`'s naming
   convention (a footgun: `env.py` wires `target_metadata=Base.metadata`,
   so an explicit `name="ck_foo_bar"` is silently re-templated to
   `ck_foo_ck_foo_bar` unless the constraint is given just the convention
   suffix).
3. `downgrade base` is total — no tables, enums, or leftover objects
   besides Alembic's own bookkeeping table.
4. The XOR / no-self-DM CHECK on `messages` actually rejects bad rows.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command

# Import the per-worktree test DSN from conftest rather than hardcoding it, so
# these real upgrade/downgrade cycles run against this worktree's isolated
# database instead of colliding on the shared `chatspace_test`.
from .conftest import ASYNC_DATABASE_URL

pytestmark = pytest.mark.usefixtures("configured_env")

EXPECTED_TABLES = {
    "alembic_version",
    "users",
    "channels",
    "channel_members",
    "messages",
    "attachments",
    "invites",
    "password_reset_tokens",
    "sessions",
}

EXPECTED_ENUMS = {"channel_member_role", "invite_status", "attachment_kind"}

EXPECTED_CHECK_NAMES = {
    "users": {"ck_users_username_len", "ck_users_names_present"},
    "channels": {"ck_channels_name"},
    "messages": {"ck_messages_target_xor", "ck_messages_content"},
    "attachments": {"ck_attachments_size_positive", "ck_attachments_size_cap"},
}

EXPECTED_INDEXES = {
    "uq_users_username_lower",
    "uq_users_email_lower",
    "uq_channels_name_lower",
    "ix_channel_members_user",
    "ix_channel_members_admin_succession",
    "ix_messages_channel_history",
    "ix_messages_dm_history",
    "ix_attachments_message",
    "ix_attachments_orphans",
    "uq_invites_token_hash",
    "ix_invites_email_pending",
    "uq_prt_token_hash",
    "ix_prt_user_active",
    "uq_sessions_refresh_hash",
    "ix_sessions_user_active",
}


def _alembic_config() -> Config:
    # `env.py` builds its own async engine from `app.core.config.get_settings`
    # (the `DATABASE_URL` env var `configured_env` sets), so no explicit
    # `sqlalchemy.url` override is required here.
    return Config("alembic.ini")


@pytest.fixture
async def async_engine(postgres_available: bool) -> AsyncIterator[AsyncEngine]:
    if not postgres_available:
        pytest.skip("local Postgres not reachable on localhost:5425")

    engine = create_async_engine(ASYNC_DATABASE_URL)
    yield engine
    await engine.dispose()


@pytest.fixture
def migrated_db(postgres_available: bool) -> Iterator[Config]:
    """Run `upgrade head`; the enclosing test/module tears down explicitly."""

    if not postgres_available:
        pytest.skip("local Postgres not reachable on localhost:5425")

    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    try:
        yield cfg
    finally:
        command.downgrade(cfg, "base")


async def _inspect_tables(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as conn:
        names: list[str] = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_table_names()
        )
        return set(names)


async def _inspect_check_constraints(engine: AsyncEngine, table: str) -> set[str]:
    async with engine.connect() as conn:
        constraints: list[Any] = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_check_constraints(table)
        )
        return {c["name"] for c in constraints}


async def _inspect_columns(engine: AsyncEngine, table: str) -> dict[str, Any]:
    async with engine.connect() as conn:
        columns: list[Any] = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_columns(table)
        )
        return {c["name"]: c for c in columns}


class TestUpgradeHead:
    async def test_creates_expected_tables(
        self, migrated_db: Config, async_engine: AsyncEngine
    ) -> None:
        assert await _inspect_tables(async_engine) == EXPECTED_TABLES

    async def test_creates_expected_enums(
        self, migrated_db: Config, async_engine: AsyncEngine
    ) -> None:
        async with async_engine.connect() as conn:
            rows = await conn.execute(text("SELECT typname FROM pg_type WHERE typtype = 'e'"))
            enum_names = {row[0] for row in rows}
        assert EXPECTED_ENUMS <= enum_names

    async def test_id_columns_have_no_server_default(
        self, migrated_db: Config, async_engine: AsyncEngine
    ) -> None:
        # `channel_members` has no `id` column — its PK is the composite
        # (channel_id, user_id) per the frozen doc.
        tables_with_id = EXPECTED_TABLES - {"alembic_version", "channel_members"}
        for table in tables_with_id:
            columns = await _inspect_columns(async_engine, table)
            assert columns["id"]["default"] is None, f"{table}.id must have no DB default"

    async def test_created_at_defaults_to_now(
        self, migrated_db: Config, async_engine: AsyncEngine
    ) -> None:
        # `channel_members` uses `joined_at` and `sessions` uses `issued_at`
        # (not `created_at`) per the frozen doc, but both are likewise
        # `NOT NULL DEFAULT now()`.
        tables_with_created_at = EXPECTED_TABLES - {
            "alembic_version",
            "channel_members",
            "sessions",
        }
        for table in tables_with_created_at:
            columns = await _inspect_columns(async_engine, table)
            assert columns["created_at"]["default"] is not None
            assert "now()" in columns["created_at"]["default"]

        for table, timestamp_column in (
            ("channel_members", "joined_at"),
            ("sessions", "issued_at"),
        ):
            columns = await _inspect_columns(async_engine, table)
            assert columns[timestamp_column]["default"] is not None
            assert "now()" in columns[timestamp_column]["default"]

    async def test_check_constraint_names_match_frozen_doc(
        self, migrated_db: Config, async_engine: AsyncEngine
    ) -> None:
        for table, expected_names in EXPECTED_CHECK_NAMES.items():
            actual = await _inspect_check_constraints(async_engine, table)
            assert expected_names <= actual, f"{table} missing expected CHECK names: {actual}"

    async def test_expected_indexes_exist(
        self, migrated_db: Config, async_engine: AsyncEngine
    ) -> None:
        async with async_engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
            )
            index_names = {row[0] for row in rows}
        assert EXPECTED_INDEXES <= index_names

    async def test_dm_history_index_uses_least_greatest(
        self, migrated_db: Config, async_engine: AsyncEngine
    ) -> None:
        async with async_engine.connect() as conn:
            result = await conn.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_messages_dm_history'")
            )
            indexdef = result.scalar_one()
        assert "least(sender_id, recipient_id)" in indexdef.lower()
        assert "greatest(sender_id, recipient_id)" in indexdef.lower()

    async def test_messages_xor_check_rejects_neither_target(
        self, migrated_db: Config, async_engine: AsyncEngine
    ) -> None:
        user_id = uuid.uuid4()
        async with async_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO users (id, username, email, hashed_password, "
                    "first_name, last_name) VALUES "
                    "(:id, 'alice', 'alice@example.com', 'hashed', 'Alice', 'A')"
                ),
                {"id": user_id},
            )

        async with async_engine.connect() as conn:
            with pytest.raises(IntegrityError):
                async with conn.begin():
                    await conn.execute(
                        text(
                            "INSERT INTO messages "
                            "(id, channel_id, recipient_id, sender_id, content) "
                            "VALUES (:id, NULL, NULL, :sender, 'hi')"
                        ),
                        {"id": uuid.uuid4(), "sender": user_id},
                    )

    async def test_messages_xor_check_rejects_self_dm(
        self, migrated_db: Config, async_engine: AsyncEngine
    ) -> None:
        user_id = uuid.uuid4()
        async with async_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO users (id, username, email, hashed_password, "
                    "first_name, last_name) VALUES "
                    "(:id, 'bob', 'bob@example.com', 'hashed', 'Bob', 'B')"
                ),
                {"id": user_id},
            )

        async with async_engine.connect() as conn:
            with pytest.raises(IntegrityError):
                async with conn.begin():
                    await conn.execute(
                        text(
                            "INSERT INTO messages "
                            "(id, channel_id, recipient_id, sender_id, content) "
                            "VALUES (:id, NULL, :sender, :sender, 'hi')"
                        ),
                        {"id": uuid.uuid4(), "sender": user_id},
                    )

    async def test_messages_content_check_rejects_blank_body(
        self, migrated_db: Config, async_engine: AsyncEngine
    ) -> None:
        user_id = uuid.uuid4()
        other_id = uuid.uuid4()
        async with async_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO users (id, username, email, hashed_password, "
                    "first_name, last_name) VALUES "
                    "(:id, 'carol', 'carol@example.com', 'hashed', 'Carol', 'C'), "
                    "(:other_id, 'dave', 'dave@example.com', 'hashed', 'Dave', 'D')"
                ),
                {"id": user_id, "other_id": other_id},
            )

        async with async_engine.connect() as conn:
            with pytest.raises(IntegrityError):
                async with conn.begin():
                    await conn.execute(
                        text(
                            "INSERT INTO messages "
                            "(id, channel_id, recipient_id, sender_id, content) "
                            "VALUES (:id, NULL, :recipient, :sender, '   ')"
                        ),
                        {"id": uuid.uuid4(), "sender": user_id, "recipient": other_id},
                    )


class TestDowngradeBase:
    async def test_downgrade_leaves_only_alembic_bookkeeping(
        self, postgres_available: bool, async_engine: AsyncEngine
    ) -> None:
        if not postgres_available:
            pytest.skip("local Postgres not reachable on localhost:5425")

        cfg = _alembic_config()
        # `command.upgrade`/`downgrade` call `asyncio.run(...)` internally
        # (see `alembic/env.py`), which cannot be invoked from within an
        # already-running event loop (this test is itself a coroutine under
        # `pytest-asyncio`) — run them on a worker thread instead.
        await asyncio.to_thread(command.upgrade, cfg, "head")
        await asyncio.to_thread(command.downgrade, cfg, "base")

        assert await _inspect_tables(async_engine) == {"alembic_version"}

        async with async_engine.connect() as conn:
            rows = await conn.execute(text("SELECT typname FROM pg_type WHERE typtype = 'e'"))
            enum_names = {row[0] for row in rows}
        assert EXPECTED_ENUMS.isdisjoint(enum_names)
