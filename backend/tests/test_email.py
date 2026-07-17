from __future__ import annotations

import logging
from datetime import UTC, datetime

import aiosmtplib
import pytest
from app.core.metrics import reset_metrics
from app.core.metrics import snapshot as metrics_snapshot

from app.core.config import Settings
from app.services.email import (
    EmailConfigError,
    EmailDeliveryError,
    EmailMessageType,
    EmailService,
    get_email_service,
    verify_email_config,
)


def _build_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "database_url": "postgresql+asyncpg://user:pass@localhost:5425/does-not-exist",
        "redis_url": "redis://localhost:6380/1",
        "jwt_signing_key": "test",
        "smtp_host": "localhost",
        "smtp_port": 1025,
        "smtp_username": "test",
        "smtp_password": "test-smtp-password",
        "smtp_from_address": "no-reply@chatspace.example",
        "s3_endpoint_url": "http://localhost:9000",
        "s3_bucket_name": "bucket",
        "s3_access_key_id": "key",
        "s3_secret_access_key": "secret",
        "bootstrap_admin_email": "admin@chatspace.example",
        "bootstrap_admin_password": "pw",
        "bootstrap_admin_username": "admin",
        "bootstrap_admin_first_name": "System",
        "bootstrap_admin_last_name": "Admin",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


class TestVerifyEmailConfig:
    def test_passes_with_valid_settings(self) -> None:
        verify_email_config(_build_settings())  # must not raise

    def test_rejects_blank_host(self) -> None:
        with pytest.raises(EmailConfigError, match="SMTP_HOST is blank"):
            verify_email_config(_build_settings(smtp_host="   "))

    def test_rejects_blank_username(self) -> None:
        with pytest.raises(EmailConfigError, match="SMTP_USERNAME is blank"):
            verify_email_config(_build_settings(smtp_username=""))

    def test_rejects_blank_password(self) -> None:
        with pytest.raises(EmailConfigError, match="SMTP_PASSWORD is blank"):
            verify_email_config(_build_settings(smtp_password="  "))

    def test_rejects_malformed_from_address(self) -> None:
        with pytest.raises(EmailConfigError, match="SMTP_FROM_ADDRESS"):
            verify_email_config(_build_settings(smtp_from_address="not-an-email"))

    def test_error_message_never_contains_the_password_value(self) -> None:
        with pytest.raises(EmailConfigError) as excinfo:
            verify_email_config(_build_settings(smtp_password=" "))

        assert "test-smtp-password" not in str(excinfo.value)

    def test_out_of_range_port_rejected_by_settings_itself(self) -> None:
        """`smtp_port` bounds are enforced by the `Settings` field, not this helper."""

        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _build_settings(smtp_port=70000)

    def test_email_service_construction_runs_the_check(self) -> None:
        with pytest.raises(EmailConfigError):
            EmailService(_build_settings(smtp_host=""))


class TestGetEmailServiceCaching:
    def test_returns_cached_instance_and_clears(self, configured_env: None) -> None:
        from app.core.config import get_settings

        get_settings.cache_clear()
        get_email_service.cache_clear()
        try:
            first = get_email_service()
            second = get_email_service()
            assert first is second
        finally:
            get_email_service.cache_clear()
            get_settings.cache_clear()


@pytest.fixture
def settings() -> Settings:
    return _build_settings()


@pytest.fixture
def service(settings: Settings) -> EmailService:
    return EmailService(settings)


