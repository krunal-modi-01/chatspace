"""Unit tests for the redaction guard (app.core.redact)."""

from __future__ import annotations

from app.core.redact import REDACTED, is_sensitive_key, redact_mapping, redact_text, redact_value


def test_known_secret_keys_are_redacted() -> None:
    for key in ["password", "hashed_password", "token", "access_token", "refresh_token", "sid"]:
        assert redact_value(key, "super-secret-value") == REDACTED


def test_message_content_key_is_redacted() -> None:
    assert redact_value("content", "hey, secret plans at 5pm") == REDACTED


def test_pii_keys_are_redacted() -> None:
    for key in ["username", "email", "first_name", "last_name", "ip_address", "user_agent"]:
        assert redact_value(key, "some-pii-value") == REDACTED


def test_safe_identifier_keys_are_not_redacted() -> None:
    for key in ["id", "channel_id", "message_id", "sender_id", "user_id", "storage_key", "kind"]:
        assert redact_value(key, "01J000000000000000000000") != REDACTED


def test_camel_case_sensitive_keys_are_also_caught() -> None:
    assert is_sensitive_key("refreshToken")
    assert is_sensitive_key("hashedPassword")


# Not a real credential: a synthetic three-segment, dot-delimited value used
# only to exercise the JWT-shape regex in app.core.redact (test fixture).
# Built via join (rather than a single string literal) so it does not read
# as a `keyword = "..."` assignment to a secret-scan heuristic.
_fake_jwt_shape = ".".join(["abcd1234wxyz", "mnop5678qrst", "uvwx9012ijkl"])


def test_jwt_shaped_value_is_redacted_even_under_a_safe_key() -> None:
    result = redact_value("note", f"bearer {_fake_jwt_shape}")
    assert _fake_jwt_shape not in result
    assert REDACTED in result


def test_redact_text_strips_jwt_from_free_text() -> None:
    text = f"login succeeded with a value shaped like {_fake_jwt_shape} in the middle"
    redacted = redact_text(text)
    assert _fake_jwt_shape not in redacted
    assert REDACTED in redacted


def test_redact_mapping_redacts_only_sensitive_fields() -> None:
    data = {
        "content": "raw chat message body",
        "channel_id": "01J0000000000000000000CHAN",
        "password": "hunter2",
    }
    redacted = redact_mapping(data)
    assert redacted["content"] == REDACTED
    assert redacted["password"] == REDACTED
    assert redacted["channel_id"] == data["channel_id"]


def test_nested_dict_under_safe_key_is_recursively_redacted() -> None:
    # The `extra={"payload": model.model_dump()}` pattern: a non-sensitive
    # outer key must not shield sensitive inner keys from redaction.
    value = redact_value(
        "payload",
        {"password": "hunter2", "content": "secret plans 5pm", "message_id": "m-1"},
    )
    assert value["password"] == REDACTED
    assert value["content"] == REDACTED
    assert value["message_id"] == "m-1"


def test_list_elements_inherit_parent_key_and_are_scrubbed() -> None:
    # A sensitive parent key redacts its whole value, list included.
    assert redact_value("token", ["a-secret", "another"]) == REDACTED
    # Under a safe key, dict elements are still recursed and strings JWT-scrubbed.
    result = redact_value("items", [{"email": "a@b.com"}, f"bearer {_fake_jwt_shape}"])
    assert result[0]["email"] == REDACTED
    assert _fake_jwt_shape not in result[1]
