"""S3-compatible object-store client construction and process-wide lifecycle (T28, ADR-0007).

Mirrors `app.db.redis` / `app.db.session`: one boto3 client per process,
constructed lazily and cached. `boto3.client("s3", ...)` does not open any
connection at construction time (like `Redis.from_url` / `create_async_engine`),
so building it at import/startup time never blocks even if the configured
endpoint (MinIO locally, a real provider in prod) is unreachable — the
first real network round-trip happens on the first `put_object`/
`generate_presigned_url` call a consumer makes.

boto3 is a synchronous library; every consumer that performs an actual
network call (`app.services.media_storage`) must run it off the event
loop via `asyncio.to_thread`. `generate_presigned_url` itself never makes
a network call (it is pure local request-signing), so callers may call it
directly without a thread hop.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import boto3

from app.core.config import Settings, get_settings

# Bounds how long a single S3 API call (`put_object`, `delete_object`) may
# block before raising, so an unreachable/wedged object store fails fast
# instead of piling up requests on the app tier (technical spec: "Object
# store down/slow ... bounded boto3 timeouts + limited retries; no retry
# storms").
_CONNECT_TIMEOUT_SECONDS = 5.0
_READ_TIMEOUT_SECONDS = 20.0
_MAX_ATTEMPTS = 2


def create_s3_client(settings: Settings) -> Any:
    """Create the process-wide boto3 S3 client from settings (ADR-0007).

    `endpoint_url` makes this provider-portable (MinIO locally; AWS S3 /
    Cloudflare R2 / DO Spaces in prod — a deploy-time config choice only).
    Path-style addressing is forced since MinIO (and most S3-compatible
    non-AWS providers) does not support virtual-hosted-style bucket
    addressing by default.
    """

    from botocore.config import Config as BotoConfig

    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_access_key.get_secret_value(),
        region_name=settings.s3_region,
        config=BotoConfig(
            connect_timeout=_CONNECT_TIMEOUT_SECONDS,
            read_timeout=_READ_TIMEOUT_SECONDS,
            retries={"max_attempts": _MAX_ATTEMPTS, "mode": "standard"},
            s3={"addressing_style": "path"},
        ),
    )


@lru_cache
def get_s3_client() -> Any:
    """Return the process-wide S3 client, creating it on first access.

    Cached for the same reason `get_engine`/`get_redis_client` are: one
    shared client (and its own internal connection pool) per process, not
    one per request. Tests may `get_s3_client.cache_clear()` between cases
    exactly like the other lazy singletons in `app.db`.
    """

    return create_s3_client(get_settings())
