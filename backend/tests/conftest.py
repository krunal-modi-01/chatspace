from __future__ import annotations

import asyncio
import hashlib
import os
import socket
import subprocess
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Per-worktree test isolation ───────────────────────────────────────────
# The feature-flow workflow runs parallel tasks in separate git worktrees on
# the SAME host, so they share one Postgres server and one Redis server. The
# `migrated_db` fixture drops/recreates the `public` schema and terminates
# every other connection to its database — so against a single shared
# `chatspace_test`, concurrent worktree runs sabotage each other (dropped
# schema + killed connections → flaky `relation "users" does not exist`).
#
# Fix: derive the test database name and Redis index from the worktree, so
# each *linked* worktree gets its own isolated data layer while the main
# checkout keeps the historical defaults (`chatspace_test`, Redis db 1).
_PG_HOST, _PG_PORT, _PG_USER, _PG_PASS = "localhost", 5432, "postgres", "postgres"
_REDIS_HOST, _REDIS_PORT = "localhost", 6379


def _worktree_suffix() -> str | None:
    """Stable short id for a *linked* git worktree, or None for the main checkout.

    A linked worktree's top-level `.git` is a FILE (`gitdir: …`); the main
    checkout's is a directory. That distinction needs no extra git plumbing
    and degrades safely (returns None) when git isn't available at all.
    """

    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None
    if not top or not os.path.isfile(os.path.join(top, ".git")):
        return None  # main checkout (`.git` is a dir) or not a git repo
    return hashlib.sha1(os.path.realpath(top).encode()).hexdigest()[:8]


_WORKTREE_SUFFIX = _worktree_suffix()
_TEST_DB_NAME = f"chatspace_test_{_WORKTREE_SUFFIX}" if _WORKTREE_SUFFIX else "chatspace_test"
# Main checkout keeps Redis db 1; each worktree maps to 2..15 (14 slots), so a
# worktree never collides with the main checkout's db 1 nor the db 0 used by
# the "redis down" tests.
_REDIS_DB = (int(_WORKTREE_SUFFIX, 16) % 14) + 2 if _WORKTREE_SUFFIX else 1

# Same DSN as `REQUIRED_ENV["DATABASE_URL"]` below, spelled out separately
# because it is consumed directly by `sqlalchemy.create_async_engine`
# (outside of `Settings`) by the `db_session` fixture.
ASYNC_DATABASE_URL = f"postgresql+asyncpg://{_PG_USER}:{_PG_PASS}@{_PG_HOST}:{_PG_PORT}/{_TEST_DB_NAME}"
# Maintenance connection to the `postgres` database, used only to CREATE/DROP
# the per-worktree test database (CREATE/DROP DATABASE can't run in a txn).
_PG_ADMIN_URL = f"postgresql+asyncpg://{_PG_USER}:{_PG_PASS}@{_PG_HOST}:{_PG_PORT}/postgres"
_REDIS_URL = f"redis://{_REDIS_HOST}:{_REDIS_PORT}/{_REDIS_DB}"

REQUIRED_ENV: dict[str, str] = {
    # A real, reachable local Postgres used by the `check_database` /
    # `/v1/readyz` happy-path tests (T03) and by the Alembic baseline
    # smoke test. Integration tests that need it are skipped (not failed)
    # when it isn't reachable — see `postgres_available` in this file.
    "DATABASE_URL": ASYNC_DATABASE_URL,
    "REDIS_URL": _REDIS_URL,
    "JWT_SIGNING_KEY": "test-signing-key-not-a-real-secret",
    "SMTP_HOST": "localhost",
    "SMTP_PORT": "1025",
    "SMTP_USERNAME": "test",
    "SMTP_PASSWORD": "test-smtp-password",
    "SMTP_FROM_ADDRESS": "no-reply@chatspace.example",
    "S3_ENDPOINT_URL": "http://localhost:9000",
    "S3_BUCKET_NAME": "chatspace-media-test",
    "S3_ACCESS_KEY_ID": "test-access-key",
    "S3_SECRET_ACCESS_KEY": "test-secret-key",
    "BOOTSTRAP_ADMIN_EMAIL": "admin@chatspace.example",
    "BOOTSTRAP_ADMIN_USERNAME": "admin",
    # Must satisfy `app.core.password_policy.enforce_password_policy`
    # (letter + digit, >= 6 chars) since `ensure_system_admin_bootstrapped`
    # (T12) now enforces the same policy as every other password path.
    "BOOTSTRAP_ADMIN_PASSWORD": "test-bootstrap-password-1",
    "BOOTSTRAP_ADMIN_FIRST_NAME": "System",
    "BOOTSTRAP_ADMIN_LAST_NAME": "Admin",
}

# Matches `REQUIRED_ENV["DATABASE_URL"]` above — used by the `client`
# fixture to migrate/reset the schema the T12 bootstrap routine needs at
# every application startup.
_TEST_DATABASE_URL = REQUIRED_ENV["DATABASE_URL"]


