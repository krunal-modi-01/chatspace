"""Exercise the generic 500 handler directly.

There is no business route in T01 that can trigger an unhandled exception,
so this test wires the same error-handling plumbing onto a throwaway app
with a route that deliberately raises, proving the handler's contract.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.correlation import set_correlation_id
from app.core.errors import install_error_handlers
from app.core.middleware import correlation_id_middleware


def _build_failing_app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(correlation_id_middleware)
    install_error_handlers(app)

    @app.get("/v1/boom")
    async def boom() -> None:
        raise RuntimeError("sensitive internal detail that must not leak")

    return app


def test_unhandled_exception_returns_problem_json_500() -> None:
    set_correlation_id(None)  # type: ignore[arg-type]
    app = _build_failing_app()

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/v1/boom")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")

    body = response.json()
    assert body["status"] == 500
    assert body["type"] == "https://chatspace.example/problems/internal-error"
    assert "correlation_id" in body and body["correlation_id"]

    serialized = str(body)
    assert "sensitive internal detail" not in serialized
    assert "RuntimeError" not in serialized
