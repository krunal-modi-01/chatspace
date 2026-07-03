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


def test_readyz_returns_200_when_database_reachable(
    client: TestClient, postgres_available: bool
) -> None:
    """Database probe is real (T03); redis remains stubbed until T05."""

    if not postgres_available:
        pytest.skip("local Postgres not reachable on localhost:5432")

    response = client.get("/v1/readyz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    check_names = {check["name"] for check in body["checks"]}
    assert check_names == {"database", "redis"}
    db_check = next(c for c in body["checks"] if c["name"] == "database")
    redis_check = next(c for c in body["checks"] if c["name"] == "redis")
    assert db_check["status"] == "ok"
    assert redis_check["status"] == "stubbed"


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


async def test_readyz_returns_503_not_500_when_database_connection_is_refused(
    configured_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: a refused Postgres connection must surface as 503, not 500.

    Exercises the real `check_database` probe (not a stub) against a port
    that actively refuses connections, so asyncpg raises a bare
    `ConnectionRefusedError` — an `OSError`, not a `SQLAlchemyError` — which
    must be caught and turned into a 503, not escape as an unhandled 500.
    """

    import socket

    from app.core.config import get_settings
    from app.db.session import dispose_engine, get_engine, get_sessionmaker

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
    with TestClient(app) as test_client:
        response = test_client.get("/v1/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    db_check = next(c for c in body["checks"] if c["name"] == "database")
    assert db_check["status"] == "unavailable"

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    await dispose_engine()


def test_ws_path_is_not_mounted_as_rest_route(client: TestClient) -> None:
    response = client.get("/v1/ws")

    assert response.status_code == 404
