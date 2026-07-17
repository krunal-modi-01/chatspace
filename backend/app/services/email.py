"""Provider-agnostic async SMTP email sender (T11, ADR-0010).

Scope: transport (async SMTP over `aiosmtplib`) + invite/reset templates +
inline send with bounded retry + a Phase-0 fail-loud startup check. This
module deliberately does **not** own invite/reset business logic — token
generation, persistence, expiry policy, and audit events belong to T13
(invites) and T16 (password reset). Callers pass an already-built
`invite_link` / `reset_link` (and its `expires_at`) into the `send_*`
coroutines here.

Fail-loud contract (ADR-0010, technical spec §9):
- No queue-and-forget. Each `send_*` call either succeeds inline (with a
  short bounded retry) or raises `EmailDeliveryError`.
- Callers decide how to surface that failure: the invite flow (F1) turns
  it into a visible `502` to the System Admin; the password-reset flow
  (F15) must preserve the uniform, non-enumerating client response and
  instead turn the same exception into a server-side audit/alert. Both
  policies live with the caller (T13/T16), not here.

Content hygiene (Overview / R24 / this task's scope note): invite and
reset tokens are never stored or logged in the clear, so the rendered
email body embeds only the caller-supplied `invite_link` / `reset_link`
required for the recipient to act on it — nothing else does. Every log
line this module emits carries only non-sensitive metadata (message
type, attempt count, exception type): it never carries the recipient
address, subject, body, link, or token, so a log line from this module
can never leak the raw token/link or PII even if someone widens the log
level.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from enum import StrEnum
from functools import lru_cache

import aiosmtplib

from app.core.config import Settings, get_settings
from app.core.metrics import increment_counter

logger = logging.getLogger(__name__)


class EmailMessageType(StrEnum):
    """Discriminates which template/flow a send call is for (log metadata only)."""

    INVITE = "invite"
    PASSWORD_RESET = "password_reset"


class EmailConfigError(RuntimeError):
    """Raised when SMTP configuration is missing or malformed at startup.

    Transactional email is a Phase-0 non-skippable prerequisite (ADR-0010,
    technical spec §10): the app must fail loudly at startup rather than
    boot into a state where invites/resets silently cannot be delivered.

    `Settings` already makes every `smtp_*` field a required env var (no
    default), so a *missing* variable already fails process startup via
    pydantic validation before `verify_email_config` ever runs. This
    error covers the second layer: a *present-but-unusable* value (e.g.
    a blank string) that a bare "required string field" would accept.
    """


class EmailDeliveryError(RuntimeError):
    """Raised when an email could not be delivered after bounded retry.

    Fail-loud by design: callers must not swallow this into a silent
    queue-and-forget. Never includes the recipient address, subject,
    body, token, or link -- only the message type and attempt count --
    so it is always safe to log or reraise without further scrubbing.
    """

    def __init__(self, message_type: EmailMessageType, attempts: int) -> None:
        super().__init__(
            f"Failed to deliver {message_type.value} email after {attempts} attempt(s)."
        )
        self.message_type = message_type
        self.attempts = attempts


@dataclass(frozen=True, slots=True)
class _RenderedEmail:
    subject: str
    body: str


def _render_invite_email(*, invite_link: str, expires_at: datetime) -> _RenderedEmail:
    """Render the invite email template.

    Deliberately generic: no recipient name, username, or email address
    is interpolated into the body (PII minimization) -- the only dynamic
    values are the single-use invite link and its expiry, both supplied
    by the caller (T13 owns issuing the token and building the link).
    """

    subject = "You're invited to chatspace"
    body = (
        "You have been invited to join a chatspace workspace.\n\n"
        f"Accept your invite: {invite_link}\n\n"
        f"This invite link expires at {expires_at.isoformat()}.\n\n"
        "If you were not expecting this invite, you can ignore this email."
    )
    return _RenderedEmail(subject=subject, body=body)


def _render_password_reset_email(*, reset_link: str, expires_at: datetime) -> _RenderedEmail:
    """Render the password-reset email template.

    Same PII-minimization rule as the invite template: no name/email is
    interpolated into the body, only the caller-supplied reset link and
    its expiry (T16 owns issuing the token and building the link).
    """

    subject = "Reset your chatspace password"
    body = (
        "A password reset was requested for your chatspace account.\n\n"
        f"Reset your password: {reset_link}\n\n"
        f"This reset link expires at {expires_at.isoformat()}.\n\n"
        "If you did not request this, you can safely ignore this email -- "
        "your password will not be changed."
    )
    return _RenderedEmail(subject=subject, body=body)


def verify_email_config(settings: Settings) -> None:
    """Fail-loud Phase-0 startup check: SMTP config must be present and usable.

    Called from `app.main.create_app` so the process refuses to serve
    when email is unconfigured or malformed (ADR-0010: "the app validates
    that email config is present at startup ... and refuses to serve if
    unusable"). Raises `EmailConfigError` -- never logs the SMTP password
    value, only whether it is blank.
    """

    problems: list[str] = []
    if not settings.smtp_host.strip():
        problems.append("SMTP_HOST is blank")
    if not settings.smtp_username.strip():
        problems.append("SMTP_USERNAME is blank")
    if not settings.smtp_password.get_secret_value().strip():
        problems.append("SMTP_PASSWORD is blank")
    if "@" not in settings.smtp_from_address:
        problems.append("SMTP_FROM_ADDRESS is not a valid email address")

    if problems:
        raise EmailConfigError(
            "Email is a non-skippable Phase-0 prerequisite (ADR-0010) but is "
            f"misconfigured: {'; '.join(problems)}."
        )


# Exceptions treated as a retryable/transport failure -- anything from the
# SMTP client library itself, plus the connection-level failures Python's
# socket layer raises that `aiosmtplib` does not always wrap (e.g. a bare
# `ConnectionRefusedError`), plus a bounded-timeout expiry on the attempt.
_RETRYABLE_EXCEPTIONS = (aiosmtplib.SMTPException, OSError, TimeoutError)


class EmailService:
    """Provider-agnostic async SMTP sender for invite/reset email.

    Fail-loud by design (ADR-0010): every public `send_*` coroutine
    either succeeds or raises `EmailDeliveryError` after a short bounded
    retry -- there is no silent queue-and-forget, matching the
    constitution's "no message queue at this scale" constraint.
    """

    def __init__(self, settings: Settings) -> None:
        verify_email_config(settings)
        self._settings = settings

    async def send_invite_email(
        self, *, to_email: str, invite_link: str, expires_at: datetime
    ) -> None:
        """Send an invite email. Raises `EmailDeliveryError` on failure (F1, Flow A.1c)."""

        rendered = _render_invite_email(invite_link=invite_link, expires_at=expires_at)
        await self._send_with_retry(
            to_email=to_email, rendered=rendered, message_type=EmailMessageType.INVITE
        )

    async def send_password_reset_email(
        self, *, to_email: str, reset_link: str, expires_at: datetime
    ) -> None:
        """Send a password-reset email. Raises `EmailDeliveryError` on failure.

        The caller (T16) is responsible for preserving the uniform,
        non-enumerating `202` response to the requester on failure (F15)
        and instead routing this exception to a server-side audit/alert
        -- this method does not know about that policy.
        """

        rendered = _render_password_reset_email(reset_link=reset_link, expires_at=expires_at)
        await self._send_with_retry(
            to_email=to_email,
            rendered=rendered,
            message_type=EmailMessageType.PASSWORD_RESET,
        )

    async def _send_with_retry(
        self, *, to_email: str, rendered: _RenderedEmail, message_type: EmailMessageType
    ) -> None:
        try:
            message = EmailMessage()
            message["From"] = self._settings.smtp_from_address
            message["To"] = to_email
            message["Subject"] = rendered.subject
            message.set_content(rendered.body)
        except (ValueError, UnicodeError) as exc:
            # Malformed input (e.g. a CRLF/header-injection attempt in the
            # recipient address) must still surface as the typed,
            # PII-free `EmailDeliveryError` that callers (T13/T16) already
            # catch -- never a raw stdlib exception. attempts=0 signals the
            # failure happened before any network send was attempted.
            logger.warning(
                "email message construction failed",
                extra={
                    "message_type": message_type.value,
                    "exception_type": type(exc).__name__,
                },
            )
            # This is a real delivery failure (attempts=0, never reached
            # the network) and must still count against the
            # `email-send-failure-rate` alert's numerator (docs/observability
            # /alerts.yaml) -- otherwise a CRLF/header-injection attempt in
            # `to_email` is invisible to that SLI.
            increment_counter("email_send_failure_total", message_type=message_type.value)
            raise EmailDeliveryError(message_type, attempts=0) from exc

        max_attempts = self._settings.smtp_max_attempts
        last_exc: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                await asyncio.wait_for(
                    aiosmtplib.send(
                        message,
                        hostname=self._settings.smtp_host,
                        port=self._settings.smtp_port,
                        username=self._settings.smtp_username,
                        password=self._settings.smtp_password.get_secret_value(),
                        use_tls=self._settings.smtp_use_tls,
                        start_tls=self._settings.smtp_start_tls,
                    ),
                    timeout=self._settings.smtp_send_timeout_seconds,
                )
            except _RETRYABLE_EXCEPTIONS as exc:
                last_exc = exc
                # Never log `to_email`, the subject, the body, the link, or
                # the token -- only message type / attempt / exception type.
                logger.warning(
                    "email send attempt failed",
                    extra={
                        "message_type": message_type.value,
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "exception_type": type(exc).__name__,
                    },
                )
                if attempt < max_attempts:
                    await asyncio.sleep(self._settings.smtp_retry_backoff_seconds * attempt)
                continue
            else:
                logger.info(
                    "email sent",
                    extra={"message_type": message_type.value, "attempt": attempt},
                )
                # Key metric (technical spec §9): "email send success/failure".
                increment_counter("email_send_success_total", message_type=message_type.value)
                return

        logger.error(
            "email delivery failed after bounded retry",
            extra={
                "message_type": message_type.value,
                "attempts": max_attempts,
                "exception_type": type(last_exc).__name__ if last_exc else None,
            },
        )
        increment_counter("email_send_failure_total", message_type=message_type.value)
        raise EmailDeliveryError(message_type, max_attempts) from last_exc


@lru_cache
def get_email_service() -> EmailService:
    """Return the process-wide cached `EmailService` instance.

    Cached like `get_settings` so the fail-loud config check runs once at
    first use; tests that monkeypatch SMTP env vars must call
    `get_email_service.cache_clear()` (mirrors the `get_settings` pattern
    used elsewhere in this codebase).
    """

    return EmailService(get_settings())
