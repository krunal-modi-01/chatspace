from __future__ import annotations

import pytest

from app.core.password_policy import (
    MIN_LENGTH,
    PasswordPolicyError,
    check_password_policy,
    enforce_password_policy,
)


def test_check_password_policy_accepts_compliant_candidate() -> None:
    assert check_password_policy("abc123") == []


def test_check_password_policy_rejects_too_short() -> None:
    violations = check_password_policy("a1")

    assert any("6 characters" in v for v in violations)


def test_min_length_is_six() -> None:
    assert MIN_LENGTH == 6


def test_check_password_policy_rejects_all_digits() -> None:
    violations = check_password_policy("123456")

    assert any("letter and one digit" in v for v in violations)


def test_check_password_policy_rejects_all_letters() -> None:
    violations = check_password_policy("abcdef")

    assert any("letter and one digit" in v for v in violations)


def test_check_password_policy_rejects_blank() -> None:
    violations = check_password_policy("      ")

    assert any("blank" in v for v in violations)


def test_enforce_password_policy_raises_with_field_level_errors() -> None:
    with pytest.raises(PasswordPolicyError) as exc_info:
        enforce_password_policy("a1", field_name="new_password")

    errors = exc_info.value.errors
    assert all(e["field"] == "new_password" for e in errors)
    assert all(set(e) == {"field", "detail"} for e in errors)


def test_enforce_password_policy_passes_silently_when_compliant() -> None:
    enforce_password_policy("abc123", field_name="password")


def test_enforce_password_policy_defaults_field_name_to_password() -> None:
    with pytest.raises(PasswordPolicyError) as exc_info:
        enforce_password_policy("a1")

    assert exc_info.value.errors[0]["field"] == "password"


def test_password_policy_error_message_never_echoes_candidate() -> None:
    non_compliant_candidate = "a1"
    try:
        enforce_password_policy(non_compliant_candidate)
    except PasswordPolicyError as exc:
        serialized = str(exc.errors)
        assert non_compliant_candidate not in serialized
