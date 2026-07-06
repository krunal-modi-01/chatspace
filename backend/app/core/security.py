"""Password hashing primitives (T09).

Wraps `passlib`'s bcrypt scheme so the rest of the codebase never touches a
raw hashing algorithm directly. Two invariants matter more than anything
else here, per CLAUDE.md SECURITY REQUIREMENTS and the database design
(R1/R24):

- A password hash is **never reversible** — only `verify_password` can
  confirm a candidate password matches a stored hash, and even that
  returns a boolean, never the original value.
- Neither the raw password nor the resulting hash is ever logged. This
  module deliberately contains no logging calls at all, so there is
  nothing for a future edit to accidentally start logging.

`passlib`'s bcrypt `verify` is constant-time by construction (it hashes
the candidate with the salt/cost embedded in the stored hash and compares
the encoded digests), which satisfies the "verify constant-time"
requirement without any bespoke comparison logic here.
"""

from __future__ import annotations

from passlib.context import CryptContext

# A single process-wide context. bcrypt is the configured scheme (matches
# the `passlib[bcrypt]` dependency already vetted in pyproject.toml);
# `deprecated="auto"` future-proofs a scheme migration (e.g. to argon2)
# without changing every call site — old hashes would still verify while
# new ones are minted with the new scheme.
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash `password` for storage in `users.hashed_password`.

    The result is a salted, one-way bcrypt digest — never the reverse of
    the input, and never logged by this function or its caller.
    """

    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Return True iff `password` matches `password_hash`.

    Constant-time by construction (delegated to `passlib`'s bcrypt
    verification, which re-derives the digest using the salt/cost encoded
    in `password_hash` and compares the encoded strings) — no early-exit
    string comparison is performed here.
    """

    try:
        return _pwd_context.verify(password, password_hash)
    except ValueError:
        # Malformed/unknown hash format: treat as "does not verify"
        # rather than raising, so a corrupt stored hash fails closed.
        return False
