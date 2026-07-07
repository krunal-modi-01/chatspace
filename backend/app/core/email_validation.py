"""Lightweight email-format validation (T13, invite issuance).

Deliberately a small in-house regex rather than a new third-party
dependency (e.g. `pydantic`'s `email-validator` extra): CLAUDE.md's
dependency-update guardrail requires a vetting checklist before adding a
new dependency, and the frozen contract's `422 | Invalid email` check only
needs a conservative "looks like an email address" gate, not full RFC 5322
parsing or MX/deliverability checks.

This is intentionally distinct from `app.schemas.invites.InviteCreateRequest`'s
structural check (`Field(min_length=1)`, which maps to the frozen `400`
"malformed body" clause for a missing/blank/non-string field). A
syntactically-present-but-invalid address (e.g. `"not-an-email"`) passes
that structural check and is instead rejected here with the frozen `422`.
"""

from __future__ import annotations

import re

# Conservative "local@domain.tld" shape: no whitespace/`@` in the local or
# domain part, and at least one `.` in the domain. Good enough to catch the
# obviously-malformed inputs the contract's `422` guards against, without
# claiming full RFC 5322 compliance.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email_format(email: str) -> bool:
    """Return whether `email` looks like a well-formed email address."""

    return bool(_EMAIL_RE.fullmatch(email.strip()))
