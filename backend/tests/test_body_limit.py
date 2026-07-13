"""Tests for `app.core.body_limit.MaxBodySizeMiddleware` (T28 security review HIGH-1).

`TestMaxBodySizeMiddleware` is pure ASGI-level -- no DB/Redis/S3, no
running app needed: exercises the middleware directly against fake
`scope`/`receive`/`send` callables.

`TestMaxBodySizeMiddlewareFullStack` (T28 code review Major #1) instead
boots the real app via `create_app()` and asserts the immediate
`Content-Length`-precheck `413` response still carries CORS and
correlation-id headers. The unit tests above cannot catch a middleware
*registration-order* regression in `app.main.create_app` -- only a real
`TestClient` request through the actual middleware stack can, since
`app.add_middleware`'s composition rules make registration order, not
just presence, the difference between this response reaching the client
through CORS/correlation or bypassing them entirely.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.body_limit import MAX_REQUEST_BODY_BYTES, BodyTooLargeError, MaxBodySizeMiddleware

pytestmark = pytest.mark.usefixtures("configured_env")

_TEST_ORIGIN = "http://localhost:5173"

_HTTP_SCOPE = {"type": "http", "path": "/v1/media", "headers": []}


def _scope_with_content_length(length: int) -> dict[str, object]:
    return {
        "type": "http",
        "path": "/v1/media",
        "headers": [(b"content-length", str(length).encode())],
    }


class _RecordingSend:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def __call__(self, message: dict[str, object]) -> None:
        self.messages.append(message)


def _receive_sequence(chunks: list[bytes]) -> object:
    remaining = list(chunks)

    async def _receive() -> dict[str, object]:
        if not remaining:
            return {"type": "http.disconnect"}
        body = remaining.pop(0)
        return {"type": "http.request", "body": body, "more_body": bool(remaining)}

    return _receive


class TestMaxBodySizeMiddleware:
    async def test_declared_content_length_over_ceiling_is_rejected_without_invoking_app(
        self,
    ) -> None:
        app_invoked = False

        async def _app(scope: object, receive: object, send: object) -> None:
            nonlocal app_invoked
            app_invoked = True

        middleware = MaxBodySizeMiddleware(_app, max_bytes=100)
        send = _RecordingSend()

        await middleware(_scope_with_content_length(1000), _receive_sequence([b""]), send)

        assert app_invoked is False
        start = next(m for m in send.messages if m["type"] == "http.response.start")
        assert start["status"] == 413
        body = next(m for m in send.messages if m["type"] == "http.response.body")
        assert b"payload" in body["body"].lower() or b"too large" in body["body"].lower()

    async def test_streamed_body_over_ceiling_raises_body_too_large_error(self) -> None:
        async def _app(scope: object, receive: object, send: object) -> None:
            # Simulate a downstream consumer (e.g. the multipart parser)
            # reading the whole streamed body before doing anything else.
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    break
                if not message.get("more_body"):
                    break

        middleware = MaxBodySizeMiddleware(_app, max_bytes=10)
        send = _RecordingSend()
        chunks = [b"0" * 6, b"0" * 6]  # cumulative 12 bytes > 10-byte ceiling

        with pytest.raises(BodyTooLargeError):
            await middleware(_HTTP_SCOPE, _receive_sequence(chunks), send)

    async def test_body_within_ceiling_passes_through_untouched(self) -> None:
        received_bodies: list[bytes] = []

        async def _app(scope: object, receive: object, send: object) -> None:
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    break
                received_bodies.append(message["body"])
                if not message.get("more_body"):
                    break

        middleware = MaxBodySizeMiddleware(_app, max_bytes=1000)
        send = _RecordingSend()

        await middleware(_HTTP_SCOPE, _receive_sequence([b"hello", b"world"]), send)

        assert b"".join(received_bodies) == b"helloworld"

    async def test_non_http_scope_passes_through_untouched(self) -> None:
        app_invoked = False

        async def _app(scope: object, receive: object, send: object) -> None:
            nonlocal app_invoked
            app_invoked = True

        middleware = MaxBodySizeMiddleware(_app, max_bytes=10)
        await middleware({"type": "lifespan"}, _receive_sequence([]), _RecordingSend())

        assert app_invoked is True


@pytest.fixture
def cors_configured_client(
    monkeypatch: pytest.MonkeyPatch, postgres_available: bool, migrated_db: None
) -> Iterator[TestClient]:
    """A `TestClient` for the real app with a concrete `CORS_ALLOWED_ORIGINS`.

    Mirrors `test_deps_auth.py`'s `broken_redis_client` fixture pattern:
    builds the app directly (rather than via the shared `client` fixture)
    so this one env var can be overridden before `create_app()` reads
    settings. Needs a real, non-wildcard origin configured so
    `CORSMiddleware` actually has something to match `_TEST_ORIGIN`
    against and add `Access-Control-Allow-Origin` to the response.
    """

    if not postgres_available:
        pytest.skip("local Postgres not reachable on localhost:5432")

    from app.core.config import get_settings
    from app.db.redis import get_redis_client
    from app.db.session import get_engine, get_sessionmaker
    from app.main import create_app

    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", _TEST_ORIGIN)
    get_settings.cache_clear()
    get_redis_client.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client

    get_settings.cache_clear()
    get_redis_client.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


class TestMaxBodySizeMiddlewareFullStack:
    """Full-stack regression test for T28 code review Major #1.

    Without this, a middleware-registration-order regression in
    `app.main.create_app` (e.g. re-adding `MaxBodySizeMiddleware` *last*,
    making it outermost again) would be invisible to this file's ASGI-level
    unit tests, which never exercise the real middleware stack.
    """

    def test_oversized_content_length_413_still_carries_cors_and_correlation_headers(
        self, migrated_db: None, cors_configured_client: TestClient
    ) -> None:
        oversized_content_length = str(MAX_REQUEST_BODY_BYTES + 1)

        response = cors_configured_client.post(
            "/v1/media",
            headers={
                "Origin": _TEST_ORIGIN,
                "Content-Length": oversized_content_length,
                "Content-Type": "multipart/form-data; boundary=x",
            },
            content=b"",
        )

        assert response.status_code == 413
        assert response.headers.get("access-control-allow-origin") == _TEST_ORIGIN
        assert "x-correlation-id" in response.headers
        assert response.headers["x-correlation-id"]

        body = response.json()
        assert body["correlation_id"]
