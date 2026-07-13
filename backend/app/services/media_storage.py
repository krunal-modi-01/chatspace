"""Thin async wrappers around the boto3 S3 client (T28, ADR-0007).

boto3 is synchronous; every function here that performs a real network
call runs it via `asyncio.to_thread` so it never blocks the event loop.
`generate_presigned_get_url` is the one exception — presigned-URL
generation is pure local request-signing (no network round-trip), so it
runs inline.

Kept as free functions (not a class) taking an explicit `client` +
`bucket` so `app.services.media` stays trivially testable: a test
monkeypatches `app.services.media_storage.put_object` (mirrors
`app.services.email`'s existing `monkeypatch.setattr(".aiosmtplib.send",
...)` pattern) rather than needing a live MinIO reachable in CI/dev
sandboxes that don't run the full docker-compose stack.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Presigned GET URL lifetime — frozen contract: "issue a 5-min presigned
# GET URL" (F59).
PRESIGNED_URL_TTL_SECONDS = 5 * 60


class MediaStorageError(Exception):
    """A `put_object`/`delete_object` call to the object store failed.

    Never carries the raw underlying boto3/botocore exception message in
    any field a caller might surface to a client — only logged, and only
    the exception type (never bucket/key values, which are opaque but
    still avoided out of caution; never raw bytes).
    """


async def put_object(client: Any, *, bucket: str, key: str, body: bytes, content_type: str) -> None:
    """Upload `body` to `bucket`/`key`, raising `MediaStorageError` on failure.

    Runs the blocking boto3 call in a worker thread. Bounded by the
    client's own configured connect/read timeouts and retry count (see
    `app.db.storage.create_s3_client`) — never retries indefinitely.
    """

    try:
        await asyncio.to_thread(
            client.put_object,
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )
    except Exception as exc:  # noqa: BLE001 - normalize every backend failure mode
        logger.error(
            "media object store put_object failed", extra={"exception_type": type(exc).__name__}
        )
        raise MediaStorageError("failed to store media object") from exc


async def delete_object(client: Any, *, bucket: str, key: str) -> None:
    """Best-effort-callable delete of `bucket`/`key`; raises `MediaStorageError` on failure.

    Callers that use this as cleanup (a failed-insert rollback, or the
    orphan sweep) decide for themselves whether to swallow the error —
    this function always raises rather than silently swallowing, so a
    caller that *does* need to know can.
    """

    try:
        await asyncio.to_thread(client.delete_object, Bucket=bucket, Key=key)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "media object store delete_object failed", extra={"exception_type": type(exc).__name__}
        )
        raise MediaStorageError("failed to delete media object") from exc


def generate_presigned_get_url(
    client: Any,
    *,
    bucket: str,
    key: str,
    expires_in_seconds: int = PRESIGNED_URL_TTL_SECONDS,
    response_content_type: str | None = None,
    response_content_disposition: str | None = None,
) -> str:
    """Return a short-TTL presigned GET URL for `bucket`/`key` (F59).

    `response_content_type`/`response_content_disposition`, when given,
    are signed into the URL as S3's `ResponseContentType`/
    `ResponseContentDisposition` params — these override, at fetch time,
    whatever `Content-Type` the object was actually stored with, without
    needing to re-`put_object` it. `app.services.media.get_media_url`
    passes these for `kind=file` media specifically: forcing
    `application/octet-stream` + `Content-Disposition: attachment` so a
    direct-navigation open of the URL always downloads rather than
    renders inline in a browser (T28 security review HIGH-2 / code review
    finding #2) — `kind=file` has no fixed content-type allowlist, so its
    stored `Content-Type` cannot be trusted to be safe to render.

    Pure local signing — boto3 never makes a network call for this, so it
    is safe to call inline (no thread hop, no dependency on the object
    store actually being reachable at call time). Never logged by any
    caller (the URL is a bearer credential for the object, per the
    contract: "URL short-lived; never logged").
    """

    params: dict[str, str] = {"Bucket": bucket, "Key": key}
    if response_content_type is not None:
        params["ResponseContentType"] = response_content_type
    if response_content_disposition is not None:
        params["ResponseContentDisposition"] = response_content_disposition

    return client.generate_presigned_url(
        "get_object",
        Params=params,
        ExpiresIn=expires_in_seconds,
    )
