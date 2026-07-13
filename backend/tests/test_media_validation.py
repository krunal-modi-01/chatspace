"""Unit tests for `app.core.media_validation` (T28, F58/F62).

Pure functions -- no DB/Redis/S3, no fixtures needed beyond plain pytest.
"""

from __future__ import annotations

import pytest

from app.core.media_validation import (
    InvalidMediaKindError,
    MediaSniffMismatchError,
    MediaTypeDisallowedError,
    parse_kind,
    sanitize_filename,
    sniff_content_type,
    validate_allowlist,
    validate_sniff_match,
)
from app.models.attachment import AttachmentKind

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
_JPEG_MAGIC = b"\xff\xd8\xff\xe0" + b"\x00" * 32
_GIF_MAGIC = b"GIF89a" + b"\x00" * 32
_WEBP_MAGIC = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 32
_MP4_MAGIC = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32
_WEBM_MAGIC = b"\x1a\x45\xdf\xa3" + b"\x00" * 32
_SVG_TEXT = b"<?xml version='1.0'?><svg xmlns='http://www.w3.org/2000/svg'></svg>"
_PDF_MAGIC = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n" + b"\x00" * 32
_JUNK = b"not a real media file at all, just some bytes" * 4


class TestParseKind:
    @pytest.mark.parametrize("raw", ["image", "file", "video", "IMAGE", " video "])
    def test_valid_kinds_parse(self, raw: str) -> None:
        assert isinstance(parse_kind(raw), AttachmentKind)

    @pytest.mark.parametrize("raw", ["", "photo", "images", "svg"])
    def test_invalid_kind_raises(self, raw: str) -> None:
        with pytest.raises(InvalidMediaKindError):
            parse_kind(raw)


class TestValidateAllowlist:
    @pytest.mark.parametrize("content_type", ["image/png", "image/jpeg", "image/gif", "image/webp"])
    def test_image_allowlist_accepts_documented_types(self, content_type: str) -> None:
        validate_allowlist(AttachmentKind.IMAGE, content_type)

    def test_image_allowlist_excludes_svg(self) -> None:
        with pytest.raises(MediaTypeDisallowedError):
            validate_allowlist(AttachmentKind.IMAGE, "image/svg+xml")

    def test_image_allowlist_rejects_arbitrary_type(self) -> None:
        with pytest.raises(MediaTypeDisallowedError):
            validate_allowlist(AttachmentKind.IMAGE, "application/octet-stream")

    @pytest.mark.parametrize("content_type", ["video/mp4", "video/webm"])
    def test_video_allowlist_accepts_documented_types(self, content_type: str) -> None:
        validate_allowlist(AttachmentKind.VIDEO, content_type)

    def test_video_allowlist_rejects_other_types(self) -> None:
        with pytest.raises(MediaTypeDisallowedError):
            validate_allowlist(AttachmentKind.VIDEO, "video/quicktime")

    @pytest.mark.parametrize("content_type", ["application/pdf", "text/plain", "application/zip"])
    def test_file_kind_has_no_fixed_allowlist(self, content_type: str) -> None:
        validate_allowlist(AttachmentKind.FILE, content_type)

    @pytest.mark.parametrize(
        "content_type",
        [
            "text/html",
            "text/xml",
            "application/xhtml+xml",
            "application/javascript",
            "text/javascript",
            "image/svg+xml",
        ],
    )
    def test_file_kind_denylists_browser_active_types(self, content_type: str) -> None:
        # T28 security review HIGH-2: these must never be storable/servable
        # under kind=file, since a presigned GET URL served with one of
        # these Content-Types would render/execute in a browser.
        with pytest.raises(MediaTypeDisallowedError):
            validate_allowlist(AttachmentKind.FILE, content_type)


class TestSniffContentType:
    def test_png_signature(self) -> None:
        assert sniff_content_type(_PNG_MAGIC) == "image/png"

    def test_jpeg_signature(self) -> None:
        assert sniff_content_type(_JPEG_MAGIC) == "image/jpeg"

    def test_gif_signature(self) -> None:
        assert sniff_content_type(_GIF_MAGIC) == "image/gif"

    def test_webp_signature(self) -> None:
        assert sniff_content_type(_WEBP_MAGIC) == "image/webp"

    def test_mp4_signature(self) -> None:
        assert sniff_content_type(_MP4_MAGIC) == "video/mp4"

    def test_webm_signature(self) -> None:
        assert sniff_content_type(_WEBM_MAGIC) == "video/webm"

    def test_svg_text_signature(self) -> None:
        assert sniff_content_type(_SVG_TEXT) == "image/svg+xml"

    def test_unrecognized_bytes_return_none(self) -> None:
        assert sniff_content_type(_JUNK) is None
        assert sniff_content_type(_PDF_MAGIC) is None


