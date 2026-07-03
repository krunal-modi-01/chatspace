from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

REQUIRED_ENV: dict[str, str] = {
    "DATABASE_URL": "postgresql+asyncpg://chatspace:chatspace@localhost:5432/chatspace_test",
    "REDIS_URL": "redis://localhost:6379/1",
    "JWT_SIGNING_KEY": "test-signing-key-not-a-real-secret",
    "SMTP_HOST": "localhost",
    "SMTP_PORT": "1025",
    "SMTP_USERNAME": "test",
    "SMTP_PASSWORD": "test-smtp-password",
    "SMTP_FROM_ADDRESS": "no-reply@chatspace.example",
    "S3_ENDPOINT_URL": "http://localhost:9000",
    "S3_BUCKET_NAME": "chatspace-media-test",
    "S3_ACCESS_KEY_ID": "test-access-key",
    "S3_SECRET_ACCESS_KEY": "test-secret-key",
    "BOOTSTRAP_ADMIN_EMAIL": "admin@chatspace.example",
    "BOOTSTRAP_ADMIN_USERNAME": "admin",
    "BOOTSTRAP_ADMIN_PASSWORD": "test-bootstrap-password",
}


@pytest.fixture
def configured_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Populate every required setting with a non-secret test value."""

    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    yield


@pytest.fixture
def client(configured_env: None) -> Iterator[TestClient]:
    from app.core.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client

    get_settings.cache_clear()
