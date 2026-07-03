"""Acceptance test (F68/R24): a log emitted while logging a message body or
a JWT-shaped value must never contain the raw content or token — the JSON
formatter must apply the redaction guard before serializing.
"""

from __future__ import annotations

import json
import logging
import sys

from app.core.correlation import set_correlation_id
from app.core.logging import JsonFormatter

# Not a real credential: synthetic value only shaped like a JWT/opaque
# token, built via join so it doesn't read as a `key = "..."` assignment.
_fake_jwt_shape = ".".join(["abcd1234wxyz", "mnop5678qrst", "uvwx9012ijkl"])
_raw_message_body = "meet me at the usual place, don't tell anyone"


def _format_record(**extra: object) -> dict:
    record = logging.LogRecord(
        name="app.services.message",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="message send accepted",
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    formatted = JsonFormatter().format(record)
    return json.loads(formatted)


def test_logging_message_content_field_does_not_leak_raw_body() -> None:
    set_correlation_id("corr-abc-123")

    payload = _format_record(content=_raw_message_body, channel_id="chan-1")

    serialized = json.dumps(payload)
    assert _raw_message_body not in serialized
    assert payload["content"] == "[REDACTED]"
    assert payload["channel_id"] == "chan-1"
    assert payload["correlation_id"] == "corr-abc-123"


def test_logging_token_field_does_not_leak_raw_token() -> None:
    set_correlation_id("corr-xyz-789")

    payload = _format_record(access_token=_fake_jwt_shape, user_id="user-1")

    serialized = json.dumps(payload)
    assert _fake_jwt_shape not in serialized
    assert payload["access_token"] == "[REDACTED]"
    assert payload["user_id"] == "user-1"


def test_logging_jwt_shaped_value_embedded_in_message_text_is_redacted() -> None:
    set_correlation_id("corr-msg-1")
    record = logging.LogRecord(
        name="app.core.security",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=f"issued session for bearer {_fake_jwt_shape}",
        args=(),
        exc_info=None,
    )

    formatted = JsonFormatter().format(record)

    assert _fake_jwt_shape not in formatted
    assert "[REDACTED]" in formatted


def test_every_log_line_carries_the_active_correlation_id() -> None:
    set_correlation_id("corr-join-key")

    payload = _format_record()

    assert payload["correlation_id"] == "corr-join-key"


def test_nested_extra_payload_does_not_leak_secrets_or_content() -> None:
    set_correlation_id("corr-nested-1")

    payload = _format_record(
        payload={"password": "hunter2", "content": _raw_message_body, "message_id": "m-9"},
    )

    serialized = json.dumps(payload)
    assert "hunter2" not in serialized
    assert _raw_message_body not in serialized
    assert payload["payload"]["message_id"] == "m-9"


def test_exception_traceback_is_not_serialized_only_its_type() -> None:
    set_correlation_id("corr-exc-1")
    secret_in_exc = "meet me at the docks"
    try:
        raise ValueError(f"failed to persist message: {secret_in_exc}")
    except ValueError:
        record = logging.LogRecord(
            name="app.services.message",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="persist failed",
            args=(),
            exc_info=sys.exc_info(),
        )

    formatted = JsonFormatter().format(record)
    payload = json.loads(formatted)

    assert secret_in_exc not in formatted
    assert payload["exc_type"] == "ValueError"
    assert "exc_info" not in payload
