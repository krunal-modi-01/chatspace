"""Media upload + presigned-fetch business logic (T28, F57-F62, ADR-0007).

Two-phase flow (F57): `upload_media` is phase 1 -- validate, sniff,
EXIF-strip-or-reject, sanitize the filename, store the object, and
persist an *unbound* (`message_id IS NULL`) `attachments` row. Binding to
a message happens later, on message-create (`app.services.messages`'s
`_bind_media_atomically`, T21) -- out of scope here. `get_media_url` is
phase 2 -- issue a short-lived presigned GET URL, re-checking the
caller's **current** membership/participation at fetch time (F59), never
trusting the stored row alone.

Nothing is ever persisted to Postgres nor left in the object store on a
validation failure: every validation/sniff/EXIF-strip check in
`app.core.media_validation`/`app.services.media_images` runs *before* the
`put_object` call, and a failed DB commit after a successful
`put_object` triggers a best-effort purge of the just-stored bytes (see
`upload_media`'s `except` clause) so a failed insert never leaves
unreferenced object-store bytes with no way to find them again.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.ids import generate_id
from app.core.media_validation import (
    SIZE_CAP_BYTES_BY_KIND,
    MediaSizeExceededError,
    parse_kind,
    sanitize_filename,
    sniff_content_type,
    validate_allowlist,
    validate_sniff_match,
)
from app.models.attachment import Attachment, AttachmentKind
from app.models.message import Message
from app.services.channels import get_membership
from app.services.media_images import strip_exif
from app.services.media_storage import (
    PRESIGNED_URL_TTL_SECONDS,
    MediaStorageError,
    delete_object,
    generate_presigned_get_url,
    put_object,
)

logger = logging.getLogger(__name__)

# Bounded chunked read (F58): never buffer more than a kind's cap (plus one
# read chunk) into memory before rejecting an oversize upload -- a client
# cannot force the app to fully buffer an arbitrarily large body first.
_READ_CHUNK_BYTES = 1024 * 1024

# `kind=file` has no fixed content-type allowlist (see
# `app.core.media_validation`'s module docstring) beyond a small denylist
# of browser-active types, so its declared `content_type` is never trusted
# as the *stored* S3 object Content-Type -- forcing this generic,
# never-rendered-inline value at store time is a second, independent layer
# (alongside `get_media_url`'s presigned `ResponseContentType`/
# `ResponseContentDisposition` override) against a stored-XSS-shaped
# upload being served in a way a browser would render/execute (T28
# security review HIGH-2). The *declared* type is still recorded verbatim
# on the `attachments` row / returned in API responses for client display
# purposes -- only the object actually written to the bucket is affected.
_FILE_KIND_STORED_CONTENT_TYPE = "application/octet-stream"


class MediaNotFoundError(Exception):
    """No such media, or unassociated/orphaned -- uniform `404` (F59 contract note)."""


class NotAuthorizedForMediaError(Exception):
    """Caller is not a current member/participant of the media's conversation -- `403` (F59)."""


class MediaUploadEmptyError(Exception):
    """The uploaded file part is empty (zero bytes) -- `400`; `byte_size` must be `> 0`."""


def _storage_key(media_id: UUID) -> str:
    """Opaque object-store key -- deliberately excludes the (PII) filename."""

    return f"attachments/{media_id}"


def _attachment_content_disposition(filename: str) -> str:
    """`Content-Disposition: attachment` header value for a sanitized filename.

    `filename` has already passed through `sanitize_filename` (F62) at
    upload time, so it cannot contain path separators or control
    characters -- this defensively strips characters that would break out
    of the quoted-string regardless.
    """

    safe = filename.replace("\\", "_").replace('"', "_")
    return f'attachment; filename="{safe}"'


async def read_upload_within_limit(file: UploadFile, max_bytes: int) -> bytes:
    """Read `file` in bounded chunks, raising `MediaSizeExceededError` as soon
    as the cumulative size exceeds `max_bytes`.

    Never buffers an unbounded amount of a maliciously oversized upload
    into memory before rejecting it -- worst case is `max_bytes` plus one
    chunk (`_READ_CHUNK_BYTES`).
    """

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise MediaSizeExceededError(f"upload exceeds the {max_bytes}-byte cap for this kind.")
        chunks.append(chunk)
    return b"".join(chunks)


