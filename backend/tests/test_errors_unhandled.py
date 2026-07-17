"""Exercise the generic 500 handler directly.

There is no business route in T01 that can trigger an unhandled exception,
so this test wires the same error-handling plumbing onto a throwaway app
with a route that deliberately raises, proving the handler's contract.
"""

from __future__ import annotations

import pytest
from app.core.metrics import reset_metrics
from app.core.metrics import snapshot as metrics_snapshot
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


def test_unhandled_exception_increments_http_error_total_and_reports_to_monitor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T39 (code review finding 1): the generic 500 handler must both

    - increment the content-free `http_error_total` counter (feeding the
      `error-rate-spike` alert, `docs/observability/alerts.yaml`), and
    - forward the exception to the Sentry-class monitor via
      `capture_exception` (a no-op when unconfigured, but always called).
    """

    set_correlation_id(None)  # type: ignore[arg-type]
    app = _build_failing_app()

    captured: list[BaseException] = []
    monkeypatch.setattr("app.core.errors.capture_exception", captured.append)

    reset_metrics()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/v1/boom")

    assert response.status_code == 500

    counters = metrics_snapshot()["counters"]["http_error_total"]
    assert counters["endpoint_class=/v1/boom,exception_type=RuntimeError,status_code=500"] == 1

    assert len(captured) == 1
    assert isinstance(captured[0], RuntimeError)