class TestSendInviteEmail:
    async def test_sends_successfully_on_first_attempt(
        self, service: EmailService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[dict[str, object]] = []

        async def fake_send(message: object, **kwargs: object) -> tuple[dict, str]:
            calls.append(kwargs)
            return {}, "OK"

        monkeypatch.setattr("app.services.email.aiosmtplib.send", fake_send)

        reset_metrics()
        await service.send_invite_email(
            to_email="invitee@example.com",
            invite_link="https://chatspace.example/invite/abc123token",
            expires_at=datetime(2026, 7, 13, tzinfo=UTC),
        )

        assert len(calls) == 1
        assert calls[0]["hostname"] == "localhost"

        # Key metric (technical spec §9): "email send success/failure"
        # (T39; code review finding 1).
        counters = metrics_snapshot()["counters"]["email_send_success_total"]
        assert counters["message_type=invite"] == 1

    async def test_raises_email_delivery_error_after_exhausting_bounded_retry(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = EmailService(_build_settings(smtp_max_attempts=3, smtp_retry_backoff_seconds=0))
        attempts: list[int] = []

        async def always_fail(message: object, **kwargs: object) -> tuple[dict, str]:
            attempts.append(1)
            raise aiosmtplib.SMTPConnectError("connection refused")

        monkeypatch.setattr("app.services.email.aiosmtplib.send", always_fail)

        reset_metrics()
        with pytest.raises(EmailDeliveryError) as excinfo:
            await service.send_invite_email(
                to_email="invitee@example.com",
                invite_link="https://chatspace.example/invite/abc123token",
                expires_at=datetime(2026, 7, 13, tzinfo=UTC),
            )

        assert len(attempts) == 3
        assert excinfo.value.message_type == EmailMessageType.INVITE
        assert excinfo.value.attempts == 3

        # Key metric (technical spec §9): "email send success/failure",
        # feeding the `email-send-failure-rate` alert (T39; code review
        # finding 1).
        counters = metrics_snapshot()["counters"]["email_send_failure_total"]
        assert counters["message_type=invite"] == 1

    async def test_recovers_after_a_transient_failure_within_the_retry_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = EmailService(_build_settings(smtp_max_attempts=3, smtp_retry_backoff_seconds=0))
        attempts: list[int] = []

        async def fail_once_then_succeed(message: object, **kwargs: object) -> tuple[dict, str]:
            attempts.append(1)
            if len(attempts) < 2:
                raise aiosmtplib.SMTPConnectError("transient")
            return {}, "OK"

        monkeypatch.setattr("app.services.email.aiosmtplib.send", fail_once_then_succeed)

        await service.send_invite_email(
            to_email="invitee@example.com",
            invite_link="https://chatspace.example/invite/abc123token",
            expires_at=datetime(2026, 7, 13, tzinfo=UTC),
        )

        assert len(attempts) == 2

    async def test_never_returns_the_raw_token_or_link_error_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = EmailService(_build_settings(smtp_max_attempts=1))

        async def always_fail(message: object, **kwargs: object) -> tuple[dict, str]:
            raise aiosmtplib.SMTPConnectError("connection refused")

        monkeypatch.setattr("app.services.email.aiosmtplib.send", always_fail)

        secret_link = "https://chatspace.example/invite/super-secret-token-xyz"
        with pytest.raises(EmailDeliveryError) as excinfo:
            await service.send_invite_email(
                to_email="invitee@example.com",
                invite_link=secret_link,
                expires_at=datetime(2026, 7, 13, tzinfo=UTC),
            )

        assert secret_link not in str(excinfo.value)
        assert "invitee@example.com" not in str(excinfo.value)


class TestTransportTlsKwargs:
    async def test_passes_configured_use_tls_start_tls_and_port_to_aiosmtplib(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression test for the STARTTLS/implicit-TLS transport bug.

        `aiosmtplib.send` must receive the settings-driven `use_tls`,
        `start_tls`, and `port` kwargs -- previously `start_tls` was never
        passed at all, silently leaving it opportunistic (`None`) and
        breaking delivery against any 587-STARTTLS relay or local MailHog.
        """

        service = EmailService(
            _build_settings(smtp_use_tls=False, smtp_start_tls=True, smtp_port=587)
        )
        calls: list[dict[str, object]] = []

        async def fake_send(message: object, **kwargs: object) -> tuple[dict, str]:
            calls.append(kwargs)
            return {}, "OK"

        monkeypatch.setattr("app.services.email.aiosmtplib.send", fake_send)

        await service.send_invite_email(
            to_email="invitee@example.com",
            invite_link="https://chatspace.example/invite/abc123token",
            expires_at=datetime(2026, 7, 13, tzinfo=UTC),
        )

        assert len(calls) == 1
        assert calls[0]["use_tls"] is False
        assert calls[0]["start_tls"] is True
        assert calls[0]["port"] == 587

    async def test_passes_configured_implicit_tls_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = EmailService(
            _build_settings(smtp_use_tls=True, smtp_start_tls=False, smtp_port=465)
        )
        calls: list[dict[str, object]] = []

        async def fake_send(message: object, **kwargs: object) -> tuple[dict, str]:
            calls.append(kwargs)
            return {}, "OK"

        monkeypatch.setattr("app.services.email.aiosmtplib.send", fake_send)

        await service.send_invite_email(
            to_email="invitee@example.com",
            invite_link="https://chatspace.example/invite/abc123token",
            expires_at=datetime(2026, 7, 13, tzinfo=UTC),
        )

        assert calls[0]["use_tls"] is True
        assert calls[0]["start_tls"] is False
        assert calls[0]["port"] == 465

    def test_rejects_both_tls_modes_enabled_at_once(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="mutually exclusive"):
            _build_settings(smtp_use_tls=True, smtp_start_tls=True)


class TestMalformedRecipientFailsLoudWithTypedError:
    async def test_crlf_in_recipient_raises_email_delivery_error_not_value_error(
        self, service: EmailService
    ) -> None:
        """Message construction happens inside the fail-loud contract.

        A malformed `to_email` (header/CRLF injection attempt) must raise
        the typed `EmailDeliveryError` that callers (T13/T16) are
        documented to catch, not a raw `ValueError` from `EmailMessage`.
        """

        with pytest.raises(EmailDeliveryError):
            await service.send_invite_email(
                to_email="attacker@example.com\r\nBcc: victim@example.com",
                invite_link="https://chatspace.example/invite/abc123token",
                expires_at=datetime(2026, 7, 13, tzinfo=UTC),
            )

    async def test_crlf_in_recipient_still_increments_failure_counter(
        self, service: EmailService
    ) -> None:
        """The pre-network 'message construction failed' path (attempts=0)
        is a real delivery failure and must still count against the
        `email-send-failure-rate` alert's numerator (T39 code review
        finding 1) -- not just the post-retry-exhaustion path.
        """

        reset_metrics()
        with pytest.raises(EmailDeliveryError):
            await service.send_invite_email(
                to_email="attacker@example.com\r\nBcc: victim@example.com",
                invite_link="https://chatspace.example/invite/abc123token",
                expires_at=datetime(2026, 7, 13, tzinfo=UTC),
            )

        counters = metrics_snapshot()["counters"]["email_send_failure_total"]
        assert counters["message_type=invite"] == 1


class TestSendPasswordResetEmail:
    async def test_sends_successfully(
        self, service: EmailService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_send(message: object, **kwargs: object) -> tuple[dict, str]:
            return {}, "OK"

        monkeypatch.setattr("app.services.email.aiosmtplib.send", fake_send)

        await service.send_password_reset_email(
            to_email="user@example.com",
            reset_link="https://chatspace.example/reset/def456token",
            expires_at=datetime(2026, 7, 6, 13, tzinfo=UTC),
        )

    async def test_raises_email_delivery_error_on_exhaustion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = EmailService(_build_settings(smtp_max_attempts=2, smtp_retry_backoff_seconds=0))

        async def always_fail(message: object, **kwargs: object) -> tuple[dict, str]:
            raise TimeoutError("boom")

        monkeypatch.setattr("app.services.email.aiosmtplib.send", always_fail)

        with pytest.raises(EmailDeliveryError) as excinfo:
            await service.send_password_reset_email(
                to_email="user@example.com",
                reset_link="https://chatspace.example/reset/def456token",
                expires_at=datetime(2026, 7, 6, 13, tzinfo=UTC),
            )

        assert excinfo.value.message_type == EmailMessageType.PASSWORD_RESET


class TestLoggingNeverLeaksSensitiveData:
    async def test_failure_log_records_never_contain_link_token_or_email(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        service = EmailService(_build_settings(smtp_max_attempts=2, smtp_retry_backoff_seconds=0))
        secret_link = "https://chatspace.example/invite/leak-check-token-999"
        recipient = "sensitive-recipient@example.com"

        async def always_fail(message: object, **kwargs: object) -> tuple[dict, str]:
            raise aiosmtplib.SMTPConnectError("connection refused")

        monkeypatch.setattr("app.services.email.aiosmtplib.send", always_fail)

        with caplog.at_level(logging.WARNING, logger="app.services.email"):
            with pytest.raises(EmailDeliveryError):
                await service.send_invite_email(
                    to_email=recipient,
                    invite_link=secret_link,
                    expires_at=datetime(2026, 7, 13, tzinfo=UTC),
                )

        for record in caplog.records:
            rendered = record.getMessage()
            assert secret_link not in rendered
            assert recipient not in rendered
            for value in vars(record).values():
                if isinstance(value, str):
                    assert secret_link not in value
                    assert recipient not in value

    async def test_success_log_records_never_contain_link_or_email(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        service = EmailService(_build_settings())
        secret_link = "https://chatspace.example/reset/leak-check-token-000"
        recipient = "another-recipient@example.com"

        async def fake_send(message: object, **kwargs: object) -> tuple[dict, str]:
            return {}, "OK"

        monkeypatch.setattr("app.services.email.aiosmtplib.send", fake_send)

        with caplog.at_level(logging.INFO, logger="app.services.email"):
            await service.send_password_reset_email(
                to_email=recipient,
                reset_link=secret_link,
                expires_at=datetime(2026, 7, 6, 13, tzinfo=UTC),
            )

        for record in caplog.records:
            for value in vars(record).values():
                if isinstance(value, str):
                    assert secret_link not in value
                    assert recipient not in value


class TestAppStartupFailsLoudOnBadEmailConfig:
    """Phase-0 non-skippable prerequisite: app refuses to start without usable SMTP config."""

    def test_create_app_raises_when_smtp_host_is_blank(
        self, monkeypatch: pytest.MonkeyPatch, configured_env: None
    ) -> None:
        import sys

        from app.core.config import get_settings

        monkeypatch.setenv("SMTP_HOST", "   ")
        get_settings.cache_clear()
        sys.modules.pop("app.main", None)

        with pytest.raises(EmailConfigError):
            import app.main  # noqa: F401

        sys.modules.pop("app.main", None)
        get_settings.cache_clear()

    def test_create_app_succeeds_with_valid_smtp_config(self, configured_env: None) -> None:
        from app.core.config import get_settings

        get_settings.cache_clear()

        from app.main import create_app

        app = create_app()
        assert app is not None

        get_settings.cache_clear()


class TestTemplateRendering:
    def test_invite_template_contains_link_and_expiry_but_no_pii(self) -> None:
        from app.services.email import _render_invite_email

        rendered = _render_invite_email(
            invite_link="https://chatspace.example/invite/tok123",
            expires_at=datetime(2026, 7, 13, tzinfo=UTC),
        )

        assert "https://chatspace.example/invite/tok123" in rendered.body
        assert "2026-07-13" in rendered.body
        assert "@" not in rendered.subject

    def test_reset_template_contains_link_and_expiry_but_no_pii(self) -> None:
        from app.services.email import _render_password_reset_email

        rendered = _render_password_reset_email(
            reset_link="https://chatspace.example/reset/tok456",
            expires_at=datetime(2026, 7, 6, 13, tzinfo=UTC),
        )

        assert "https://chatspace.example/reset/tok456" in rendered.body
        assert "2026-07-06" in rendered.body
        assert "@" not in rendered.subject
