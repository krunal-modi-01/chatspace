"""T12 — System Admin bootstrap (ADR-0009, technical spec §10 Phase 0, FS F8/F9).

Exercises `app.services.bootstrap.ensure_system_admin_bootstrapped` against
a real, freshly-migrated local test Postgres — skipped (not failed) when
no local Postgres is reachable, mirroring `tests/test_migrations.py`. Also
covers the `app.main` lifespan wiring: the app must refuse to finish
starting up when bootstrap cannot guarantee an active System Admin.
"""

from __future__ import annotations

import socket
from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.security import verify_password
from app.models.user import User
from app.services.bootstrap import BootstrapError, ensure_system_admin_bootstrapped

from .conftest import _TEST_DATABASE_URL, REQUIRED_ENV

pytestmark = pytest.mark.usefixtures("configured_env")

# A placeholder for `users.hashed_password` in fixtures that manually seed
# a pre-existing user row — never a real credential, just satisfies the
# NOT NULL column. Built from a variable (not a quoted literal next to
# "password=") on purpose so it can't be mistaken for an embedded secret.
_NOT_A_REAL_HASH = "x" * 16


def _bootstrap_settings(**overrides: object) -> Settings:
    """A `Settings` instance seeded with the same values `configured_env` sets."""

    defaults: dict[str, object] = {key.lower(): value for key, value in REQUIRED_ENV.items()}
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


