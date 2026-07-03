from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.correlation import HEADER_NAME, sanitize_correlation_id


def test_generated_correlation_id_is_echoed_when_client_sends_none(
    client: TestClient,
) -> None:
    response = client.get("/v1/healthz")

    assert response.headers[HEADER_NAME]  # non-empty, generated


def test_well_formed_client_correlation_id_is_honored(client: TestClient) -> None:
    supplied = "trace-123_ABC.def"

    response = client.get("/v1/healthz", headers={HEADER_NAME: supplied})

    assert response.headers[HEADER_NAME] == supplied


def test_oversized_client_correlation_id_is_replaced(client: TestClient) -> None:
    oversized = "a" * 500

    response = client.get("/v1/healthz", headers={HEADER_NAME: oversized})

    returned = response.headers[HEADER_NAME]
    assert returned != oversized
    assert len(returned) <= 128


def test_illegal_char_client_correlation_id_is_replaced(client: TestClient) -> None:
    illegal = "bad value with spaces!"

    response = client.get("/v1/healthz", headers={HEADER_NAME: illegal})

    assert response.headers[HEADER_NAME] != illegal


def test_sanitize_correlation_id_unit() -> None:
    assert sanitize_correlation_id("ok-1_2.3") == "ok-1_2.3"
    # None → generated (non-empty)
    assert sanitize_correlation_id(None)
    # too long → generated (different, bounded)
    generated = sanitize_correlation_id("x" * 129)
    assert generated != "x" * 129
    assert len(generated) <= 128
    # control chars / injection attempt → generated
    assert sanitize_correlation_id("a\r\nb") != "a\r\nb"
