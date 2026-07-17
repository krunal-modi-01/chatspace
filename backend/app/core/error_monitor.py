"""Sentry-class error/uptime monitor wiring (T39, technical spec §9).

**Config-driven, OFF by default everywhere, including locally**: this
module is a no-op unless `Settings.error_monitor_dsn` is explicitly set
(CLAUDE.md/`app.core.config`: no default, `None` disables it entirely).
Most local/dev/test environments never set it, matching the constitution's
"basic uptime/error monitor... is enough — no full metrics stack" posture
without forcing every developer to run one.

**No new hard dependency.** `sentry-sdk` is deliberately *not* added to
`pyproject.toml`'s base `dependencies` — only to the optional
`observability` extra (`uv sync --extra observability` / `pip install
chatspace-backend[observability]`) — per CLAUDE.md's guardrail that a new
dependency needs the `dependency-update` skill's vetting checklist, which
this infra task does not carry out. Instead, `configure_error_monitor`
lazily imports `sentry_sdk` only when a DSN is actually configured, and
degrades to a logged no-op (never a startup failure) if the package
happens not to be installed in a given deployment image. This is *not* a
Phase-0 hard prerequisite like transactional email/bootstrap (technical
spec §10) — an observability nicety, not something the app should refuse
to serve over.

**Content hygiene (F68/SEC).** Every event this module would ever send
upstream is scrubbed through the same redaction guard the JSON log
formatter uses (`app.core.redact`) before leaving the process, and
`send_default_pii=False` is passed explicitly to the SDK so it never
opts into attaching request/user PII on its own. The raw
request/headers/cookies interface is dropped outright (not merely
redacted key-by-key) since it is exactly the class of secret
(`Authorization` header, session cookie) this task must never let leak
to a third-party service.

`send_default_pii=False` alone does **not** stop `sentry-sdk` from
capturing per-frame local variables on a traceback (`sentry-sdk>=2.0`
defaults `include_local_variables=True`, independently of that flag) —
`sentry_sdk.init` is called below with `include_local_variables=False`
explicitly, and `_scrub_event` also redacts the rendered exception
message (`exception.values[*].value`, where `capture_exception` puts
`str(exc)`) and strips any per-frame `vars` snapshot as defense-in-depth.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.core.config import Settings
from app.core.redact import redact_mapping, redact_text

if TYPE_CHECKING:
    from sentry_sdk.types import Event, Hint

logger = logging.getLogger(__name__)

# Process-wide: whether `sentry_sdk.init(...)` has actually run. `False`
# both when disabled by config and when enabled-but-the-optional-package
# is missing — `capture_exception` treats both identically (silent no-op).
_configured = False


def _scrub_stacktrace_frames(stacktrace: Any) -> None:
    """Strip local-variable snapshots from every frame of a `stacktrace`.

    `sentry-sdk` can attach a `vars` mapping (arbitrary local variables,
    by name, at the point of the frame) to each frame regardless of
    `send_default_pii` — that flag only governs request/user context, not
    stack locals. Local variable names are not a closed, known vocabulary
    (unlike `app.core.redact`'s field-name deny-list), so partial
    key-based redaction cannot be trusted here: the frame is dropped
    outright as defense-in-depth, on top of passing
    `include_local_variables=False` to `sentry_sdk.init` (the primary
    control — this function must not be relied on alone).
    """

    if not isinstance(stacktrace, dict):
        return
    frames = stacktrace.get("frames")
    if not isinstance(frames, list):
        return
    for frame in frames:
        if isinstance(frame, dict):
            frame.pop("vars", None)


def _scrub_event(event: Event, hint: Hint) -> Event | None:
    """Sentry `before_send` hook: redact the same way every log line is redacted.

    `redact_mapping` already walks nested dict/list values recursively
    (see `app.core.redact`), so this only needs to apply it to the
    top-level containers Sentry's event schema actually carries free-form
    caller data in (`extra`, the rendered `message`) and drop the
    `request` interface outright.

    Defense-in-depth (SEC/T39): also scrubs the rendered exception message
    (`exception.values[*].value` — where `capture_exception` actually puts
    `str(exc)`, since `event["message"]` is only populated by
    `capture_message`) and strips any per-frame local-variable snapshot
    from `exception.values[*].stacktrace` and `threads[*].stacktrace`, in
    case a future SDK version or integration re-attaches locals even with
    `include_local_variables=False` set on `sentry_sdk.init`.
    """

    del hint  # unused: `hint` carries the raw exception object, not data to scrub
    event.pop("request", None)

    extra = event.get("extra")
    if isinstance(extra, dict):
        event["extra"] = redact_mapping(extra)

    message = event.get("message")
    if isinstance(message, str):
        event["message"] = redact_text(message)

    exception = event.get("exception")
    if isinstance(exception, dict):
        values = exception.get("values")
        if isinstance(values, list):
            for exc_value in values:
                if not isinstance(exc_value, dict):
                    continue
                rendered = exc_value.get("value")
                if isinstance(rendered, str):
                    exc_value["value"] = redact_text(rendered)
                _scrub_stacktrace_frames(exc_value.get("stacktrace"))

    threads = event.get("threads")
    if isinstance(threads, dict):
        thread_values = threads.get("values")
        if isinstance(thread_values, list):
            for thread in thread_values:
                if isinstance(thread, dict):
                    _scrub_stacktrace_frames(thread.get("stacktrace"))

    return event


def configure_error_monitor(settings: Settings) -> None:
    """Initialize the error monitor if (and only if) a DSN is configured.

    Never raises: every failure mode here (no DSN, package not installed,
    a bad DSN value the SDK itself rejects) degrades to a logged, disabled
    monitor rather than aborting application startup — see module
    docstring for why this is deliberately not a fail-loud Phase-0 gate
    like `app.services.email.verify_email_config`.
    """

    global _configured

    dsn = settings.error_monitor_dsn
    if dsn is None or not dsn.get_secret_value().strip():
        logger.info("error monitor disabled (no ERROR_MONITOR_DSN configured)")
        _configured = False
        return

    try:
        import sentry_sdk
    except ImportError:
        logger.warning(
            "ERROR_MONITOR_DSN is configured but the optional 'sentry-sdk' "
            "package is not installed; error monitor disabled. Install the "
            "'observability' extra to enable it."
        )
        _configured = False
        return

    try:
        sentry_sdk.init(
            dsn=dsn.get_secret_value(),
            environment=settings.app_env,
            traces_sample_rate=settings.error_monitor_traces_sample_rate,
            send_default_pii=False,
            # `sentry-sdk>=2.0` defaults this to True independently of
            # `send_default_pii` — every captured exception's traceback
            # would otherwise include a snapshot of local variables
            # (raw message content, tokens, emails) from every frame.
            # Must not be relied on alone: `_scrub_event` also strips any
            # `vars` key defensively (see `_scrub_stacktrace_frames`).
            include_local_variables=False,
            before_send=_scrub_event,
        )
    except Exception:  # noqa: BLE001 - never let monitor setup abort startup
        logger.warning("error monitor failed to initialize; disabled", exc_info=False)
        _configured = False
        return

    _configured = True
    logger.info("error monitor configured", extra={"app_env": settings.app_env})


def is_configured() -> bool:
    return _configured


def capture_exception(exc: BaseException) -> None:
    """Report `exc` upstream; a silent no-op when the monitor is disabled.

    Callers (`app.core.errors.unhandled_exception_handler`) call this
    unconditionally for every unhandled 500 — this function alone decides
    whether there is anywhere to send it. Never raises: a reporting
    failure must never itself turn into an unrelated second error.
    """

    if not _configured:
        return
    try:
        import sentry_sdk

        sentry_sdk.capture_exception(exc)
    except Exception:  # noqa: BLE001 - monitoring must never break the request path
        logger.warning("error monitor capture_exception failed", exc_info=False)


def reset_for_tests() -> None:
    """Test-only: reset the module-level configured flag between test cases."""

    global _configured
    _configured = False
