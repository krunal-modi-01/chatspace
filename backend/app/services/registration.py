"""Invite-redemption registration (T14, F5/F6, frozen contract for `POST /v1/auth/register`).

There is deliberately **no invite-less registration path** — every call
into this module requires an already-validated, `pending`/unexpired
`Invite` row (obtained via `app.services.invites.find_valid_invite_by_token`
by the route handler *before* this module is invoked). This module owns
only what happens once that invite is known-valid: field-content
validation (username shape, non-blank names), case-insensitive
duplicate-username/email detection, password hashing, and building the
new `User` row — plus flipping the invite to `accepted` via
`app.services.invites.redeem_invite` in the very same unit of work.

Transaction boundary (frozen data-model note): invite-validation, the
`users` INSERT, and the invite's `pending -> accepted` transition all
happen in **one** transaction, owned by the caller (the route handler).
This module's `build_registered_user` only `db.add()`s and `flush()`es —
it never commits — so a duplicate-username/email failure surfaced by the
flush (`IntegrityError`) can be rolled back by the caller without the
invite ever having been consumed.
"""

from __future__ import annotations

import unicodedata

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import generate_id
from app.core.security import hash_password
from app.models.invite import Invite
from app.models.user import User
from app.services.invites import is_email_registered, redeem_invite

# Mirrors the frozen `username_len` CHECK constraint (1-32 chars).
USERNAME_MIN_LENGTH = 1
USERNAME_MAX_LENGTH = 32


class RegistrationFieldError(Exception):
    """Raised when a registration field fails content validation (frozen `422`).

    `errors` is a list of `{"field": ..., "detail": ...}` dicts, ready to
    drop into the RFC 7807 `errors[]` array — same shape as
    `app.core.password_policy.PasswordPolicyError`.
    """

    def __init__(self, errors: list[dict[str, str]]) -> None:
        self.errors = errors
        super().__init__("Registration field validation failed.")


class DuplicateIdentityError(Exception):
    """Raised when the candidate username or email is already registered (frozen `409`).

    Deliberately does not say *which* one collided in a way callers must
    surface distinctly — the frozen contract's `409` response is a single
    uniform outcome ("Username or email already registered"), not a
    field-attributed error.
    """


def _normalize_username(username: str) -> str:
    # NFC-normalize *before* returning so the value that gets length-checked
    # here is the same value `build_registered_user` persists — Postgres
    # does not normalize text on insert, so checking one form and storing
    # another lets a combining-character username (e.g. 32 NFC-normalized
    # chars that are 64 raw code points) pass this check but then fail the
    # DB's `username_len` CHECK constraint as an unhandled 500.
    return unicodedata.normalize("NFC", username.strip())


def validate_registration_fields(*, username: str, first_name: str, last_name: str) -> str:
    """Validate content (not just structural presence) of registration fields.

    Returns the normalized (stripped) username. Raises
    `RegistrationFieldError` (`422`) for: a username outside the frozen
    `username_len` bound (1-32 chars after stripping), or a
    first/last name that is blank/whitespace-only (mirrors
    `names_present`'s `btrim <> ''`). Pydantic's `min_length=1`
    on the request schema already rejects an empty string structurally
    (`400`); this catches the remaining content-validity gaps (e.g.
    all-whitespace, or an over-length username) that `min_length` alone
    cannot.
    """

    errors: list[dict[str, str]] = []

    normalized_username = _normalize_username(username)
    # `normalized_username` is already NFC-normalized (see
    # `_normalize_username`), matching what `build_registered_user`
    # persists — so this length check applies to the exact string that
    # will hit Postgres' `username_len` CHECK constraint.
    username_len = len(normalized_username)
    if not (USERNAME_MIN_LENGTH <= username_len <= USERNAME_MAX_LENGTH):
        errors.append(
            {
                "field": "username",
                "detail": f"must be between {USERNAME_MIN_LENGTH} and "
                f"{USERNAME_MAX_LENGTH} characters long",
            }
        )

    if not first_name.strip():
        errors.append({"field": "first_name", "detail": "must not be blank"})

    if not last_name.strip():
        errors.append({"field": "last_name", "detail": "must not be blank"})

    if errors:
        raise RegistrationFieldError(errors)

    return normalized_username


async def is_username_registered(db: AsyncSession, username: str) -> bool:
    """Case-insensitive check against `users`, mirroring `uq_users_username_lower`."""

    result = await db.execute(
        select(User.id).where(func.lower(User.username) == username.strip().lower())
    )
    return result.scalar_one_or_none() is not None


async def check_identity_not_taken(db: AsyncSession, *, username: str, email: str) -> None:
    """Raise `DuplicateIdentityError` if `username` or `email` is already registered.

    A pre-check, race-safe only up to the usual TOCTOU window — the caller
    must *also* catch the `IntegrityError` a concurrent registration could
    still raise on the functional unique indexes as the authoritative
    backstop (mirrors `app.services.bootstrap`'s same two-layer pattern).
    """

    if await is_username_registered(db, username) or await is_email_registered(db, email):
        raise DuplicateIdentityError


def build_registered_user(
    *,
    invite: Invite,
    username: str,
    first_name: str,
    last_name: str,
    password: str,
    avatar_url: str | None,
) -> User:
    """Construct (and `db.add()`-ready) the new `User` row for invite redemption.

    Does **not** flush, commit, or mark the invite redeemed — the caller
    owns the transaction and must call `app.services.invites.redeem_invite`
    on the same `invite` and flush/commit both together (see module
    docstring). `email` is locked to `invite.email` (R45), never taken
    from client input — there is no `email` field on `RegisterRequest` at
    all.

    The new user is created **active** (`is_active` relies on the DB
    default `true`, per acceptance criteria) with `must_change_password`
    left at its `false` default (the caller chose their own password) and
    `email_verified=True` (redeeming a mailed invite proves ownership of
    `invite.email` — mirrors `app.services.bootstrap`'s seeded-admin
    rationale for the same field).
    """

    return User(
        id=generate_id(),
        username=username,
        email=invite.email,
        hashed_password=hash_password(password),
        first_name=first_name,
        last_name=last_name,
        avatar_url=avatar_url,
        is_active=True,
        is_system_admin=False,
        must_change_password=False,
        email_verified=True,
    )


__all__ = [
    "DuplicateIdentityError",
    "RegistrationFieldError",
    "build_registered_user",
    "check_identity_not_taken",
    "is_username_registered",
    "redeem_invite",
    "validate_registration_fields",
]
