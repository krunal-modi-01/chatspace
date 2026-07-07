from __future__ import annotations

from app.core.token_hash import hash_refresh_token


class TestHashRefreshToken:
    def test_is_deterministic(self) -> None:
        assert hash_refresh_token("abc123") == hash_refresh_token("abc123")

    def test_distinct_tokens_hash_differently(self) -> None:
        assert hash_refresh_token("token-a") != hash_refresh_token("token-b")

    def test_output_is_a_sha256_hex_digest(self) -> None:
        digest = hash_refresh_token("some-raw-token")

        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)

    def test_never_returns_the_raw_token(self) -> None:
        raw = "super-secret-refresh-token-value"

        digest = hash_refresh_token(raw)

        assert raw not in digest