class TestValidateSniffMatch:
    def test_image_match_passes(self) -> None:
        validate_sniff_match(AttachmentKind.IMAGE, "image/png", "image/png")

    def test_image_mismatch_raises(self) -> None:
        with pytest.raises(MediaSniffMismatchError):
            validate_sniff_match(AttachmentKind.IMAGE, "image/png", "image/jpeg")

    def test_image_unrecognized_sniff_raises(self) -> None:
        with pytest.raises(MediaSniffMismatchError):
            validate_sniff_match(AttachmentKind.IMAGE, "image/png", None)

    def test_video_mismatch_raises(self) -> None:
        with pytest.raises(MediaSniffMismatchError):
            validate_sniff_match(AttachmentKind.VIDEO, "video/mp4", "video/webm")

    def test_file_kind_allows_unrecognized_sniff(self) -> None:
        # A generic file (PDF, zip, etc.) whose signature this module does
        # not enumerate must not be rejected merely for being unrecognized.
        validate_sniff_match(AttachmentKind.FILE, "application/pdf", None)

    def test_file_kind_rejects_disguised_image(self) -> None:
        # Actual bytes are a PNG but declared as a generic file type --
        # this is exactly the bypass-EXIF-strip/size-cap attempt the
        # sniff-match rule must catch even for kind=file.
        with pytest.raises(MediaSniffMismatchError):
            validate_sniff_match(AttachmentKind.FILE, "application/octet-stream", "image/png")

    @pytest.mark.parametrize(
        "content_type,sniffed",
        [
            ("image/png", "image/png"),
            ("image/jpeg", "image/jpeg"),
            ("image/svg+xml", "image/svg+xml"),
        ],
    )
    def test_file_kind_rejects_real_image_even_when_declared_type_matches(
        self, content_type: str, sniffed: str
    ) -> None:
        # T28 code review blocker #1: kind=file must never be usable to
        # store a real image byte-for-byte, even when the client is
        # "honest" about the declared content_type -- otherwise kind=file
        # bypasses the mandatory EXIF-strip requirement (F61) and the
        # smaller image size cap entirely. The client must resubmit as
        # kind=image.
        with pytest.raises(MediaSniffMismatchError):
            validate_sniff_match(AttachmentKind.FILE, content_type, sniffed)

    def test_file_kind_matching_declared_video_type_is_fine(self) -> None:
        # Video carries no EXIF-strip requirement, so a correctly-labeled
        # video under kind=file is not a bypass of anything -- unlike
        # images, it is still allowed when sniff == declared.
        validate_sniff_match(AttachmentKind.FILE, "video/mp4", "video/mp4")


class TestSanitizeFilename:
    def test_plain_name_preserved(self) -> None:
        assert sanitize_filename("screenshot.png") == "screenshot.png"

    def test_path_traversal_stripped_unix(self) -> None:
        assert sanitize_filename("../../etc/passwd") == "passwd"

    def test_path_traversal_stripped_windows(self) -> None:
        assert sanitize_filename("..\\..\\Windows\\System32\\evil.exe") == "evil.exe"

    def test_unsafe_characters_replaced(self) -> None:
        result = sanitize_filename("weird<>:name?.png")
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result
        assert "?" not in result

    def test_empty_input_falls_back(self) -> None:
        assert sanitize_filename("") == "file"

    def test_only_dots_falls_back(self) -> None:
        assert sanitize_filename("...") == "file"

    def test_long_name_truncated(self) -> None:
        result = sanitize_filename("a" * 500 + ".png")
        assert len(result) <= 255

    def test_never_raises(self) -> None:
        for candidate in ["/", "\\", "..", ".", "   ", "\x00\x01", "😀.png"]:
            sanitize_filename(candidate)  # must not raise
