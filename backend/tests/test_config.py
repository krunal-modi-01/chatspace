from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from tests.conftest import REQUIRED_ENV


def test_settings_loads_when_all_required_env_vars_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)

    settings = Settings()  # type: ignore[call-arg]

    assert settings.database_url.get_secret_value() == REQUIRED_ENV["DATABASE_URL"]
    assert settings.jwt_signing_key.get_secret_value() == REQUIRED_ENV["JWT_SIGNING_KEY"]
    assert settings.bootstrap_admin_email == REQUIRED_ENV["BOOTSTRAP_ADMIN_EMAIL"]


@pytest.mark.parametrize("missing_key", sorted(REQUIRED_ENV))
def test_settings_fails_fast_when_a_required_var_is_missing(
    monkeypatch: pytest.MonkeyPatch, missing_key: str
) -> None:
    for key, value in REQUIRED_ENV.items():
        if key != missing_key:
            monkeypatch.setenv(key, value)
    monkeypatch.delenv(missing_key, raising=False)

    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_settings_has_no_hardcoded_secret_defaults() -> None:
    """No secret-bearing field may declare a default; only env can supply it."""

    secret_field_names = {
        "database_url",
        "redis_url",
        "jwt_signing_key",
        "smtp_password",
        "s3_access_key_id",
        "s3_secret_access_key",
        "bootstrap_admin_password",
    }
    for name in secret_field_names:
        field_info = Settings.model_fields[name]
        assert field_info.is_required(), f"{name} must not have a default value"


def test_cors_allowed_origins_parses_csv_string(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://a.example, https://b.example")

    settings = Settings()  # type: ignore[call-arg]

    assert settings.cors_allowed_origins == ["https://a.example", "https://b.example"]


def test_cors_allowed_origins_defaults_to_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)

    settings = Settings()  # type: ignore[call-arg]

    assert settings.cors_allowed_origins == []


def test_cors_wildcard_origin_rejected_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")

    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_cors_wildcard_origin_allowed_outside_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")

    settings = Settings()  # type: ignore[call-arg]

    assert settings.cors_allowed_origins == ["*"]
