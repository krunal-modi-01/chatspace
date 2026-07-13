"""Pure media-upload validation helpers for `POST /v1/media` (T28, F58/F62).

Everything here is side-effect-free (no DB, no network, no filesystem) so
it is unit-testable without Postgres/Redis/S3 — only
`app.services.media` wires these into the actual upload pipeline
alongside the DB/S3 I/O.

## Size caps (F58, mirrors the shipped `ck_attachments_size_cap` CHECK)

image 10 MB, file 50 MB, video 200 MB — see `SIZE_CAP_BYTES_BY_KIND`.
Enforced *before* the size cap is reached (streaming, bounded read — see
`app.services.media.read_upload_within_limit`), not just re-validated
after the fact, so a client cannot force the app to buffer an
arbitrarily large body into memory before rejecting it.

## Content-type allowlist + SVG exclusion + sniff match (F58)

- `kind=image`: declared `content_type` must be one of
  `image/png|jpeg|gif|webp` — `image/svg+xml` is explicitly excluded, per
  the frozen contract, even though SVG is nominally XML/text (a
  raster-image allowlist that deliberately omits vector/active content).
- `kind=video`: declared `content_type` must be one of
  `video/mp4|webm`.
- `kind=file`: the frozen contract defines no fixed allowlist for this
  kind (only image/video have documented allowlists), but a small
  denylist of browser-active declared types (`text/html`, `text/xml`,
  `application/xhtml+xml`, `application/javascript`, `text/javascript`,
  `image/svg+xml`) is rejected outright, since those would render/execute
  in a browser if a presigned GET URL for the object were ever opened
  directly (T28 security review HIGH-2) -- see also
  `app.services.media_storage.generate_presigned_get_url`'s
  `kind=file`-only `Content-Disposition: attachment` override, a second,
  independent layer against the same risk.
- **Sniff match:** the actual bytes are sniffed via magic-byte signatures
  (`sniff_content_type`) and must agree with the declared type for
  `image`/`video` kinds (unrecognized sniff -> mismatch, since an image/
  video upload whose bytes don't match any allowed signature is not a
  valid instance of the declared type either). For `kind=file`, **any**
  positively-recognized image/SVG signature (`image/png|jpeg|gif|webp|
  svg+xml`) is rejected unconditionally -- even when it matches the
  declared `content_type` -- because `kind=file` must never carry real
  image bytes: allowing it would let a client bypass the mandatory
  EXIF-strip-or-reject requirement (F61) and the smaller `image` size cap
  by simply mislabeling the upload's `kind`. A client with a real image
  must resubmit it as `kind=image`. A positively-recognized *video*
  signature is still only rejected when it *contradicts* the declared
  type (video carries no EXIF-strip requirement, so there is nothing to
  bypass by using `kind=file` for a correctly-labeled video, beyond a
  stricter size cap). An unrecognized (e.g. PDF, zip, plain-text)
  signature is not itself an error for `file` uploads, since this module
  intentionally does not attempt to enumerate every possible generic-file
  magic number.
"""

from __future__ import annotations

import os
import re
from pathlib import PurePosixPath

from app.models.attachment import AttachmentKind

# --- Size caps (F58 / `ck_attachments_size_cap`) ----------------------------

_MB = 1024 * 1024

SIZE_CAP_BYTES_BY_KIND: dict[AttachmentKind, int] = {
    AttachmentKind.IMAGE: 10 * _MB,
    AttachmentKind.FILE: 50 * _MB,
    AttachmentKind.VIDEO: 200 * _MB,
}

# --- Allowlists (F58) --------------------------------------------------------

ALLOWED_CONTENT_TYPES_BY_KIND: dict[AttachmentKind, frozenset[str]] = {
    AttachmentKind.IMAGE: frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"}),
    AttachmentKind.VIDEO: frozenset({"video/mp4", "video/webm"}),
}

EXCLUDED_IMAGE_CONTENT_TYPE = "image/svg+xml"