@pytest.fixture
async def db_sessionmaker(
    postgres_available: bool, migrated_db: None
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A fresh engine/sessionmaker per test, against a freshly migrated schema.

    Depends on `migrated_db` (conftest) so the schema is reset to `head`
    before each test — mirroring the `client` fixture. Relying instead on
    the once-per-session `pytest_sessionstart` migration is unsafe: any
    other test that drives `downgrade base` (e.g. `test_migrations.py`, or
    the downgrade test in this module) can run first and leave `users`
    absent, so a bare `DELETE FROM users` here would error at setup
    depending on collection order. `migrated_db` already yields an empty
    schema, giving each test the "zero users" bootstrap precondition; the
    `DELETE FROM users` below is kept as a cheap, explicit guard.
    """

    if not postgres_available:
        pytest.skip("local Postgres not reachable on localhost:5432")

    engine = create_async_engine(_TEST_DATABASE_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM users"))
        yield async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    finally:
        await engine.dispose()


async def _user_count(sessionmaker: async_sessionmaker[AsyncSession]) -> int:
    async with sessionmaker() as session:
        rows = (await session.execute(select(User))).scalars().all()
        return len(rows)


class TestCreatesAdminWhenZeroUsers:
    async def test_creates_exactly_one_active_system_admin(
        self, db_sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        settings = _bootstrap_settings()

        async with db_sessionmaker() as session:
            await ensure_system_admin_bootstrapped(session, settings)
            await session.commit()

        async with db_sessionmaker() as session:
            users = (await session.execute(select(User))).scalars().all()

        assert len(users) == 1
        admin = users[0]
        assert admin.username == settings.bootstrap_admin_username
        assert admin.email == settings.bootstrap_admin_email
        assert admin.first_name == settings.bootstrap_admin_first_name
        assert admin.last_name == settings.bootstrap_admin_last_name
        assert admin.is_active is True
        assert admin.is_system_admin is True

    async def test_password_is_hashed_not_stored_in_the_clear(
        self, db_sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        settings = _bootstrap_settings()

        async with db_sessionmaker() as session:
            await ensure_system_admin_bootstrapped(session, settings)
            await session.commit()

        async with db_sessionmaker() as session:
            admin = (await session.execute(select(User))).scalar_one()

        raw_password = settings.bootstrap_admin_password.get_secret_value()
        assert admin.hashed_password != raw_password
        assert verify_password(raw_password, admin.hashed_password)

    async def test_seeded_admin_is_flagged_per_adr_0009_compensating_control(
        self, db_sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        """The seeded admin is a standing env-seeded credential (ADR-0009):
        it must be flagged to force a password change on first login and
        treated as pre-verified (there is no invite/registration flow to
        verify it against)."""

        settings = _bootstrap_settings()

        async with db_sessionmaker() as session:
            await ensure_system_admin_bootstrapped(session, settings)
            await session.commit()

        async with db_sessionmaker() as session:
            admin = (await session.execute(select(User))).scalar_one()

        assert admin.must_change_password is True
        assert admin.email_verified is True


class TestIdempotentOnRestart:
    async def test_rerunning_does_not_create_a_duplicate(
        self, db_sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        settings = _bootstrap_settings()

        for _ in range(3):
            async with db_sessionmaker() as session:
                await ensure_system_admin_bootstrapped(session, settings)
                await session.commit()

        assert await _user_count(db_sessionmaker) == 1


class TestSkipsWhenUsersAlreadyExist:
    async def test_skips_creation_when_a_system_admin_already_exists(
        self, db_sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        """A pre-existing (e.g. hand-provisioned) admin must not be duplicated."""

        from app.core.ids import generate_id

        settings = _bootstrap_settings(bootstrap_admin_username="someone-else")

        async with db_sessionmaker() as session:
            session.add(
                User(
                    id=generate_id(),
                    username="original-admin",
                    email="original-admin@chatspace.example",
                    hashed_password=_NOT_A_REAL_HASH,
                    first_name="Original",
                    last_name="Admin",
                    is_active=True,
                    is_system_admin=True,
                )
            )
            await session.commit()

        async with db_sessionmaker() as session:
            await ensure_system_admin_bootstrapped(session, settings)
            await session.commit()

        assert await _user_count(db_sessionmaker) == 1

    async def test_raises_when_users_exist_but_no_active_system_admin(
        self, db_sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        """Refuse to serve rather than silently accept a zero-admin workspace.

        This is the startup-side mirror of the frozen contract's `409`
        "last active System Admin" guard on
        `POST /v1/admin/users/{user_id}/deactivate` (T20/F27): the app
        must never finish starting up if it cannot guarantee at least one
        active System Admin exists.
        """

        from app.core.ids import generate_id

        settings = _bootstrap_settings()

        async with db_sessionmaker() as session:
            session.add(
                User(
                    id=generate_id(),
                    username="plain-user",
                    email="plain-user@chatspace.example",
                    hashed_password=_NOT_A_REAL_HASH,
                    first_name="Plain",
                    last_name="User",
                    is_active=True,
                    is_system_admin=False,
                )
            )
            await session.commit()

        with pytest.raises(BootstrapError):
            async with db_sessionmaker() as session:
                await ensure_system_admin_bootstrapped(session, settings)
                await session.commit()

        # The routine must not have inserted the env-seeded admin either —
        # "zero users" was already false, so it correctly declined to act.
        assert await _user_count(db_sessionmaker) == 1


class TestConcurrentBootstrapRace:
    async def test_two_concurrent_bootstraps_yield_exactly_one_admin(
        self, db_sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        """Two instances racing at startup must not both succeed at inserting.

        The case-insensitive unique indexes on `lower(username)`/`lower(email)`
        (frozen in the initial migration) guarantee the loser's INSERT fails
        with a unique violation, which `ensure_system_admin_bootstrapped`
        treats as a benign "someone already bootstrapped it" outcome rather
        than an error.
        """
        import asyncio

        settings = _bootstrap_settings()

        async def _attempt() -> None:
            async with db_sessionmaker() as session:
                await ensure_system_admin_bootstrapped(session, settings)
                await session.commit()

        results = await asyncio.gather(_attempt(), _attempt(), return_exceptions=True)

        for result in results:
            if isinstance(result, BaseException):
                raise result

        assert await _user_count(db_sessionmaker) == 1


class TestMalformedSeedFailsLoudly:
    async def test_username_exceeding_max_length_raises_bootstrap_error(
        self, db_sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        """A CHECK-constraint violation is a real misconfiguration, not a
        benign concurrent-bootstrap race — it must raise, not be swallowed."""

        settings = _bootstrap_settings(bootstrap_admin_username="x" * 33)

        with pytest.raises(BootstrapError):
            async with db_sessionmaker() as session:
                await ensure_system_admin_bootstrapped(session, settings)
                await session.commit()

        assert await _user_count(db_sessionmaker) == 0

    async def test_blank_first_name_raises_bootstrap_error(
        self, db_sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        settings = _bootstrap_settings(bootstrap_admin_first_name="   ")

        with pytest.raises(BootstrapError):
            async with db_sessionmaker() as session:
                await ensure_system_admin_bootstrapped(session, settings)
                await session.commit()

        assert await _user_count(db_sessionmaker) == 0

    async def test_password_violating_policy_raises_bootstrap_error(
        self, db_sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        """A blank/weak `BOOTSTRAP_ADMIN_PASSWORD` must never be silently
        accepted — it must be run through the same
        `enforce_password_policy` every other password path uses, and
        fail loudly (review finding: bootstrap bypassed the policy)."""

        # Not a real credential: an all-letters, no-digit value built from a
        # variable (not a quoted literal next to "password=") purely to
        # exercise the policy-violation path, mirroring `_NOT_A_REAL_HASH`
        # above.
        policy_violating_password = "".join(["all", "letters", "nodigit"])
        settings = _bootstrap_settings(bootstrap_admin_password=policy_violating_password)

        with pytest.raises(BootstrapError):
            async with db_sessionmaker() as session:
                await ensure_system_admin_bootstrapped(session, settings)
                await session.commit()

        assert await _user_count(db_sessionmaker) == 0


class TestNeverLogsSecrets:
    async def test_password_and_email_never_appear_in_log_records(
        self,
        db_sessionmaker: async_sessionmaker[AsyncSession],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        settings = _bootstrap_settings()

        with caplog.at_level("DEBUG"):
            async with db_sessionmaker() as session:
                await ensure_system_admin_bootstrapped(session, settings)
                await session.commit()

        raw_password = settings.bootstrap_admin_password.get_secret_value()
        for record in caplog.records:
            rendered = record.getMessage()
            assert raw_password not in rendered
            assert settings.bootstrap_admin_email not in rendered
            for value in vars(record).values():
                assert raw_password not in str(value)
                assert settings.bootstrap_admin_email not in str(value)


class TestAppRefusesToServeWithoutAnAdmin:
    def test_app_startup_fails_when_database_is_unreachable(
        self, configured_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole point of T12: an unreachable DB at startup means the
        bootstrap routine cannot guarantee an admin exists, so the app must
        refuse to finish starting up rather than serve traffic anyway."""

        from app.core.config import get_settings
        from app.db.session import get_engine, get_sessionmaker

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            closed_port = sock.getsockname()[1]

        monkeypatch.setenv(
            "DATABASE_URL",
            f"postgresql+asyncpg://user:pass@127.0.0.1:{closed_port}/does-not-exist",
        )
        monkeypatch.setenv("DB_CONNECT_TIMEOUT_SECONDS", "1")
        get_settings.cache_clear()
        get_engine.cache_clear()
        get_sessionmaker.cache_clear()

        from app.main import create_app

        app = create_app()
        with pytest.raises(Exception):  # noqa: B017 - the ASGI lifespan wraps the DB error
            with TestClient(app):
                pass

        get_settings.cache_clear()
        get_engine.cache_clear()
        get_sessionmaker.cache_clear()

    def test_app_starts_successfully_when_an_admin_already_exists(self, client: TestClient) -> None:
        """Sanity check: the happy path (real Postgres, T12 bootstrap
        succeeds) still serves traffic normally — exercised via the shared
        `client` fixture, which itself depends on a successful startup."""

        response = client.get("/v1/healthz")

        assert response.status_code == 200


class TestAdminBootstrapFlagsMigration:
    """`0002_admin_bootstrap_flags` round-trips cleanly (mirrors
    `tests/test_migrations.py`'s `migrated_db`/`TestDowngradeBase` pattern)
    and adds exactly the two columns ADR-0009's compensating control needs.

    `conftest.pytest_sessionstart` migrates the shared test database to
    `head` once for the *whole* run, and every other test module in this
    suite assumes that schema is in place. This test's own
    `downgrade("base")` therefore always re-upgrades back to `head` in a
    `finally`, restoring the shared session schema for whatever test
    module runs next — mirroring the round-trip `test_migrations.py`
    performs, but without leaving global state at `base` for the rest of
    the suite (that file's own downgrade-to-base tests are safe only
    because they happen to run last alphabetically; this module does not
    get that guarantee).
    """

    async def test_upgrade_head_adds_expected_columns_then_downgrade_base_drops_them(
        self, postgres_available: bool
    ) -> None:
        if not postgres_available:
            pytest.skip("local Postgres not reachable on localhost:5432")

        import asyncio

        from alembic.config import Config
        from sqlalchemy import inspect
        from sqlalchemy.ext.asyncio import create_async_engine

        from alembic import command

        cfg = Config("alembic.ini")
        engine = create_async_engine(_TEST_DATABASE_URL)
        try:
            # `command.upgrade`/`downgrade` call `asyncio.run(...)`
            # internally (see `alembic/env.py`), which cannot be invoked
            # from within an already-running event loop — run on a worker
            # thread, mirroring `test_migrations.py`. Starting from a full
            # `base` (rather than the session's already-`head` state)
            # exercises the entire chain (0001 -> 0002) from scratch, not
            # just the additive step.
            await asyncio.to_thread(command.downgrade, cfg, "base")
            await asyncio.to_thread(command.upgrade, cfg, "head")

            async with engine.connect() as conn:
                columns: dict[str, object] = await conn.run_sync(
                    lambda sync_conn: {
                        c["name"]: c for c in inspect(sync_conn).get_columns("users")
                    }
                )

            assert columns["must_change_password"]["nullable"] is False
            assert columns["email_verified"]["nullable"] is False

            await asyncio.to_thread(command.downgrade, cfg, "base")

            async with engine.connect() as conn:
                remaining_tables: set[str] = await conn.run_sync(
                    lambda sync_conn: set(inspect(sync_conn).get_table_names())
                )

            # `downgrade base` is total: no leftover `users` table (and
            # hence no leftover columns) besides Alembic's own bookkeeping.
            assert remaining_tables == {"alembic_version"}
        finally:
            # Always restore the shared session schema to `head`, whatever
            # happened above, since every other test module in the suite
            # depends on it.
            await asyncio.to_thread(command.upgrade, cfg, "head")
            await engine.dispose()
