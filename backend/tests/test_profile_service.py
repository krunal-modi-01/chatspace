"""Unit tests for `app.services.profile` (T17) — no DB/HTTP required.

Exercises the immutable-field guard (F20) and the empty-name guard (F19)
independently of FastAPI/HTTP, plus `apply_profile_update`'s partial-update
semantics (unset fields untouched, `avatar_url: null` clears the avatar).
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.ids import generate_id
from app.models.user import User
from app.schemas.users import ProfileUpdateRequest
from app.services.profile import (
    EmptyNameError,
    ImmutableFieldChangeError,
    apply_profile_update,
    validate_profile_update,
)

_PLACEHOLDER_HASH_VALUE = "not-a-real-hash-value"


def _make_user(**overrides: object) -> User:
    defaults: dict[str, object] = dict(
        id=generate_id(),
        username="alice",
        email="alice@example.com",
        hashed_password=_PLACEHOLDER_HASH_VALUE,
        first_name="Alice",
        last_name="Ng",
        avatar_url=None,
        is_active=True,
        is_system_admin=False,
        must_change_password=False,
        email_verified=True,
        last_seen=None,
        created_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return User(**defaults)  # type: ignore[arg-type]


class TestValidateProfileUpdateImmutableFields:
    def test_changing_email_raises(self) -> None:
        user = _make_user()
        request = ProfileUpdateRequest(email="new@example.com")

        try:
            validate_profile_update(user, request)
            raise AssertionError("expected ImmutableFieldChangeError")
        except ImmutableFieldChangeError as exc:
            assert exc.field == "email"

    def test_changing_username_raises(self) -> None:
        user = _make_user()
        request = ProfileUpdateRequest(username="new-handle")

        try:
            validate_profile_update(user, request)
            raise AssertionError("expected ImmutableFieldChangeError")
        except ImmutableFieldChangeError as exc:
            assert exc.field == "username"

    def test_resending_the_same_email_is_not_an_error(self) -> None:
        user = _make_user(email="alice@example.com")
        request = ProfileUpdateRequest(email="alice@example.com")

        update = validate_profile_update(user, request)

        assert update.first_name is None

    def test_resending_the_same_username_is_not_an_error(self) -> None:
        user = _make_user(username="alice")
        request = ProfileUpdateRequest(username="alice")

        validate_profile_update(user, request)  # must not raise

    def test_omitting_email_and_username_entirely_is_fine(self) -> None:
        user = _make_user()
        request = ProfileUpdateRequest(first_name="Alicia")

        update = validate_profile_update(user, request)

        assert update.first_name == "Alicia"


class TestValidateProfileUpdateEmptyNames:
    def test_empty_first_name_raises(self) -> None:
        user = _make_user()
        request = ProfileUpdateRequest(first_name="")

        try:
            validate_profile_update(user, request)
            raise AssertionError("expected EmptyNameError")
        except EmptyNameError as exc:
            assert exc.field == "first_name"

    def test_whitespace_only_first_name_raises(self) -> None:
        user = _make_user()
        request = ProfileUpdateRequest(first_name="   ")

        try:
            validate_profile_update(user, request)
            raise AssertionError("expected EmptyNameError")
        except EmptyNameError as exc:
            assert exc.field == "first_name"

    def test_empty_last_name_raises(self) -> None:
        user = _make_user()
        request = ProfileUpdateRequest(last_name="")

        try:
            validate_profile_update(user, request)
            raise AssertionError("expected EmptyNameError")
        except EmptyNameError as exc:
            assert exc.field == "last_name"

    def test_omitted_names_do_not_raise(self) -> None:
        user = _make_user()
        request = ProfileUpdateRequest(avatar_url="https://cdn.example/a.png")

        validate_profile_update(user, request)  # must not raise


class TestApplyProfileUpdate:
    def test_only_provided_fields_are_applied(self) -> None:
        user = _make_user(first_name="Alice", last_name="Ng", avatar_url="https://old")
        request = ProfileUpdateRequest(first_name="Alicia")

        update = validate_profile_update(user, request)
        apply_profile_update(user, update)

        assert user.first_name == "Alicia"
        assert user.last_name == "Ng"
        assert user.avatar_url == "https://old"

    def test_avatar_url_can_be_explicitly_cleared_to_null(self) -> None:
        user = _make_user(avatar_url="https://old")
        request = ProfileUpdateRequest(avatar_url=None)

        update = validate_profile_update(user, request)
        apply_profile_update(user, update)

        assert user.avatar_url is None

    def test_omitting_avatar_url_leaves_it_untouched(self) -> None:
        user = _make_user(avatar_url="https://old")
        request = ProfileUpdateRequest(first_name="Alicia")

        update = validate_profile_update(user, request)
        apply_profile_update(user, update)

        assert user.avatar_url == "https://old"