@pytest.fixture
def configured_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Populate every required setting with a non-secret test value."""

    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    yield


def _local_postgres_reachable() -> bool:
    host, port = "localhost", 5432
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


async def _ensure_database_exists() -> None:
    """Create this worktree's test database if it doesn't yet exist.

    A no-op for the main checkout, whose `chatspace_test` is expected to
    already exist. `CREATE DATABASE` cannot run inside a transaction, so it
    goes over an AUTOCOMMIT connection to the `postgres` maintenance database.
    """

    if not _WORKTREE_SUFFIX:
        return
    engine = create_async_engine(_PG_ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :n"),
                {"n": _TEST_DB_NAME},
            )
            if not exists:
                # `_TEST_DB_NAME` is a hex-suffixed literal we control, not
                # user input, but quote the identifier defensively anyway.
                await conn.execute(text(f'CREATE DATABASE "{_TEST_DB_NAME}"'))
    finally:
        await engine.dispose()


async def _drop_database() -> None:
    """Best-effort drop of this worktree's test database on session teardown.

    Keeps per-worktree `chatspace_test_<hash>` databases from piling up as the
    workflow churns through worktrees. Never touches the main checkout's DB.
    """

    if not _WORKTREE_SUFFIX:
        return
    from app.db.session import dispose_engine

    await dispose_engine()
    engine = create_async_engine(_PG_ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :n AND pid <> pg_backend_pid()"
                ),
                {"n": _TEST_DB_NAME},
            )
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{_TEST_DB_NAME}"'))
    finally:
        await engine.dispose()


def pytest_sessionstart(session: pytest.Session) -> None:
    """Migrate the test schema to `head` exactly once for the whole run.

    T12's System Admin bootstrap runs a real DB round-trip at every app
    startup, so every `client`/`db_sessionmaker`-based test needs the
    `users` table to exist. Doing that migration once, deterministically,
    *before* any fixture is resolved — rather than lazily inside a
    session-scoped fixture — sidesteps ordering ambiguity between
    fixtures of different scopes (a module/session-scoped fixture and a
    function-scoped one can legitimately run in either order depending on
    what a given test also requests) and the repeated `CREATE TYPE`/`DROP
    TYPE` churn that made a once-per-test migration both slow and,
    empirically, a source of flakiness against a live Postgres.

    A no-op (skipped entirely) when no local test Postgres is reachable —
    DB-backed tests are individually skipped via `postgres_available`,
    matching every other DB-backed fixture in this file.
    """

    session.config._chatspace_pg_available = _local_postgres_reachable()  # type: ignore[attr-defined]
    if not session.config._chatspace_pg_available:  # type: ignore[attr-defined]
        return

    os.environ.update(REQUIRED_ENV)

    from alembic.config import Config

    from alembic import command
    from app.core.config import get_settings

    get_settings.cache_clear()
    # In a worktree, our isolated database may not exist yet — create it
    # before migrating. No-op for the main checkout's `chatspace_test`.
    asyncio.run(_ensure_database_exists())
    command.upgrade(Config("alembic.ini"), "head")


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Downgrade the test schema back to `base`, undoing `pytest_sessionstart`.

    Best-effort: `tests/test_migrations.py` independently drives its own
    full upgrade/downgrade cycles against the same database as part of
    its own tests, so the schema may already be at `base` by the time
    this runs — that's fine, `alembic downgrade base` from `base` is a
    no-op, and this function tolerates it failing outright too (e.g. the
    connection was already torn down some other way).
    """

    if not getattr(session.config, "_chatspace_pg_available", False):
        return

    # A worktree owns its whole database — drop it outright so isolated
    # test databases don't accumulate as the workflow churns worktrees.
    if _WORKTREE_SUFFIX:
        try:
            asyncio.run(_drop_database())
        except Exception:
            pass
        return

    from alembic.config import Config

    from alembic import command

    try:
        command.downgrade(Config("alembic.ini"), "base")
    except Exception:
        pass


