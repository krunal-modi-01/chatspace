"""EXIF-strip-or-reject pipeline for uploaded images (T28, F61, ADR-0007).

F61: "EXIF metadata (including GPS) is stripped from uploaded images
before storage; visible content is otherwise unchanged... if stripping
fails on a malformed image, the upload is rejected rather than stored
unstripped." Applies to the image allowlist only (`kind=image`), never to
`file`/`video` uploads.

Uses Pillow (named explicitly by ADR-0007's decision record). Opening an
image and re-saving it without forwarding the source `exif`/metadata
info Pillow attaches to `Image.info` is sufficient to drop EXIF for every
format in the image allowlist (PNG `eXIf` chunk, JPEG APP1 EXIF segment,
WEBP EXIF chunk) — Pillow never *writes* EXIF on save unless a caller
explicitly passes `exif=...`, which this module never does.

Orientation is applied (`ImageOps.exif_transpose`) *before* the EXIF tag
that encodes it is dropped, so the stripped image still looks the same
as the original when rendered (F61: "visible content is otherwise
unchanged") rather than silently losing its correct rotation.

Animated GIF/WEBP: every frame is preserved (`save_all=True`), not just
the first, so a multi-frame upload does not lose its animation as a side
effect of the strip.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps, ImageSequence

from app.core.media_validation import MediaExifStripError

_PILLOW_FORMAT_BY_CONTENT_TYPE: dict[str, str] = {
    "image/png": "PNG",
    "image/jpeg": "JPEG",
    "image/gif": "GIF",
    "image/webp": "WEBP",
}


def strip_exif(data: bytes, *, content_type: str) -> bytes:
    """Return `data` re-encoded with EXIF metadata removed.

    Raises `MediaExifStripError` (-> `415`, F61) if `content_type` has no
    known strip handler, or if the image cannot be decoded/re-encoded
    (a malformed image is rejected outright, never stored unstripped).
    """

    pillow_format = _PILLOW_FORMAT_BY_CONTENT_TYPE.get(content_type)
    if pillow_format is None:
        raise MediaExifStripError(f"no EXIF-strip handler for content_type '{content_type}'.")

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:
        raise MediaExifStripError(
            "image could not be decoded; rejecting rather than storing unstripped."
        ) from exc

    try:
        n_frames = getattr(image, "n_frames", 1)
        buffer = io.BytesIO()

        # Preserve visual fidelity (F61: "visible content is otherwise
        # unchanged") -- re-encoding at Pillow's default JPEG/WEBP quality
        # (75) is a visibly lossier, lower-quality result than the
        # original, and dropping the ICC color profile can shift colors.
        # Neither `quality` nor `icc_profile` carries EXIF/GPS data, so
        # preserving them does not reintroduce anything F61 requires
        # stripped.
        fidelity_kwargs: dict[str, object] = {}
        if pillow_format in ("JPEG", "WEBP"):
            fidelity_kwargs["quality"] = 95
        if "icc_profile" in image.info:
            fidelity_kwargs["icc_profile"] = image.info["icc_profile"]

        if n_frames > 1:
            frames = [
                ImageOps.exif_transpose(frame.copy()) for frame in ImageSequence.Iterator(image)
            ]
            save_kwargs: dict[str, object] = {
                "save_all": True,
                "append_images": frames[1:],
                **fidelity_kwargs,
            }
            if "duration" in image.info:
                save_kwargs["duration"] = image.info["duration"]
            if "loop" in image.info:
                save_kwargs["loop"] = image.info["loop"]
            frames[0].save(buffer, format=pillow_format, **save_kwargs)
        else:
            oriented = ImageOps.exif_transpose(image)
            if pillow_format == "JPEG" and oriented.mode in ("RGBA", "P"):
                oriented = oriented.convert("RGB")
            oriented.save(buffer, format=pillow_format, **fidelity_kwargs)
    except MediaExifStripError:
        raise
    except Exception as exc:
        raise MediaExifStripError("failed to re-encode image while stripping EXIF.") from exc

    return buffer.getvalue()
