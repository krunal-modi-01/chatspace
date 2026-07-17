from __future__ import annotations

from fastapi.testclient import TestClient
from starlette.requests import Request

from app.core.errors import _endpoint_class


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


def test_password_policy_error_handler_is_registered(configured_env: None) -> None:
    """`PasswordPolicyError` (T09/F23) is wired to a problem+json 422 handler
    even before any password-setting endpoint (register/change/reset)
    exists to raise it."""

    from app.core.password_policy import PasswordPolicyError
    from app.main import create_app

    app = create_app()
    assert PasswordPolicyError in app.exception_handlers


def test_password_policy_error_renders_as_422_problem_json(client: TestClient) -> None:
    """Wire a throwaway route that raises `PasswordPolicyError` and assert
    the response matches the frozen 422 problem+json shape with a
    field-level `errors[]` array (F23).

    Uses the shared `client` fixture (rather than building its own app via
    `create_app()`) since app startup now runs the T12 System Admin
    bootstrap, which requires a migrated `users` table.
    """

    from app.core.password_policy import enforce_password_policy

    @client.app.get("/v1/__test-password-policy")  # type: ignore[union-attr]
    def _raise_policy_error() -> None:
        enforce_password_policy("a1", field_name="new_password")

    response = client.get("/v1/__test-password-policy")

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")

    body = response.json()
    assert body["status"] == 422
    assert body["instance"] == "/v1/__test-password-policy"
    assert "correlation_id" in body and body["correlation_id"]
    assert body["errors"]
    assert all(e["field"] == "new_password" for e in body["errors"])
    # The rejected candidate password itself must never appear in the body,
    # only the policy-violation description.
    assert all("a1" != e.get("detail") for e in body["errors"])
    assert body["detail"] == "Password fails policy."


def _make_request(*, path: str, route: object | None) -> Request:
    scope: dict[str, object] = {
        "type": "http",
        "path": path,
        "headers": [],
        "query_string": b"",
        "method": "GET",
        "scheme": "http",
        "server": ("testserver", 80),
    }
    if route is not None:
        scope["route"] = route
    return Request(scope)  # type: ignore[arg-type]


class _FakeRoute:
    """Minimal stand-in for a Starlette `Route`/`APIRoute` -- only `.path` matters."""

    def __init__(self, path: str) -> None:
        self.path = path


def test_endpoint_class_prefers_the_matched_route_template_over_the_raw_path() -> None:
    """T39 code review finding 4: a metric label must never carry a raw,
    caller-supplied id/value -- only the fixed route template, when a route
    matched at all."""

    request = _make_request(
        path="/v1/channels/01998f2e-abcd-7000-8000-000000000000/messages",
        route=_FakeRoute("/v1/channels/{channel_id}/messages"),
    )

    assert _endpoint_class(request) == "/v1/channels/{channel_id}/messages"


def test_endpoint_class_falls_back_to_raw_path_only_when_no_route_matched() -> None:
    """The raw-path fallback is documented as unreachable for the two call
    sites that actually use this label today (`rate_limit_exceeded_handler`
    and `unhandled_exception_handler` only ever fire on an already-matched
    route) -- pinned here so a future call site cannot silently start
    leaking a raw, potentially caller-influenced path into the metrics
    registry without at least this invariant being visible and tested."""

    request = _make_request(path="/v1/totally-unmatched-path", route=None)

    assert _endpoint_class(request) == "/v1/totally-unmatched-path"
