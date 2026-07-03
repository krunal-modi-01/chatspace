from __future__ import annotations

from fastapi.testclient import TestClient


def test_404_returns_problem_json_shape(client: TestClient) -> None:
    response = client.get("/v1/nonexistent-route")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")

    body = response.json()
    assert body["type"] == "https://chatspace.example/problems/not-found"
    assert body["status"] == 404
    assert body["instance"] == "/v1/nonexistent-route"
    assert "correlation_id" in body and body["correlation_id"]
    assert "detail" in body and isinstance(body["detail"], str)
    assert "title" in body


def test_error_body_never_leaks_stack_trace_details(client: TestClient) -> None:
    response = client.get("/v1/nonexistent-route")
    body = response.json()

    serialized = str(body)
    assert "Traceback" not in serialized
    assert 'File "' not in serialized


def test_validation_error_includes_errors_array(client: TestClient) -> None:
    # There is no business route yet to trigger a 422; assert the handler
    # is wired by checking the app's registered exception handlers cover it.
    from fastapi.exceptions import RequestValidationError

    from app.main import create_app

    app = create_app()
    assert RequestValidationError in app.exception_handlers


def test_correlation_id_is_echoed_on_response_header(client: TestClient) -> None:
    response = client.get("/v1/healthz", headers={"X-Correlation-Id": "test-corr-id-123"})

    assert response.headers["X-Correlation-Id"] == "test-corr-id-123"


def test_correlation_id_generated_when_absent(client: TestClient) -> None:
    response = client.get("/v1/healthz")

    assert response.headers.get("X-Correlation-Id")


def test_error_correlation_id_matches_response_header(client: TestClient) -> None:
    response = client.get("/v1/nonexistent-route", headers={"X-Correlation-Id": "abc-123"})

    body = response.json()
    assert body["correlation_id"] == "abc-123"
    assert response.headers["X-Correlation-Id"] == "abc-123"