async def upload_media(
    db: AsyncSession,
    s3_client: Any,
    *,
    uploader_id: UUID,
    file: UploadFile,
    declared_content_type_raw: str,
    kind_raw: str,
    filename_raw: str,
) -> Attachment:
    """Validate, sniff, EXIF-strip, sanitize, store, and persist one upload (F57/F58/F61).

    Raises (all pre-store; nothing is ever persisted or uploaded on
    failure): `InvalidMediaKindError` (`400`), `MediaUploadEmptyError`
    (`400`), `MediaSizeExceededError` (`413`), `MediaTypeDisallowedError` /
    `MediaSniffMismatchError` / `MediaExifStripError` (`415`), or
    `MediaStorageError` (`503` -- object store unavailable; additive,
    flagged in the technical spec's risk table, not yet in the frozen
    contract's status table -- see `app.api.media`).
    """

    kind = parse_kind(kind_raw)
    declared_content_type = declared_content_type_raw.strip().lower()
    sanitized_filename = sanitize_filename(filename_raw)

    cap = SIZE_CAP_BYTES_BY_KIND[kind]
    data = await read_upload_within_limit(file, cap)
    if len(data) == 0:
        raise MediaUploadEmptyError("uploaded file is empty.")

    validate_allowlist(kind, declared_content_type)
    sniffed = sniff_content_type(data)
    validate_sniff_match(kind, declared_content_type, sniffed)

    stored_bytes = data
    if kind == AttachmentKind.IMAGE:
        # Security review HIGH: `strip_exif` is a synchronous, CPU-bound
        # Pillow decode/re-encode (potentially 100ms-1s+ for a large image,
        # longer for a multi-frame animation) -- run it off the event loop
        # so one upload's EXIF-strip can never stall every other concurrent
        # request/WebSocket connection on this instance, mirroring
        # `media_storage.py`'s own `asyncio.to_thread` wrapping of its
        # (I/O-bound) boto3 calls for the same reason.
        stored_bytes = await asyncio.to_thread(strip_exif, data, content_type=declared_content_type)
        if len(stored_bytes) > cap:
            # Defense-in-depth: re-encoding overhead pushed the stripped
            # image back over its own cap -- reject rather than violate the
            # shipped `ck_attachments_size_cap` CHECK on insert.
            raise MediaSizeExceededError(
                f"stripped image exceeds the {cap}-byte cap for kind='image'."
            )

    media_id = generate_id()
    storage_key = _storage_key(media_id)
    settings = get_settings()

    stored_content_type = declared_content_type
    if kind == AttachmentKind.FILE:
        stored_content_type = _FILE_KIND_STORED_CONTENT_TYPE

    await put_object(
        s3_client,
        bucket=settings.s3_bucket_name,
        key=storage_key,
        body=stored_bytes,
        content_type=stored_content_type,
    )

    attachment = Attachment(
        id=media_id,
        message_id=None,
        uploader_id=uploader_id,
        kind=kind,
        content_type=declared_content_type,
        storage_key=storage_key,
        filename=sanitized_filename,
        byte_size=len(stored_bytes),
    )
    db.add(attachment)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        try:
            await delete_object(s3_client, bucket=settings.s3_bucket_name, key=storage_key)
        except MediaStorageError:
            logger.error(
                "failed to purge orphaned object bytes after a failed attachment insert",
                extra={"media_id": str(media_id)},
            )
        raise

    await db.refresh(attachment)
    return attachment


async def _caller_can_access_message_media(
    db: AsyncSession, message: Message, *, caller_id: UUID
) -> bool:
    """Current membership/participation check (F59) -- re-checked at fetch time.

    Channel-bound media: caller must **currently** be a member of
    `message.channel_id` (re-reads `channel_members`, never trusts a
    stale/cached membership). DM-bound media: caller must be one of the
    message's two fixed participants (`sender_id`/`recipient_id`) -- DMs
    have no membership table to leave, so "current participation" is
    simply being one of the two fixed ids on that message.
    """

    if message.channel_id is not None:
        membership = await get_membership(db, channel_id=message.channel_id, user_id=caller_id)
        return membership is not None

    return caller_id in (message.sender_id, message.recipient_id)


@dataclass(frozen=True, slots=True)
class MediaUrlResult:
    """Outcome of `get_media_url` -- the frozen `200` response shape's fields."""

    url: str
    expires_at: datetime
    content_type: str
    filename: str
    size: int


async def get_media_url(
    db: AsyncSession, s3_client: Any, *, media_id: UUID, caller_id: UUID
) -> MediaUrlResult:
    """Issue a 5-min presigned GET URL for `media_id`, authorized at fetch time (F59).

    Raises `MediaNotFoundError` (`404`, uniform for "no such media",
    "unassociated/orphaned", and "bound message has been soft-deleted" --
    checked in that order, before authorization, per the contract) or
    `NotAuthorizedForMediaError` (`403`, not a current member/participant
    of the bound message's conversation).
    """

    attachment = await db.get(Attachment, media_id)
    if attachment is None or attachment.message_id is None:
        raise MediaNotFoundError(f"No bound media {media_id}.")

    message = await db.get(Message, attachment.message_id)
    if message is None:
        # Unreachable in practice (`attachments.message_id` FKs `messages.id`
        # ON DELETE CASCADE, so a bound row's message always exists) --
        # defense-in-depth only, same uniform 404.
        raise MediaNotFoundError(f"No bound media {media_id}.")

    if message.deleted_at is not None:
        # A soft-deleted message's attachment row is retained (per
        # `app.services.messages`'s soft-delete model) but must not remain
        # fetchable -- a user who deletes a message expects its media to
        # disappear along with it, same as history/list endpoints already
        # filter `deleted_at IS NULL` (T28 code review finding #3). Uniform
        # 404, same as every other "no such media" outcome here.
        raise MediaNotFoundError(f"No bound media {media_id}.")

    if not await _caller_can_access_message_media(db, message, caller_id=caller_id):
        raise NotAuthorizedForMediaError(
            f"{caller_id} is not a current member/participant for media {media_id}."
        )

    settings = get_settings()
    response_content_type: str | None = None
    response_content_disposition: str | None = None
    if attachment.kind == AttachmentKind.FILE:
        # See `_FILE_KIND_STORED_CONTENT_TYPE`'s comment -- force a forced
        # download regardless of what the client declared at upload time
        # (T28 security review HIGH-2 / code review finding #2).
        response_content_type = _FILE_KIND_STORED_CONTENT_TYPE
        response_content_disposition = _attachment_content_disposition(attachment.filename)

    url = generate_presigned_get_url(
        s3_client,
        bucket=settings.s3_bucket_name,
        key=attachment.storage_key,
        response_content_type=response_content_type,
        response_content_disposition=response_content_disposition,
    )
    expires_at = datetime.now(UTC) + timedelta(seconds=PRESIGNED_URL_TTL_SECONDS)

    return MediaUrlResult(
        url=url,
        expires_at=expires_at,
        content_type=attachment.content_type,
        filename=attachment.filename,
        size=attachment.byte_size,
    )
