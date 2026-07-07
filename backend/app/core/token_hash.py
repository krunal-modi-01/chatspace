"""Refresh-token hashing (T10, ADR-0006).

Refresh tokens are stored **only** as `sessions.refresh_token_hash` — the
raw token is minted once (`app.services.sessions.generate_raw_refresh_token`),
handed to the caller, and never persisted, logged, or returned again
(CLAUDE.md SECURITY REQUIREMENTS; database design `sessions` table notes).

Deliberately **not** `passlib`'s bcrypt (used for `hashed_password` in
`app.core.security`): bcrypt is a slow, salted KDF designed to blunt
brute-forcing a *low-entropy* human password, and it has no verification
path other than "hash the candidate and compare" — there is no way to look
a bcrypt hash up by value, which is exactly what refresh-token exchange
needs (`WHERE refresh_token_hash = ?` against `uq_sessions_refresh_hash`).
A refresh token is instead a high-entropy (256-bit) server-generated
random secret, so a fast, deterministic, unsalted cryptographic hash
(SHA-256) is the standard, sufficient construction: preimage/second-preimage
resistance already makes recovering the raw token from its hash
infeasible, and salting exists to defeat precomputation attacks against a
*small, guessable* input space, which does not apply here.
"""

from __future__ import annotations

import hashlib


def _sha256_hex(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def hash_refresh_token(raw_token: str) -> str:
    """Return the deterministic SHA-256 hex digest of `raw_token`.

    Deterministic so the exact same raw token always hashes to the exact
    same value, which is required for the equality lookup
    (`sessions.refresh_token_hash = ?`) that refresh-token exchange
    performs against `uq_sessions_refresh_hash`. Never logs or returns
    `raw_token` itself.
    """

    return _sha256_hex(raw_token)


def hash_reset_token(raw_token: str) -> str:
    """Return the deterministic SHA-256 hex digest of a raw password-reset token.

    Same construction and rationale as `hash_refresh_token` above (T16,
    F15-F17): a password-reset token is likewise a high-entropy,
    server-generated opaque secret looked up by equality
    (`password_reset_tokens.token_hash = ?` against `uq_prt_token_hash`),
    so a fast, deterministic, unsalted hash is the correct construction —
    never a slow salted KDF like bcrypt. Never logs or returns `raw_token`
    itself; only this hash is ever persisted (`token_hash` column).
    """

    return _sha256_hex(raw_token)
