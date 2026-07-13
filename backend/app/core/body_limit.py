"""Global request-body-size ceiling (T28 security review HIGH-1).

Starlette's own multipart parser (`starlette.formparsers.MultiPartParser`)
applies a size ceiling to non-file form fields only (`max_part_size`,
1 MB default) -- the file-part branch streams bytes straight into a
`SpooledTemporaryFile` (rolling over to local disk past 1 MB) with **no
upper bound at all**. `app.services.media.read_upload_within_limit`'s
per-kind cap only runs *after* FastAPI/Starlette has already fully parsed
(and, for an oversized body, already fully buffered/spooled to disk) the
multipart body -- far too late to prevent a disk-exhaustion DoS on the
single-Docker-host deployment this project targets (CLAUDE.md's
1,000-user-scale architecture notes: app/DB/Redis share one host's disk).

This module closes that gap with a pure-ASGI middleware that runs *before*
Starlette's body/multipart parsing gets a chance to buffer anything:

1. A `Content-Length` header that already declares an over-ceiling size is
   rejected immediately, before a single body byte is read.
2. For bodies without a (trustworthy) `Content-Length` -- chunked
   transfer-encoding, or a client that simply lies about the header -- the
   raw ASGI `receive` stream is wrapped to count actual bytes as they
   arrive and abort as soon as the cumulative total crosses the ceiling.

Deliberately global (not scoped to `/v1/media`): a single ceiling sized to
comfortably fit the largest legitimate per-kind media cap (video, 200 MB,
`app.core.media_validation.SIZE_CAP_BYTES_BY_KIND`) plus multipart framing
overhead, so it never interferes with a real upload, while still bounding
the worst case any request body -- media or otherwise -- can force onto
this host's disk/memory before any route handler's own validation runs.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.correlation import get_correlation_id

logger = logging.getLogger(__name__)

# Comfortably above the largest per-kind media cap (video, 200 MB) to
# leave headroom for multipart boundary/header framing overhead, without
# being so generous that it stops bounding the worst case.
MAX_REQUEST_BODY_BYTES = 210 * 1024 * 1024

_PROBLEM_TYPE = "https://chatspace.example/problems/payload-too-large"
_PROBLEM_TITLE = "Payload too large"
_PROBLEM_DETAIL = "Request body exceeds the maximum allowed size."


class BodyTooLargeError(Exception):
    """Raised when a streamed request body exceeds `MAX_REQUEST_BODY_BYTES`.

    Registered as a FastAPI exception handler (see `app.core.errors`) so
    it renders the standard `413` problem+json shape via the normal
    exception-handling path: this is only ever raised while `self._app`
    (the rest of the ASGI stack, including routing/dependency resolution
    and Starlette's `ExceptionMiddleware`) is still executing inside
    `MaxBodySizeMiddleware.__call__`, so that machinery is available to
    catch it -- unlike the `Content-Length` pre-check path below, which
    rejects before `self._app` is ever invoked and therefore builds its
    `413` response directly.
    """


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", ()):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


def _problem_body(instance: str) -> dict[str, Any]:
    return {
        "type": _PROBLEM_TYPE,
        "title": _PROBLEM_TITLE,
        "status": 413,
        "detail": _PROBLEM_DETAIL,
        "instance": instance,
        "correlation_id": get_correlation_id(),
    }


class MaxBodySizeMiddleware:
    """Reject request bodies larger than `max_bytes` before they reach the app.

    See module docstring for the two enforcement layers. Placed in
    `app.main.create_app` as the *first*-added middleware (T28 code review
    Major #1), which Starlette's `add_middleware` composition rules make
    the *innermost* of the app's user middlewares -- positioned just
    outside Starlette's `ExceptionMiddleware` and *inside* CORS/correlation.
    This keeps both of this middleware's response paths correct: the
    streamed-overflow `BodyTooLargeError`, raised from within a request
    still being parsed/routed, is caught by the normal exception-handler
    dispatch (registered inside `ExceptionMiddleware`) rather than bubbling
    past it; and the immediate `Content-Length`-precheck `413` (built and
    sent directly via `send()`, bypassing `self._app`/`ExceptionMiddleware`
    entirely) still passes back out through CORS and correlation-id, since
    those wrap this middleware rather than the reverse. Registering this
    middleware *last* would make it outermost instead, silently dropping
    CORS headers and the correlation id from the precheck `413` response.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int = MAX_REQUEST_BODY_BYTES) -> None:
        self._app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        declared = _content_length(scope)
        if declared is not None and declared > self._max_bytes:
            logger.warning(
                "request rejected: declared Content-Length exceeds the global body-size ceiling",
                extra={"path": scope.get("path"), "max_bytes": self._max_bytes},
            )
            await self._send_413(scope, send)
            return

        total = 0

        async def guarded_receive() -> Message:
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body") or b"")
                if total > self._max_bytes:
                    logger.warning(
                        "request aborted: streamed body exceeded the global body-size ceiling",
                        extra={"path": scope.get("path"), "max_bytes": self._max_bytes},
                    )
                    raise BodyTooLargeError(f"request body exceeded {self._max_bytes} bytes.")
            return message

        await self._app(scope, guarded_receive, send)

    async def _send_413(self, scope: Scope, send: Send) -> None:
        payload = json.dumps(_problem_body(scope.get("path", ""))).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/problem+json")],
            }
        )
        await send({"type": "http.response.body", "body": payload})