async def _reset_users_table() -> None:
    """Delete every row from `users` for the next `client`-fixture test.

    Uses its own throwaway engine rather than the app's cached one, since
    the app's engine/session-factory caches are cleared around each test.
    """

    engine = create_async_engine(_TEST_DATABASE_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM users"))
    finally:
        await engine.dispose()


@pytest.fixture
def client(
    configured_env: None, postgres_available: bool, migrated_db: None
) -> Iterator[TestClient]:
    """A `TestClient` for a fully started app.

    T12's System Admin bootstrap is a non-skippable Phase-0 startup
    routine that runs a real DB round-trip in the app's lifespan — so
    building this app for real requires the `users` table to exist.
    Depends on `migrated_db` so the schema is present (migrated to head,
    incl. 0002) before the app boots and bootstraps — otherwise a prior
    DB test's schema reset would leave `users` absent. Skipped (not
    failed) when no local test Postgres is reachable, mirroring every
    other DB-backed fixture in this file.
    """

    if not postgres_available:
        pytest.skip(
            "local Postgres not reachable on localhost:5432 "
            "(required: T12 System Admin bootstrap runs at app startup)"
        )

    import asyncio

    from app.core.config import get_settings
    from app.db.redis import get_redis_client
    from app.db.session import get_engine, get_sessionmaker

    get_settings.cache_clear()
    get_redis_client.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()

    asyncio.run(_reset_users_table())

    from app.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client

    get_settings.cache_clear()
    get_redis_client.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


@pytest.fixture(scope="session")
def postgres_available() -> bool:
    """Probe once per test session whether the local test Postgres is up.

    DB-backed tests that need a real connection are *skipped* (not
    failed) when it isn't reachable, so the suite stays green in
    environments without a local Postgres (e.g. a bare CI runner) while
    still exercising the real driver wherever one is available.
    """

    host, port = "localhost", 5432
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


async def _reset_schema_and_engine() -> None:
    """Force the test database (and process engine pool) to a known-clean state.

    Three things a crashed/interrupted prior test run can leave behind that
    would otherwise poison every subsequent test:

    1. Half-applied DDL in `public` — e.g. a `CREATE TYPE` that committed
       but the matching `CREATE TABLE`/`alembic_version` bump didn't,
       leaving `relation "users" does not exist` or
       `duplicate key ... pg_type_typname_nsp_index` on the next
       `CREATE TYPE` for the same enum name. `DROP SCHEMA public CASCADE`
       + `CREATE SCHEMA public` unconditionally wipes that out regardless
       of what state it was left in.
    2. A pooled connection on the process-wide `app.db.session.get_engine`
       singleton that was opened *before* the schema reset. asyncpg caches
       type OIDs (incl. enum types) per physical connection; reusing such a
       connection after `DROP SCHEMA ... CASCADE` recreates same-named
       enums under new OIDs, so a stale pooled connection can raise or
       silently misresolve types. Disposing the engine (which `dispose_engine`
       also does) forces a fresh connection, and therefore a fresh OID
       cache, on next use.
    3. A leaked, still-open backend connection from a killed prior test
       process (e.g. a `TestClient` request whose `get_db_session` cleanup
       never ran because the process was killed mid-request) sitting "idle
       in transaction" and holding a lock on a `public`-schema relation.
       Left alone, `DROP SCHEMA public CASCADE` below would block
       indefinitely waiting for that lock — observed in practice as the
       whole suite hanging rather than failing fast. Terminating every
       *other* backend connected to this database first guarantees the
       schema reset can always proceed.
    """

    from app.db.session import dispose_engine

    await dispose_engine()
    engine = create_async_engine(ASYNC_DATABASE_URL)
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND pid <> pg_backend_pid()"
                )
            )
            await conn.commit()
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


@pytest.fixture
def migrated_db(postgres_available: bool) -> Iterator[None]:
    """Run `alembic upgrade head` against a freshly reset local test Postgres.

    Resets the `public` schema (and disposes the process engine singleton)
    both before `upgrade head` and again on teardown — see
    `_reset_schema_and_engine` — so `users`/`sessions` exist for T10's
    real-DB tests without depending on test ordering, a shared
    already-migrated database, or the previous test/run having torn down
    cleanly. A `command.downgrade(cfg, "base")` round-trip alone (the prior
    approach) is not enough: if a prior process was killed mid-`upgrade`,
    there is nothing to "downgrade" from a half-applied state, and the next
    test's `upgrade head` would fail outright.
    """

    if not postgres_available:
        pytest.skip("local Postgres not reachable on localhost:5432")

    from alembic.config import Config

    from alembic import command

    cfg = Config("alembic.ini")

    asyncio.run(_reset_schema_and_engine())
    try:
        command.upgrade(cfg, "head")
    except Exception:
        # Never leave a half-applied schema for the *next* test to trip
        # over — reset immediately rather than only on the happy path.
        asyncio.run(_reset_schema_and_engine())
        raise

    try:
        yield
    finally:
        asyncio.run(_reset_schema_and_engine())


@pytest.fixture
async def db_session(migrated_db: None) -> AsyncIterator[AsyncSession]:
    """A real `AsyncSession` against the migrated local test Postgres.

    Callers commit explicitly (or rely on autoflush) — nothing here wraps
    the test in an outer transaction, matching how `app.db.session` is
    used in the running app (T10 tests exercise real commit/rollback
    behavior of `require_auth`'s revocation checks).
    """

    engine = create_async_engine(ASYNC_DATABASE_URL)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        yield session
    await engine.dispose()


@pytest.fixture(scope="session")
def redis_available() -> bool:
    """Probe once per test session whether the local test Redis is up.

    Mirrors `postgres_available`: Redis-backed tests that need a real
    connection are *skipped* (not failed) when it isn't reachable, so the
    suite stays green on a bare CI runner while still exercising the real
    client wherever a local Redis is available.
    """

    host, port = "localhost", 6379
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False
