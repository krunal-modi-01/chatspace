"""Request correlation id: context-local storage + generation.

The correlation id is a non-PII request identifier that appears on every
log line and every RFC 7807 error body (API contract, line 34 / F68).
"""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar

_correlation_id_ctx: ContextVar[str | None] = ContextVar("correlation_id", default=None)

HEADER_NAME = "X-Correlation-Id"

# A client-supplied correlation id is only honored if it is a short, safe
# token: bounded length and a conservative charset. This prevents a client
# from injecting oversized or control-character values that would bloat log
# lines and be reflected verbatim into responses/logs.
_MAX_CORRELATION_ID_LEN = 128
_CORRELATION_ID_RE = re.compile(rf"^[A-Za-z0-9._-]{{1,{_MAX_CORRELATION_ID_LEN}}}$")


def generate_correlation_id() -> str:
    """Generate a new opaque, non-PII correlation id."""

    return uuid.uuid4().hex


def sanitize_correlation_id(value: str | None) -> str:
    """Return a safe correlation id.

    Honors a well-formed client-supplied value (bounded length, safe
    charset) so client-side traces can be joined with server logs;
    otherwise generates a fresh id. Never trusts arbitrary client input.
    """

    if value is not None and _CORRELATION_ID_RE.match(value):
        return value
    return generate_correlation_id()


def set_correlation_id(value: str) -> None:
    _correlation_id_ctx.set(value)


def get_correlation_id() -> str | None:
    return _correlation_id_ctx.get()
