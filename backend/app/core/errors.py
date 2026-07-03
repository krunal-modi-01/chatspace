"""RFC 7807 `application/problem+json` error envelope.

Per the frozen API contract (lines 22-34), every error emitted by the
surface — including framework-level 404/422/500s — conforms to a single
shape:

```json
{
  "type": "https://chatspace.example/problems/<slug>",
  "title": "Human-readable summary of the problem class",
  "status": 422,
  "detail": "Specific, non-sensitive explanation for this occurrence",
  "instance": "/v1/channels/{channel_id}/messages",
  "correlation_id": "01J...",
  "errors": [ { "field": "content", "detail": "must not be empty" } ]
}
```

`type`, `title`, `status`, `detail`, `instance`, and `correlation_id` are
always present; `errors` appears only for 400/422 validation failures.
Error bodies never contain message content, PII, tokens, or secrets.

This module installs generic handlers now (before any business route
exists) so downstream routes/services reuse the same envelope rather than
re-declaring error shapes.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, status
from fastapi.exceptions import RequestValidationError
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.correlation import get_correlation_id

PROBLEM_CONTENT_TYPE = "application/problem+json"
PROBLEM_BASE_URL = "https://chatspace.example/problems"

_TITLES_BY_STATUS: dict[int, str] = {
    status.HTTP_400_BAD_REQUEST: "Bad request",
    status.HTTP_401_UNAUTHORIZED: "Authentication required",
    status.HTTP_403_FORBIDDEN: "Forbidden",
    status.HTTP_404_NOT_FOUND: "Resource not found",
    status.HTTP_409_CONFLICT: "Conflict",
    status.HTTP_410_GONE: "Resource no longer available",
    status.HTTP_413_CONTENT_TOO_LARGE: "Payload too large",
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "Unsupported media type",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "Validation failed",
    status.HTTP_429_TOO_MANY_REQUESTS: "Too many requests",
    status.HTTP_500_INTERNAL_SERVER_ERROR: "Internal server error",
    status.HTTP_503_SERVICE_UNAVAILABLE: "Service unavailable",
}

_SLUGS_BY_STATUS: dict[int, str] = {
    status.HTTP_400_BAD_REQUEST: "bad-request",
    status.HTTP_401_UNAUTHORIZED: "unauthorized",
    status.HTTP_403_FORBIDDEN: "forbidden",
    status.HTTP_404_NOT_FOUND: "not-found",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_410_GONE: "gone",
    status.HTTP_413_CONTENT_TOO_LARGE: "payload-too-large",
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "unsupported-media-type",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "validation-failed",
    status.HTTP_429_TOO_MANY_REQUESTS: "rate-limited",
    status.HTTP_500_INTERNAL_SERVER_ERROR: "internal-error",
    status.HTTP_503_SERVICE_UNAVAILABLE: "service-unavailable",
}


def _title_for(status_code: int) -> str:
    return _TITLES_BY_STATUS.get(status_code, "Unexpected error")


def _slug_for(status_code: int) -> str:
    return _SLUGS_BY_STATUS.get(status_code, "error")


def build_problem_body(
    *,
    status_code: int,
    detail: str,
    instance: str,
    title: str | None = None,
    errors: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Construct a problem+json body per the frozen error contract."""

    body: dict[str, Any] = {
        "type": f"{PROBLEM_BASE_URL}/{_slug_for(status_code)}",
        "title": title or _title_for(status_code),
        "status": status_code,
        "detail": detail,
        "instance": instance,
        "correlation_id": get_correlation_id(),
    }
    if errors is not None:
        body["errors"] = errors
    return body


def _problem_response(
    *,
    status_code: int,
    detail: str,
    instance: str,
    title: str | None = None,
    errors: list[dict[str, str]] | None = None,
) -> JSONResponse:
    body = build_problem_body(
        status_code=status_code,
        detail=detail,
        instance=instance,
        title=title,
        errors=errors,
    )
    return JSONResponse(status_code=status_code, content=body, media_type=PROBLEM_CONTENT_TYPE)


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, HTTPException | StarletteHTTPException)
    detail = exc.detail if isinstance(exc.detail, str) else "An error occurred."
    return _problem_response(
        status_code=exc.status_code,
        detail=detail,
        instance=request.url.path,
    )


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [
        {
            "field": ".".join(str(loc) for loc in error["loc"] if loc != "body"),
            "detail": error["msg"],
        }
        for error in exc.errors()
    ]
    return _problem_response(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail="One or more fields failed validation.",
        instance=request.url.path,
        errors=errors,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Never leak internals (stack traces, exception messages) into the response;
    # the correlation id is the join key back to the (separately logged) detail.
    return _problem_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="An unexpected error occurred. Reference the correlation id for support.",
        instance=request.url.path,
    )


def install_error_handlers(app: FastAPI) -> None:
    """Register the problem+json handlers on the given FastAPI app.

    Both the FastAPI and Starlette `HTTPException` classes are registered
    explicitly: FastAPI wires its own default handlers under *both* keys
    at app construction, and Starlette's own routing (e.g. an unmatched
    route -> 404) raises the plain `starlette.exceptions.HTTPException`,
    not the FastAPI subclass. Overriding only one key would leave the
    other on FastAPI's default (non-problem+json) handler.
    """

    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
