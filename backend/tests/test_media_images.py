"""Unit tests for `app.services.media_images.strip_exif` (T28, F61).

Pure Pillow-based tests -- no DB/Redis/S3, generates its own tiny
in-memory images with synthetic EXIF for each format.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.core.media_validation import MediaExifStripError
from app.services.media_images import strip_exif


def _jpeg_with_exif() -> bytes:
    image = Image.new("RGB", (4, 4), color=(255, 0, 0))
    exif = image.getexif()
    exif[0x0110] = "Test Camera Model"  # Model tag -- arbitrary EXIF payload
    exif[0x013B] = "Test Artist"  # Artist tag -- a second simple, scalar EXIF field
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def _png_bytes() -> bytes:
    image = Image.new("RGBA", (4, 4), color=(0, 255, 0, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _animated_gif_bytes() -> bytes:
    frame1 = Image.new("RGB", (4, 4), color=(255, 0, 0))
    frame2 = Image.new("RGB", (4, 4), color=(0, 0, 255))
    buffer = io.BytesIO()
    frame1.save(buffer, format="GIF", save_all=True, append_images=[frame2], duration=100, loop=0)
    return buffer.getvalue()


class TestStripExif:
    def test_jpeg_exif_is_removed(self) -> None:
        source = _jpeg_with_exif()
        assert Image.open(io.BytesIO(source)).getexif()  # sanity: source really has EXIF

        stripped = strip_exif(source, content_type="image/jpeg")

        result_image = Image.open(io.BytesIO(stripped))
        assert not result_image.getexif()
        assert result_image.size == (4, 4)

    def test_png_round_trips_without_error(self) -> None:
        source = _png_bytes()
        stripped = strip_exif(source, content_type="image/png")

        result_image = Image.open(io.BytesIO(stripped))
        assert result_image.size == (4, 4)

    def test_animated_gif_preserves_all_frames(self) -> None:
        source = _animated_gif_bytes()
        assert Image.open(io.BytesIO(source)).n_frames == 2

        stripped = strip_exif(source, content_type="image/gif")

        result_image = Image.open(io.BytesIO(stripped))
        assert getattr(result_image, "n_frames", 1) == 2

    def test_malformed_image_is_rejected_not_stored_unstripped(self) -> None:
        with pytest.raises(MediaExifStripError):
            strip_exif(b"this is not a valid image file at all", content_type="image/jpeg")

    def test_unsupported_content_type_is_rejected(self) -> None:
        with pytest.raises(MediaExifStripError):
            strip_exif(_png_bytes(), content_type="image/tiff")

    def test_jpeg_re_encode_preserves_high_quality(self) -> None:
        # T28 code review finding #4: re-saving must not silently drop to
        # Pillow's default JPEG quality (75), which is a visibly lossier
        # result than typical camera/phone output -- assert the stripped
        # bytes decode with the higher `quality=95` this module now uses,
        # by checking the re-encode is not the (smaller, blockier)
        # default-quality result for the same source image.
        image = Image.new("RGB", (64, 64), color=(120, 60, 200))
        for x in range(64):
            for y in range(64):
                image.putpixel((x, y), ((x * 4) % 256, (y * 4) % 256, (x + y) % 256))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=95)
        source = buffer.getvalue()

        stripped = strip_exif(source, content_type="image/jpeg")

        default_quality_buffer = io.BytesIO()
        image.save(default_quality_buffer, format="JPEG", quality=75)
        default_quality_bytes = default_quality_buffer.getvalue()

        # A quality=95 re-encode of a noisy image is reliably larger than
        # a quality=75 re-encode of the same image -- a coarse but stable
        # signal that this module preserved high quality rather than
        # falling back to Pillow's default.
        assert len(stripped) > len(default_quality_bytes)

    def test_visible_content_unchanged_after_strip(self) -> None:
        image = Image.new("RGB", (2, 2), color=(10, 20, 30))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        source = buffer.getvalue()

        stripped = strip_exif(source, content_type="image/png")

        result_image = Image.open(io.BytesIO(stripped)).convert("RGB")
        assert result_image.getpixel((0, 0)) == (10, 20, 30)