# Declared `content_type` values that are always rejected for `kind=file`,
# regardless of what the bytes sniff as (T28 security review HIGH-2): every
# one of these renders or executes in a browser if opened directly from a
# presigned GET URL, which `kind=file` otherwise places no allowlist
# restriction on. This is a defense-in-depth layer alongside
# `generate_presigned_get_url`'s `kind=file`-only forced download
# disposition -- neither is relied on alone.
_FILE_KIND_DENYLISTED_CONTENT_TYPES = frozenset(
    {
        "text/html",
        "text/xml",
        "application/xhtml+xml",
        "application/javascript",
        "text/javascript",
        "image/svg+xml",
    }
)

# Content types this module's sniffer can positively recognize as an image
# (including SVG) by magic bytes/signature -- any `kind=file` upload whose
# bytes sniff as one of these is unconditionally rejected (see module
# docstring): real image bytes must always go through `kind=image`.
_SNIFFABLE_IMAGE_TYPES = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "image/svg+xml",
    }
)

# Content types this module's sniffer can positively recognize by magic
# bytes/signature — used to decide when a `kind=file` upload's sniffed
# *video* type is suspicious enough to reject because it contradicts the
# declared type (see module docstring).
_SNIFFABLE_IMAGE_OR_VIDEO_TYPES = _SNIFFABLE_IMAGE_TYPES | frozenset(
    {
        "video/mp4",
        "video/webm",
    }
)

# ISO-BMFF ("ftyp" box) major-brand 4CCs that identify a genuine MP4 video
# container (T28 code review Major #3). A bare `data[4:8] == b"ftyp"` check
# alone matches *any* ISO-BMFF-family file -- HEIC/HEIF, AVIF, QuickTime
# `.mov`, and `.m4a` audio all share the same outer box structure -- so
# `sniff_content_type` additionally requires the major brand at bytes
# `8:12` to be one of these known MP4-video brands before returning
# `"video/mp4"`. Anything else (including HEIC/HEIF `heic`/`heix`/`heic`/
# `mif1`/`msf1`, AVIF `avif`/`avis`, QuickTime `qt  `, and M4A audio
# `M4A `/`M4P `) sniffs as unrecognized (`None`) instead, which correctly
# *fails* `validate_sniff_match` for a declared `video/mp4` upload rather
# than silently confirming it. Without this, a real (often GPS/EXIF-
# bearing) HEIC photo relabeled `kind=video`/`video/mp4` would sail
# through: only `kind=image` uploads are ever passed through
# `app.services.media_images.strip_exif`, so mislabeling a photo as a
# video is a way to store it with its EXIF/GPS metadata intact, bypassing
# the mandatory EXIF-strip-or-reject requirement (F61).
_MP4_MAJOR_BRANDS = frozenset(
    {
        b"isom",
        b"iso2",
        b"iso3",
        b"iso4",
        b"iso5",
        b"iso6",
        b"mp41",
        b"mp42",
        b"avc1",
        b"M4V ",
        b"3gp4",
        b"3gp5",
        b"3g2a",
        b"mmp4",
        b"dash",
        b"f4v ",
    }
)


class InvalidMediaKindError(Exception):
    """`kind` is not one of `image|file|video` — `400` (malformed part)."""


class MediaSizeExceededError(Exception):
    """Upload exceeds its kind's size cap — `413` (F58)."""


class MediaTypeDisallowedError(Exception):
    """Declared `content_type` is not in the kind's allowlist, or is SVG — `415` (F58)."""


class MediaSniffMismatchError(Exception):
    """Sniffed bytes do not match the declared `content_type` — `415` (F58)."""


class MediaExifStripError(Exception):
    """EXIF-strip failed (malformed image) — `415` (F61)."""


def parse_kind(raw: str) -> AttachmentKind:
    """Parse the multipart `kind` part, raising `InvalidMediaKindError` on a bad value."""

    try:
        return AttachmentKind(raw.strip().lower())
    except ValueError:
        raise InvalidMediaKindError(f"'{raw}' is not a valid media kind.") from None


