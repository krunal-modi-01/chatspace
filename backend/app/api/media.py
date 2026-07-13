"""`POST /v1/media` + `GET /v1/media/{media_id}/url` (T28, frozen contract, F57-F62).

Multipart upload (phase 1) and presigned-fetch (phase 2) of the
two-phase media flow (ADR-0007). Unlike the JSON-body routes elsewhere in
this package, `POST /v1/media`'s body is `multipart/form-data` -- FastAPI
typed `File`/`Form` parameters already give the missing-part ->
"unprocessable" distinction natively, so this route does not go through
`app.core.request_body.parse_body`; instead every part is declared
optional (`| None`) and `_require_part` raises the frozen `400`
("malformed multipart / missing parts") itself for any part that's
absent, keeping the same 400-for-structural / 413-or-415-for-semantic
split every other endpoint on this surface uses.

Rate limiting (`Depends(enforce_media_upload_rate_limit)`, T27,
`RateLimitScope.MEDIA_UPLOAD`, 20/min per user) applies only to the
upload route -- `GET .../url` is a safe, idempotent read the contract
does not rate-limit.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthenticatedUser, require_auth
from app.core.media_validation import (
    InvalidMediaKindError,
    MediaExifStripError,
    MediaSizeExceededError,
    MediaSniffMismatchError,
    MediaTypeDisallowedError,
)
from app.core.rate_limit_deps import enforce_media_upload_rate_limit
from app.db.session import get_db_session
from app.db.storage import get_s3_client
from app.schemas.media import MediaUploadResponse, MediaUrlResponse
from app.services.media import (
    MediaNotFoundError,
    MediaUploadEmptyError,
    NotAuthorizedForMediaError,
    get_media_url,
    upload_media,
)
from app.services.media_storage import MediaStorageError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["media"])

_MISSING_PART_DETAIL_TEMPLATE = (
    "'{field}' part is required and must be present in the multipart body."
)
_INVALID_KIND_DETAIL = "kind must be one of 'image', 'file', 'video'."
_EMPTY_UPLOAD_DETAIL = "uploaded file must not be empty."
_SIZE_EXCEEDED_DETAIL = "Upload exceeds the maximum size allowed for this media kind."
_UNSUPPORTED_MEDIA_DETAIL = (
    "This media's declared type, actual content, or (for images) EXIF metadata "
    "could not be validated/stripped."
)
_STORAGE_UNAVAILABLE_DETAIL = "Media storage is temporarily unavailable; please retry shortly."
_MEDIA_NOT_FOUND_DETAIL = "No such media."
_NOT_AUTHORIZED_DETAIL = (
    "You must be a current member/participant of this media's conversation to fetch it."
)

_CurrentUser = Annotated[AuthenticatedUser, Depends(require_auth)]
_DbSession = Annotated[AsyncSession, Depends(get_db_session)]
_S3Client = Annotated[Any, Depends(get_s3_client)]


def _require_part(value: str | UploadFile | None, field: str) -> None:
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_MISSING_PART_DETAIL_TEMPLATE.format(field=field),
        )
    if isinstance(value, str) and value.strip() == "":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_MISSING_PART_DETAIL_TEMPLATE.format(field=field),
        )


@router.post(
    "/media",
    response_model=MediaUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_media_route(
    current: _CurrentUser,
    db: _DbSession,
    s3_client: _S3Client,
    _rate_limit_guard: Annotated[None, Depends(enforce_media_upload_rate_limit)],
    file: Annotated[UploadFile | None, File()] = None,
    declared_content_type: Annotated[str | None, Form()] = None,
    kind: Annotated[str | None, Form()] = None,
    filename: Annotated[str | None, Form()] = None,
) -> Any:
    _require_part(file, "file")
    _require_part(declared_content_type, "declared_content_type")
    _require_part(kind, "kind")
    _require_part(filename, "filename")
    # `_require_part` raises on `None`/blank; narrow for the type checker.
    assert file is not None
    assert declared_content_type is not None
    assert kind is not None
    assert filename is not None

    try:
        attachment = await upload_media(
            db,
            s3_client,
            uploader_id=current.user_id,
            file=file,
            declared_content_type_raw=declared_content_type,
            kind_raw=kind,
            filename_raw=filename,
        )
    except InvalidMediaKindError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=_INVALID_KIND_DETAIL
        ) from None
    except MediaUploadEmptyError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=_EMPTY_UPLOAD_DETAIL
        ) from None
    except MediaSizeExceededError:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=_SIZE_EXCEEDED_DETAIL
        ) from None
    except (MediaTypeDisallowedError, MediaSniffMismatchError, MediaExifStripError):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=_UNSUPPORTED_MEDIA_DETAIL
        ) from None
    except MediaStorageError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_STORAGE_UNAVAILABLE_DETAIL
        ) from None

    logger.info(
        "media uploaded",
        extra={
            "media_id": str(attachment.id),
            "uploader_id": str(current.user_id),
            "kind": attachment.kind.value,
            "size": attachment.byte_size,
        },
    )

    response_body = MediaUploadResponse.from_attachment(attachment)
    return JSONResponse(
        status_code=status.HTTP_201_CREATED, content=response_body.model_dump(mode="json")
    )


@router.get(
    "/media/{media_id}/url",
    response_model=MediaUrlResponse,
    status_code=status.HTTP_200_OK,
)
async def get_media_url_route(
    media_id: UUID, current: _CurrentUser, db: _DbSession, s3_client: _S3Client
) -> MediaUrlResponse:
    try:
        result = await get_media_url(db, s3_client, media_id=media_id, caller_id=current.user_id)
    except MediaNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_MEDIA_NOT_FOUND_DETAIL
        ) from None
    except NotAuthorizedForMediaError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_NOT_AUTHORIZED_DETAIL
        ) from None

    # Never log the issued URL itself (frozen contract: "URL short-lived;
    # never logged") -- only the media id and caller, matching every other
    # audit-style log line on this surface.
    logger.info(
        "media url issued",
        extra={"media_id": str(media_id), "caller_id": str(current.user_id)},
    )

    return MediaUrlResponse(
        url=result.url,
        expires_at=result.expires_at,
        content_type=result.content_type,
        filename=result.filename,
        size=result.size,
    )
