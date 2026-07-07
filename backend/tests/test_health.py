from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services.readiness import ReadinessCheck, ReadinessStatus


def test_healthz_returns_200_ok(client: TestClient) -> None:
    response = client.get("/v1/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_is_plain_json_not_problem_json(client: TestClient) -> None:
    response = client.get("/v1/healthz")

    assert "application/problem+json" not in response.headers["content-type"]


def test_readyz_returns_200_when_database_and_redis_reachable(
    client: TestClient, postgres_available: bool, redis_available: bool
) -> None:
    """Both the database (T03) and Redis (T05) probes are real."""

    if not postgres_available:
        pytest.skip("local Postgres not reachable on localhost:5432")
    if not redis_available:
        pytest.skip("local Redis not reachable on localhost:6379")

    response = client.get("/v1/readyz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    check_names = {check["name"] for check in body["checks"]}
    assert check_names == {"database", "redis"}
    db_check = next(c for c in body["checks"] if c["name"] == "database")
    redis_check = next(c for c in body["checks"] if c["name"] == "redis")
    assert db_check["status"] == "ok"
    assert redis_check["status"] == "ok"


def test_readyz_returns_503_when_redis_unreachable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Redis down degrades readyz to 503 — it must never crash the process (T05).

    Redis must be reachable at *startup* (via the `client` fixture) since
    it's checked incidentally by other app wiring; this test breaks it
    only afterwards, at request time — the scenario `/v1/readyz` is meant
    to degrade gracefully from (Redis being down does not gate T12's
    bootstrap, which only needs Postgres).
    """

    import socket

    from app.core.config import get_settings
    from app.db.redis import get_redis_client

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        closed_port = sock.getsockname()[1]

    monkeypatch.setenv("REDIS_URL", f"redis://127.0.0.1:{closed_port}/0")
    monkeypatch.setenv("REDIS_CONNECT_TIMEOUT_SECONDS", "1")
    get_settings.cache_clear()
    get_redis_client.cache_clear()

    response = client.get("/v1/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    redis_check = next(c for c in body["checks"] if c["name"] == "redis")
    assert redis_check["status"] == "unavailable"

    get_settings.cache_clear()
    get_redis_client.cache_clear()


def test_readyz_returns_503_when_a_dependency_is_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _unavailable_db() -> ReadinessCheck:
        return ReadinessCheck(
            name="database",
            status=ReadinessStatus.UNAVAILABLE,
            detail="Postgres unreachable",
        )

    monkeypatch.setattr("app.api.health.check_database", _unavailable_db)

    response = client.get("/v1/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    db_check = next(c for c in body["checks"] if c["name"] == "database")
    assert db_check["status"] == "unavailable"


def test_readyz_returns_503_not_500_when_database_connection_is_refused(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: a refused Postgres connection must surface as 503, not 500.

    Exercises the real `check_database` probe (not a stub) against a port
    that actively refuses connections, so asyncpg raises a bare
    `ConnectionRefusedError` — an `OSError`, not a `SQLAlchemyError` — which
    must be caught and turned into a 503, not escape as an unhandled 500.

    Postgres must be reachable at *startup* (via the `client` fixture) so
    the T12 System Admin bootstrap can succeed — this test breaks the
    connection only afterwards, at request time, which is the scenario
    `check_database`/`/v1/readyz` are meant to degrade gracefully from. A
    DB that is already unreachable *at startup* is a different, fatal
    scenario covered by `tests/test_bootstrap.py`.
    """

    import socket

    from app.core.config import get_settings
    from app.db.session import get_engine, get_sessionmaker
    from tests.conftest import REQUIRED_ENV

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

    response = client.get("/v1/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    db_check = next(c for c in body["checks"] if c["name"] == "database")
    assert db_check["status"] == "unavailable"

    # Restore a real, reachable DATABASE_URL *before* returning, rather than
    # relying on `monkeypatch`'s own teardown timing relative to the
    # `client` fixture's — the `client` fixture downgrades the schema via
    # its own fresh DB connection on teardown, which must not race against
    # this test's broken-port override still being in effect.
    monkeypatch.setenv("DATABASE_URL", REQUIRED_ENV["DATABASE_URL"])
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


def test_ws_path_is_not_mounted_as_rest_route(client: TestClient) -> None:
    response = client.get("/v1/ws")

    assert response.status_code == 404