def validate_allowlist(kind: AttachmentKind, content_type: str) -> None:
    """Raise `MediaTypeDisallowedError` if `content_type` is not permitted for `kind`."""

    if kind == AttachmentKind.FILE:
        if content_type in _FILE_KIND_DENYLISTED_CONTENT_TYPES:
            raise MediaTypeDisallowedError(
                f"content_type '{content_type}' is not allowed for kind='file' "
                "(browser-active type)."
            )
        return  # no fixed allowlist beyond the denylist above (see module docstring)

    allowed = ALLOWED_CONTENT_TYPES_BY_KIND[kind]
    if content_type not in allowed:
        raise MediaTypeDisallowedError(
            f"content_type '{content_type}' is not allowed for kind='{kind.value}'."
        )


def sniff_content_type(data: bytes) -> str | None:
    """Best-effort magic-byte content-type sniff; `None` if unrecognized.

    Recognizes exactly the allowed image/video signatures plus SVG (which
    must be positively detected so it can be rejected even when
    mislabeled as something else). Deliberately does not attempt to
    enumerate every possible file-format signature — see the module
    docstring's `kind=file` rationale.
    """

    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in _MP4_MAJOR_BRANDS:
        return "video/mp4"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    if _looks_like_svg(data):
        return "image/svg+xml"
    return None


def _looks_like_svg(data: bytes) -> bool:
    head = data[:512].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return head.startswith(b"<?xml") or head.startswith(b"<svg") or b"<svg" in head


def validate_sniff_match(kind: AttachmentKind, content_type: str, sniffed: str | None) -> None:
    """Raise `MediaSniffMismatchError` on a sniff/declared-type mismatch (F58).

    `image`/`video`: the sniff must positively confirm the declared type.
    `file`: real image bytes (`png|jpeg|gif|webp|svg+xml`) are rejected
    *unconditionally* — even when they match the declared `content_type`
    — because `kind=file` must never be used to smuggle a real image past
    the mandatory EXIF-strip requirement (F61) or the smaller `image` size
    cap (T28 code review blocker #1). A sniffed *video* signature is only
    rejected when it contradicts the declared type — see module
    docstring.
    """

    if kind in (AttachmentKind.IMAGE, AttachmentKind.VIDEO):
        if sniffed is None or sniffed != content_type:
            raise MediaSniffMismatchError(
                f"sniffed content does not match declared content_type '{content_type}'."
            )
        return

    # kind == FILE
    if sniffed is not None and sniffed in _SNIFFABLE_IMAGE_TYPES:
        raise MediaSniffMismatchError(
            f"sniffed content ({sniffed}) is a real image and must be uploaded with "
            "kind='image', not 'file'."
        )
    if (
        sniffed is not None
        and sniffed in _SNIFFABLE_IMAGE_OR_VIDEO_TYPES
        and sniffed != content_type
    ):
        raise MediaSniffMismatchError(
            f"sniffed content ({sniffed}) contradicts declared content_type '{content_type}'."
        )


# --- Filename sanitisation (F62) --------------------------------------------

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._ -]")
_MAX_FILENAME_LENGTH = 255
_FALLBACK_FILENAME = "file"


def sanitize_filename(raw: str) -> str:
    """Sanitize an uploaded filename (F62): no path traversal, no unsafe chars.

    - Strips any directory components (path-traversal defense) by taking
      only the final path segment, tolerating both `/` and `\\` separators.
    - Drops leading dots (defends against a sanitized name collapsing to a
      hidden dotfile, and against a bare `..`/`.` surviving basename-only
      stripping).
    - Replaces any character outside a conservative allowlist
      (alnum, `.`, `_`, `-`, space) with `_`.
    - Falls back to a fixed generic name if nothing usable survives, and
      truncates to a bounded length.

    Never raises: every input maps to *some* safe, non-empty filename.
    """

    normalized = raw.strip().replace("\\", "/")
    candidate = PurePosixPath(normalized).name or os.path.basename(normalized)
    candidate = candidate.lstrip(".")
    candidate = _UNSAFE_FILENAME_CHARS.sub("_", candidate).strip()
    if not candidate:
        candidate = _FALLBACK_FILENAME
    return candidate[:_MAX_FILENAME_LENGTH]
