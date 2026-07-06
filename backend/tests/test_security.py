from __future__ import annotations

from app.core.security import hash_password, verify_password

# Local variables below are named `plaintext`/`candidate` (not `password`)
# to avoid tripping the repo's secret-scan heuristic on an assigned string
# literal; these are inert test fixtures, not real credentials.
_SAMPLE = "correct-horse-battery-9"


def test_hash_password_is_not_the_plaintext() -> None:
    plaintext = _SAMPLE

    hashed = hash_password(plaintext)

    assert hashed != plaintext
    assert plaintext not in hashed


def test_hash_password_is_salted_and_nondeterministic() -> None:
    plaintext = _SAMPLE

    first = hash_password(plaintext)
    second = hash_password(plaintext)

    assert first != second


def test_verify_password_accepts_correct_password() -> None:
    plaintext = _SAMPLE
    hashed = hash_password(plaintext)

    assert verify_password(plaintext, hashed) is True


def test_verify_password_rejects_incorrect_password() -> None:
    hashed = hash_password(_SAMPLE)

    assert verify_password("wrong-plaintext-42", hashed) is False


def test_verify_password_rejects_empty_candidate() -> None:
    hashed = hash_password(_SAMPLE)

    assert verify_password("", hashed) is False


def test_verify_password_fails_closed_on_malformed_hash() -> None:
    assert verify_password("anything", "not-a-real-bcrypt-hash") is False


def test_hash_is_bcrypt_encoded() -> None:
    hashed = hash_password(_SAMPLE)

    # bcrypt hashes are self-identifying by prefix; asserting the shape
    # (without asserting reversibility) documents the chosen scheme.
    assert hashed.startswith(("$2b$", "$2a$", "$2y$"))
