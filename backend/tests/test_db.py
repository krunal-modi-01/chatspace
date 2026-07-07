from __future__ import annotations

import socket
import time
from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import build_engine_kwargs
from app.db.session import dispose_engine, get_db_session, get_engine, get_sessionmaker
from app.services.readiness import ReadinessStatus, check_database

if TYPE_CHECKING:
    from app.core.config import Settings


def _find_closed_port() -> int:
    """Return a TCP port on localhost that is guaranteed to refuse connections.

    Binds an ephemeral port and immediately closes it — nothing else in the
    test process holds it open, so a subsequent connect attempt gets a real
    `ECONNREFUSED` (not a timeout, not a listening service), which is exactly
    the failure mode this file needs to exercise deterministically.
    """

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(autouse=True)
def _reset_engine_cache() -> Iterator[None]:
    """Ensure each test starts with no cached engine/settings from a prior test.

    `get_settings`, `get_engine`, and `get_sessionmaker` are all
    process-wide `lru_cache`s (by design — one pool per instance); tests
    that monkeypatch env vars must not leak a stale binding into the next
    test.
    """

    from app.core.config import get_settings

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    yield
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


def _build_settings(**overrides: object) -> Settings:
    from app.core.config import Settings

    defaults: dict[str, object] = {
        "database_url": "postgresql+asyncpg://user:pass@240.0.0.1:5432/does-not-exist",
        "redis_url": "redis://localhost:6379/1",
        "jwt_signing_key": "test",
        "smtp_host": "localhost",
        "smtp_port": 1025,
        "smtp_username": "test",
        "smtp_password": "test",
        "smtp_from_address": "no-reply@chatspace.example",
        "s3_endpoint_url": "http://localhost:9000",
        "s3_bucket_name": "bucket",
        "s3_access_key_id": "key",
        "s3_secret_access_key": "secret",
        "bootstrap_admin_email": "admin@chatspace.example",
        "bootstrap_admin_password": "pw",
        "bootstrap_admin_username": "admin",
        "bootstrap_admin_first_name": "System",
        "bootstrap_admin_last_name": "Admin",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


class TestEngineConfiguration:
    """Pool size and statement timeout must be config-driven (T03)."""

    def test_pool_settings_come_from_settings(self) -> None:
        settings = _build_settings(db_pool_size=7, db_max_overflow=2, db_pool_timeout_seconds=1.5)

        kwargs = build_engine_kwargs(settings)

        assert kwargs["pool_size"] == 7
        assert kwargs["max_overflow"] == 2
        assert kwargs["pool_timeout"] == 1.5

    def test_statement_timeout_is_set_via_server_settings(self) -> None:
        settings = _build_settings(db_statement_timeout_ms=2500, db_connect_timeout_seconds=2.0)

        kwargs = build_engine_kwargs(settings)
        connect_args = kwargs["connect_args"]

        assert connect_args["server_settings"]["statement_timeout"] == "2500"
        assert connect_args["timeout"] == 2.0

    def test_creating_engine_does_not_connect(self) -> None:
        """Constructing the engine must never block on a live connection.

        `create_async_engine` is lazy — the pool is populated on first
        use — so this must succeed even with a garbage URL host, proving
        engine construction alone can't hang application startup.
        """

        from app.db.engine import create_engine

        settings = _build_settings()

        engine = create_engine(settings)
        assert engine is not None


class TestGetDbSessionDependency:
    async def test_yields_an_async_session_and_commits_on_success(
        self, configured_env: None, postgres_available: bool
    ) -> None:
        if not postgres_available:
            pytest.skip("local Postgres not reachable on localhost:5432")

        session_gen = get_db_session()
        session = await anext(session_gen)
        assert isinstance(session, AsyncSession)
        result = await session.execute(text("SELECT 1"))
        assert result.scalar_one() == 1

        # Drive the generator to completion so it commits/closes cleanly.
        with pytest.raises(StopAsyncIteration):
            await anext(session_gen)

        await dispose_engine()

    async def test_rolls_back_on_exception_and_still_closes(
        self, configured_env: None, postgres_available: bool
    ) -> None:
        if not postgres_available:
            pytest.skip("local Postgres not reachable on localhost:5432")

        session_gen = get_db_session()
        session = await anext(session_gen)

        with pytest.raises(RuntimeError):
            await session_gen.athrow(RuntimeError("boom"))

        assert not session.in_transaction()
        await dispose_engine()


class TestCheckDatabaseProbe:
    async def test_returns_ok_when_postgres_reachable(
        self, configured_env: None, postgres_available: bool
    ) -> None:
        if not postgres_available:
            pytest.skip("local Postgres not reachable on localhost:5432")

        check = await check_database()

        assert check.status == ReadinessStatus.OK
        assert check.name == "database"

    async def test_returns_unavailable_fast_when_postgres_unreachable(
        self, monkeypatch: pytest.MonkeyPatch, configured_env: None
    ) -> None:
        """Fails fast (no hang) against an unreachable host (F: readyz probe)."""

        from app.core.config import get_settings

        monkeypatch.setenv(
            "DATABASE_URL",
            "postgresql+asyncpg://user:pass@240.0.0.1:5432/does-not-exist",
        )
        monkeypatch.setenv("DB_CONNECT_TIMEOUT_SECONDS", "1")
        get_settings.cache_clear()
        get_engine.cache_clear()
        get_sessionmaker.cache_clear()

        started = time.monotonic()
        check = await check_database()
        elapsed = time.monotonic() - started

        assert check.status == ReadinessStatus.UNAVAILABLE
        assert check.name == "database"
        # Bounded well above the 1s connect timeout, far below a network
        # stack's default multi-minute TCP retry — proves "fast error, no
        # hang" rather than merely "eventually errors".
        assert elapsed < 5

        get_settings.cache_clear()
        await dispose_engine()

    async def test_returns_unavailable_when_postgres_port_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, configured_env: None
    ) -> None:
        """Regression: a closed port raises a bare `ConnectionRefusedError`.

        Unlike the black-hole-IP case above (which times out), asyncpg
        raises `ConnectionRefusedError` — an `OSError`, not a
        `SQLAlchemyError` — when the host is reachable but nothing is
        listening on the port. `check_database` must catch this and report
        UNAVAILABLE rather than letting it propagate as an unhandled
        exception (which the readyz endpoint would turn into a 500).
        """

        from app.core.config import get_settings

        closed_port = _find_closed_port()
        monkeypatch.setenv(
            "DATABASE_URL",
            f"postgresql+asyncpg://user:pass@127.0.0.1:{closed_port}/does-not-exist",
        )
        monkeypatch.setenv("DB_CONNECT_TIMEOUT_SECONDS", "1")
        get_settings.cache_clear()
        get_engine.cache_clear()
        get_sessionmaker.cache_clear()

        check = await check_database()

        assert check.status == ReadinessStatus.UNAVAILABLE
        assert check.name == "database"

        get_settings.cache_clear()
        await dispose_engine()

    async def test_unavailable_detail_never_leaks_connection_string(
        self, monkeypatch: pytest.MonkeyPatch, configured_env: None
    ) -> None:
        from app.core.config import get_settings

        monkeypatch.setenv(
            "DATABASE_URL",
            "postgresql+asyncpg://secretuser:secretpass@240.0.0.1:5432/does-not-exist",
        )
        monkeypatch.setenv("DB_CONNECT_TIMEOUT_SECONDS", "1")
        get_settings.cache_clear()
        get_engine.cache_clear()
        get_sessionmaker.cache_clear()

        check = await check_database()

        assert "secretuser" not in check.detail
        assert "secretpass" not in check.detail

        get_settings.cache_clear()
        await dispose_engine()
