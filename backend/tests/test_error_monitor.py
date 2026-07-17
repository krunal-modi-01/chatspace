"""Unit tests for `app.core.error_monitor` (T39, technical spec §9).

No real Sentry DSN or network access — asserts the config-driven,
off-by-default posture and the content-scrubbing `before_send` hook. The
optional `sentry_sdk` package is not installed in this project's base
dependency set (see `pyproject.toml`'s `observability` extra), so the
"DSN configured but package missing" path is exercised for real here
rather than mocked.
"""

from __future__ import annotations

import importlib.util

import pytest

from app.core import error_monitor
from app.core.config import Settings
from tests.conftest import REQUIRED_ENV

_SENTRY_SDK_INSTALLED = importlib.util.find_spec("sentry_sdk") is not None


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    error_monitor.reset_for_tests()
    yield
    error_monitor.reset_for_tests()


def _settings(**overrides: object) -> Settings:
    kwargs = {k.lower(): v for k, v in REQUIRED_ENV.items()}
    kwargs.update(overrides)
    return Settings(**kwargs)  # type: ignore[arg-type]


class TestOffByDefault:
    def test_no_dsn_leaves_monitor_disabled(self) -> None:
        error_monitor.configure_error_monitor(_settings())

        assert error_monitor.is_configured() is False

    def test_blank_dsn_leaves_monitor_disabled(self) -> None:
        error_monitor.configure_error_monitor(_settings(error_monitor_dsn="   "))

        assert error_monitor.is_configured() is False

    def test_capture_exception_is_a_silent_noop_when_disabled(self) -> None:
        error_monitor.configure_error_monitor(_settings())

        # Must not raise even though nothing is configured to receive it.
        error_monitor.capture_exception(ValueError("boom"))


class TestDsnConfiguredButPackageMissing:
    def test_degrades_to_disabled_without_installed_sentry_sdk(self) -> None:
        """`sentry-sdk` is an optional extra (pyproject.toml), not a base
        dependency — this environment does not have it installed, so a
        configured DSN must degrade to a logged no-op rather than crash
        startup.
        """

        error_monitor.configure_error_monitor(
            _settings(error_monitor_dsn="https://public@example.ingest.sentry.io/1")
        )

        assert error_monitor.is_configured() is False


class TestScrubEvent:
    def test_drops_the_request_interface_outright(self) -> None:
        event = {"request": {"headers": {"Authorization": "Bearer secret"}}, "message": "hi"}

        scrubbed = error_monitor._scrub_event(event, {})

        assert "request" not in scrubbed

    def test_redacts_sensitive_keys_in_extra(self) -> None:
        event = {"extra": {"password": "hunter2", "channel_id": "01J..."}}

        scrubbed = error_monitor._scrub_event(event, {})

        assert scrubbed["extra"]["password"] == "[REDACTED]"
        assert scrubbed["extra"]["channel_id"] == "01J..."

    def test_redacts_jwt_shaped_substrings_in_message(self) -> None:
        # Not a real token — three dot-separated base64url-ish segments,
        # deliberately not prefixed "eyJ", purely to exercise
        # `app.core.redact`'s shape-based (not prefix-based) JWT matcher.
        token_shaped = "headerpart.payloadpart.signaturepart"
        event = {"message": f"failed while holding token {token_shaped}"}

        scrubbed = error_monitor._scrub_event(event, {})

        assert token_shaped not in scrubbed["message"]

    def test_redacts_jwt_shaped_substring_in_exception_value(self) -> None:
        """`capture_exception` (the only real call site) renders `str(exc)`
        into `exception.values[*].value`, never `event["message"]`
        (that field is only populated by `capture_message`) — so this is
        the field that must actually be scrubbed for the real code path.
        Regression test for the HIGH security finding: a token embedded
        in an exception's message (e.g. `raise InvalidTokenError(f"token
        {token} expired")`) must never reach the third-party monitor.
        """

        token_shaped = "headerpart.payloadpart.signaturepart"
        event = {
            "exception": {
                "values": [{"type": "InvalidTokenError", "value": f"token {token_shaped} expired"}]
            }
        }

        scrubbed = error_monitor._scrub_event(event, {})

        rendered = scrubbed["exception"]["values"][0]["value"]
        assert token_shaped not in rendered

    def test_strips_local_variable_snapshots_from_exception_frames(self) -> None:
        """`sentry-sdk` attaches a `vars` mapping (raw local variables) to
        every stack frame by default, independent of `send_default_pii` —
        `include_local_variables=False` on `sentry_sdk.init` is the primary
        control, but `_scrub_event` must also strip it defensively in case
        a future SDK version or a different integration re-attaches it.
        """

        event = {
            "exception": {
                "values": [
                    {
                        "type": "ValueError",
                        "value": "boom",
                        "stacktrace": {
                            "frames": [
                                {
                                    "function": "send_dm_message",
                                    "vars": {
                                        "content": "the raw chat message body",
                                        "hashed_password": "$2b$...",
                                        "token": "headerpart.payloadpart.signaturepart",
                                    },
                                }
                            ]
                        },
                    }
                ]
            }
        }

        scrubbed = error_monitor._scrub_event(event, {})

        frame = scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]
        assert "vars" not in frame

    def test_strips_local_variable_snapshots_from_thread_frames(self) -> None:
        event = {
            "threads": {
                "values": [
                    {
                        "stacktrace": {
                            "frames": [{"function": "worker", "vars": {"email": "a@b.com"}}]
                        }
                    }
                ]
            }
        }

        scrubbed = error_monitor._scrub_event(event, {})

        frame = scrubbed["threads"]["values"][0]["stacktrace"]["frames"][0]
        assert "vars" not in frame


