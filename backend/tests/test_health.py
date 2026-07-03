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


def test_readyz_returns_200_with_stubbed_checks(client: TestClient) -> None:
    response = client.get("/v1/readyz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    check_names = {check["name"] for check in body["checks"]}
    assert check_names == {"database", "redis"}
    for check in body["checks"]:
        assert check["status"] == "stubbed"


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


def test_ws_path_is_not_mounted_as_rest_route(client: TestClient) -> None:
    response = client.get("/v1/ws")

    assert response.status_code == 404
