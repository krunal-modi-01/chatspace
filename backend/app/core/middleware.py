"""ASGI middleware for request-scoped correlation ids."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

from app.core.correlation import HEADER_NAME, sanitize_correlation_id, set_correlation_id


async def correlation_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Assign a correlation id for the lifetime of the request.

    A client-supplied `X-Correlation-Id` is honored *only* when it is a
    well-formed, bounded token (see `sanitize_correlation_id`) so
    client-side traces can be joined with server logs; otherwise one is
    generated. The id is echoed back on the response and is available to
    the error handlers and the JSON log formatter via a context variable.
    """

    correlation_id = sanitize_correlation_id(request.headers.get(HEADER_NAME))
    set_correlation_id(correlation_id)
    request.state.correlation_id = correlation_id

    response = await call_next(request)
    response.headers[HEADER_NAME] = correlation_id
    return response
