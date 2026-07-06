"""Password-policy validator (F23 / R37).

A single reusable check for "does this candidate password meet our
minimum bar", shared by registration, password-change, and password-reset
confirmation — so the three call sites never drift out of sync on what
"strong enough" means.

Per the functional spec (F23/R37): minimum 6 characters + a basic
strength rule. On failure, the caller (an endpoint handler, in a later
task) raises `PasswordPolicyError`, which carries field-level violation
detail suitable for the frozen `422 problem+json` `errors[]` array. This
module does not decide the request's `field` name itself — register uses
`password`, change/reset-confirm use `new_password` — the caller supplies
it via `field_name`.

Never logs the candidate password: violation messages describe the rule
that failed, never the input value itself.
"""

from __future__ import annotations

MIN_LENGTH = 6


class PasswordPolicyError(Exception):
    """Raised when a candidate password fails the policy.

    `errors` is a list of `{"field": ..., "detail": ...}` dicts, ready to
    drop into the RFC 7807 `errors[]` array of a 422 problem+json body.
    """

    def __init__(self, errors: list[dict[str, str]]) -> None:
        self.errors = errors
        super().__init__("Password fails policy.")


def check_password_policy(password: str) -> list[str]:
    """Return a list of human-readable violation messages (empty = compliant).

    Rules (F23/R37):
    - minimum length: `MIN_LENGTH` characters.
    - basic strength: must contain at least one letter and at least one
      digit (rejects e.g. all-digit or all-letter passwords), and must not
      be entirely whitespace.
    """

    violations: list[str] = []

    if len(password) < MIN_LENGTH:
        violations.append(f"must be at least {MIN_LENGTH} characters long")

    if not password.strip():
        violations.append("must not be blank")

    has_letter = any(char.isalpha() for char in password)
    has_digit = any(char.isdigit() for char in password)
    if not (has_letter and has_digit):
        violations.append("must contain at least one letter and one digit")

    return violations


def enforce_password_policy(password: str, *, field_name: str = "password") -> None:
    """Raise `PasswordPolicyError` if `password` fails the policy.

    `field_name` lets each call site (register -> `password`, change/reset
    confirm -> `new_password`) report the violation against the field name
    that matches its own request schema, per the frozen API contract.
    """

    violations = check_password_policy(password)
    if violations:
        raise PasswordPolicyError(
            errors=[{"field": field_name, "detail": violation} for violation in violations]
        )
