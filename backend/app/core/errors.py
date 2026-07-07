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

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, status
from fastapi.exceptions import RequestValidationError
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.correlation import HEADER_NAME, get_correlation_id
from app.core.pagination import PaginationError
from app.core.password_policy import PasswordPolicyError
from app.core.request_body import MalformedBodyError
from app.services.auth import MustChangePasswordError

logger = logging.getLogger(__name__)

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
    type_slug: str | None = None,
    errors: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Construct a problem+json body per the frozen error contract.

    `type_slug` overrides the status-code-derived slug (`_slug_for`) for
    cases where the frozen contract needs two distinct `type` values under
    the same HTTP status — e.g. `403` is overloaded by T15's
    `must_change_password` compensating control (ADR-0009) alongside its
    existing "account deactivated" meaning; a distinct `type` lets a
    tolerant client tell the two apart without a status-code collision.
    """

    body: dict[str, Any] = {
        "type": f"{PROBLEM_BASE_URL}/{type_slug or _slug_for(status_code)}",
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
    type_slug: str | None = None,
    errors: list[dict[str, str]] | None = None,
) -> JSONResponse:
    body = build_problem_body(
        status_code=status_code,
        detail=detail,
        instance=instance,
        title=title,
        type_slug=type_slug,
        errors=errors,
    )
    response = JSONResponse(status_code=status_code, content=body, media_type=PROBLEM_CONTENT_TYPE)
    # The unhandled-exception (500) handler runs inside Starlette's
    # ServerErrorMiddleware, which sits outside the correlation-id HTTP
    # middleware that normally echoes this header — so set it here to keep
    # the header present on every error, where tracing matters most.
    response.headers[HEADER_NAME] = body["correlation_id"]
    return response


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


async def password_policy_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Turn a `PasswordPolicyError` (F23) into the frozen 422 problem+json shape.

    Reused by every password-setting endpoint (register, password change,
    password-reset confirm) via a single `PasswordPolicyError` raised from
    `app.core.password_policy.enforce_password_policy` — never the raw
    candidate password, which this handler never sees or logs.
    """

    assert isinstance(exc, PasswordPolicyError)
    return _problem_response(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail="Password fails policy.",
        instance=request.url.path,
        errors=exc.errors,
    )


async def must_change_password_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Turn a `MustChangePasswordError` into the ADR-0009 compensating-control response.

    T15 CONTRACT-GAP (documented in the frozen contract's T15 notice): the
    contract does not define a wire shape for this outcome. This
    implements the contract's option 2 — block with a distinct
    `problem+json` `type` at `403` (`.../problems/must-change-password`)
    rather than overloading the generic `.../problems/forbidden` type
    that `403` otherwise means ("account deactivated"). This is a
    contract *addition* (new, additive `type` slug only — no existing
    status/shape changes) and should be confirmed with the API owner
    before this becomes load-bearing for a client.
    """

    assert isinstance(exc, MustChangePasswordError)
    return _problem_response(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "Your password must be changed before you can log in. "
            "Complete a password change to continue."
        ),
        instance=request.url.path,
        title="Password change required",
        type_slug="must-change-password",
    )


async def malformed_body_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Turn a `MalformedBodyError` into the frozen `400` problem+json shape.

    Reused by every endpoint (T16's `/v1/auth/password*`, and future
    endpoints) that manually validates its body via
    `app.core.request_body.parse_body` to distinguish a malformed body
    (`400`) from a business-rule failure like password policy (`422`) —
    see that module's docstring for why FastAPI's automatic body
    validation cannot make this distinction on its own.
    """

    assert isinstance(exc, MalformedBodyError)
    return _problem_response(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Request body is malformed.",
        instance=request.url.path,
        errors=exc.errors,
    )


async def pagination_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Turn a `PaginationError` (malformed cursor / invalid limit) into `400`.

    Per the Pagination contract clause, a malformed `cursor` or an invalid
    `limit` is a `400`, not the generic `422` validation shape — this is a
    distinct handler (not `RequestValidationError`) so the status code
    stays exactly `400` as the contract requires. Never echoes the raw
    (client-supplied, opaque) cursor value back in the response.
    """

    assert isinstance(exc, PaginationError)
    return _problem_response(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=exc.detail,
        instance=request.url.path,
        errors=[{"field": exc.field, "detail": exc.detail}],
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Never leak internals (stack traces, exception messages) into the response;
    # the correlation id is the join key back to the (separately logged) detail.
    # Only the exception *type* and request path are logged — never
    # `str(exc)` or a formatted traceback, since an exception message can
    # incidentally embed request data (content, tokens, PII) that the
    # redaction guard cannot reliably scrub out of free-form text (F68/R24).
    logger.error(
        "unhandled exception",
        extra={"exception_type": type(exc).__name__, "path": request.url.path},
    )
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
    app.add_exception_handler(PasswordPolicyError, password_policy_exception_handler)
    app.add_exception_handler(MustChangePasswordError, must_change_password_error_handler)
    app.add_exception_handler(MalformedBodyError, malformed_body_exception_handler)
    app.add_exception_handler(PaginationError, pagination_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
