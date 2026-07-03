"""Structured JSON logging configuration.

Every log line carries a `correlation_id` (see `app.core.correlation`) and
never contains message content, tokens, secrets, or PII (CLAUDE.md
GUARDRAILS; technical spec §9 Observability). The redaction guard
(`app.core.redact`) is applied to every extra field and to the rendered
message text before a record is serialized.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.correlation import get_correlation_id
from app.core.redact import redact_text, redact_value

_RESERVED_LOG_RECORD_ATTRS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON with a correlation id."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            # `message` is the rendered log line, not a business field name,
            # so it is only ever redacted for the JWT-shaped defense-in-depth
            # check (redact_text), never wholesale (redact_value would treat
            # the literal key "message" as sensitive content).
            "message": redact_text(record.getMessage()),
            "correlation_id": get_correlation_id(),
        }

        for key, value in record.__dict__.items():
            if key not in _RESERVED_LOG_RECORD_ATTRS and key not in payload:
                payload[key] = redact_value(key, value)

        if record.exc_info:
            # Never serialize a raw traceback or str(exc): both can embed
            # request content, tokens, or PII that redact_text (JWT-shape
            # only) cannot reliably scrub out of free-form text (F68/R24).
            # Record only the exception *type* as a breadcrumb; the
            # correlation id is the join key back to the request.
            exc_type = record.exc_info[0]
            payload["exc_type"] = exc_type.__name__ if exc_type is not None else None

        return json.dumps(payload, default=str)


def configure_logging(log_level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger, replacing any handlers."""

    root = logging.getLogger()
    root.setLevel(log_level.upper())

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())

    root.handlers.clear()
    root.addHandler(handler)
