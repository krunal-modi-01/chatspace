from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from jose import jwt as jose_jwt
from pydantic import SecretStr

from app.core.config import Settings
from app.core.jwt import (
    ExpiredTokenError,
    InvalidTokenError,
    create_access_token,
    decode_access_token,
)
from tests.conftest import REQUIRED_ENV


@pytest.fixture
def settings() -> Settings:
    return Settings(**{k.lower(): v for k, v in REQUIRED_ENV.items()})  # type: ignore[arg-type]


def test_create_access_token_expires_in_matches_contract_900_seconds(settings: Settings) -> None:
    _, expires_in = create_access_token(user_id="user-1", session_id="session-1", settings=settings)

    assert expires_in == 900


def test_create_access_token_carries_sub_and_sid(settings: Settings) -> None:
    token, _ = create_access_token(user_id="user-123", session_id="session-456", settings=settings)

    payload = decode_access_token(token, settings=settings)

    assert payload.user_id == "user-123"
    assert payload.session_id == "session-456"


def test_decode_access_token_round_trips_issued_and_expiry(settings: Settings) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    token, _ = create_access_token(
        user_id="user-1", session_id="session-1", settings=settings, now=now
    )

    payload = decode_access_token(token, settings=settings)

    assert payload.issued_at == now
    assert payload.expires_at == now + timedelta(minutes=settings.jwt_access_token_ttl_minutes)


def test_decode_access_token_rejects_expired_token(settings: Settings) -> None:
    expired_time = datetime.now(UTC) - timedelta(hours=1)
    token, _ = create_access_token(
        user_id="user-1", session_id="session-1", settings=settings, now=expired_time
    )

    with pytest.raises(ExpiredTokenError):
        decode_access_token(token, settings=settings)


def test_decode_access_token_rejects_bad_signature(settings: Settings) -> None:
    token, _ = create_access_token(user_id="user-1", session_id="session-1", settings=settings)
    # Tamper the FIRST char of the signature segment: its bits are always
    # significant, unlike the last base64url char (low 2 bits are padding for a
    # 32-byte HS256 signature, so flipping it can decode to identical bytes).
    header, payload, signature = token.split(".")
    tampered_signature = ("B" if signature[0] != "B" else "C") + signature[1:]
    tampered = f"{header}.{payload}.{tampered_signature}"

    with pytest.raises(InvalidTokenError):
        decode_access_token(tampered, settings=settings)


def test_decode_access_token_rejects_malformed_token(settings: Settings) -> None:
    with pytest.raises(InvalidTokenError):
        decode_access_token("not-a-jwt", settings=settings)


def test_decode_access_token_rejects_missing_claims(settings: Settings) -> None:
    bogus = jose_jwt.encode(
        {"foo": "bar"},
        settings.jwt_signing_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(InvalidTokenError):
        decode_access_token(bogus, settings=settings)


def test_decode_access_token_rejects_wrong_signing_key(settings: Settings) -> None:
    token, _ = create_access_token(user_id="user-1", session_id="session-1", settings=settings)

    other = settings.model_copy(update={"jwt_signing_key": SecretStr("a-completely-different-key")})

    with pytest.raises(InvalidTokenError):
        decode_access_token(token, settings=other)


def test_access_token_is_a_three_segment_jwt(settings: Settings) -> None:
    token, _ = create_access_token(user_id="user-1", session_id="session-1", settings=settings)

    assert len(token.split(".")) == 3