@pytest.mark.skipif(
    not _SENTRY_SDK_INSTALLED,
    reason="optional 'observability' extra ('sentry-sdk') not installed",
)
class TestRealSdkNeverLeaksLocalsOrMessage:
    """End-to-end regression test using the real `sentry_sdk`, guarded to
    skip when the optional `observability` extra is not installed (it is
    not part of the base dependency set — see module docstring). Uses a
    custom in-memory transport so no network call is made; this exercises
    the actual `sentry_sdk.init(...)` config (`include_local_variables`)
    together with `_scrub_event`, not just the scrub function in isolation.
    """

    def test_sensitive_local_and_exception_message_never_appear_in_captured_event(self) -> None:
        import sentry_sdk
        from sentry_sdk.transport import Transport

        captured: list[dict[str, object]] = []

        class _CapturingTransport(Transport):
            def capture_envelope(self, envelope):  # type: ignore[no-untyped-def]
                for item in envelope.items:
                    if item.data_category == "error":
                        captured.append(item.payload.json)

        settings = _settings(error_monitor_dsn="https://public@example.ingest.sentry.io/1")
        sentry_sdk.init(
            dsn=settings.error_monitor_dsn.get_secret_value(),
            transport=_CapturingTransport(),
            send_default_pii=False,
            include_local_variables=False,
            before_send=error_monitor._scrub_event,
        )

        token_value = "headerpart.payloadpart.signaturepart"

        def _inner() -> None:
            password_hash = "$2b$12$abcdefghijklmnopqrstuv"  # noqa: F841 - local on purpose
            raise ValueError(f"token {token_value} rejected")

        try:
            _inner()
        except ValueError as exc:
            sentry_sdk.capture_exception(exc)

        sentry_sdk.flush()

        assert len(captured) == 1
        exc_value = captured[0]["exception"]["values"][0]
        frames = exc_value["stacktrace"]["frames"]

        # The two fields the HIGH security finding is about: the rendered
        # exception message (where `capture_exception` puts `str(exc)`)
        # and any per-frame local-variable snapshot. Deliberately not
        # asserting against `str(captured[0])` as a whole: `sentry-sdk`
        # also attaches source-code context lines (`context_line`/
        # `pre_context`) around each frame by default, which is a
        # separate, lower-risk feature (source text, not a live runtime
        # secret value) outside this finding's scope, and would produce
        # a misleading failure here purely because this test's own source
        # line literally contains the token string.
        assert token_value not in exc_value["value"]
        assert not any("vars" in frame for frame in frames)
