"""Pydantic response schemas for `POST /v1/media` + `GET /v1/media/{id}/url` (T28).

Both shapes are exactly the frozen contract's response bodies — no
`storage_key` ever appears on the wire (it is an internal, opaque
object-store key per the database design). Request bodies are
`multipart/form-data`, not JSON, so there is no request schema here (the
route parses `File`/`Form` parts directly — see `app.api.media`).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.attachment import Attachment, AttachmentKind


class MediaUploadResponse(BaseModel):
    """`201` body of `POST /v1/media`."""

    media_id: UUID
    kind: str
    content_type: str
    filename: str
    size: int
    created_at: datetime

    @classmethod
    def from_attachment(cls, attachment: Attachment) -> MediaUploadResponse:
        kind = attachment.kind
        return cls(
            media_id=attachment.id,
            kind=kind.value if isinstance(kind, AttachmentKind) else str(kind),
            content_type=attachment.content_type,
            filename=attachment.filename,
            size=attachment.byte_size,
            created_at=attachment.created_at,
        )


class MediaUrlResponse(BaseModel):
    """`200` body of `GET /v1/media/{media_id}/url` — a short-lived presigned GET URL (F59)."""

    url: str
    expires_at: datetime
    content_type: str
    filename: str
    size: int
