"""Integration tests for `POST /v1/media` + `GET /v1/media/{id}/url` (T28, frozen contract).

Exercises the real routes end-to-end against Postgres + Redis (skipped
when unreachable): per-kind size caps -> `413` (F58), allowlist + SVG
exclusion + sniff mismatch -> `415` (F58), EXIF-strip on image upload
(F61), filename sanitize (F62), missing multipart parts -> `400`, and the
presigned-fetch authorization gate re-checked against **current**
channel membership / DM participation (F59) -> `403`/`404` (uniform for
nonexistent vs. unbound).

`put_object` is monkeypatched (module-level, in `app.services.media`'s
own namespace -- mirrors `app.services.email`'s existing
`monkeypatch.setattr(".aiosmtplib.send", ...)` pattern) for every test
that needs a successful store, since no local MinIO is assumed reachable
in every dev/CI sandbox this suite runs in. Presigned-URL generation
itself (`generate_presigned_get_url`) is never mocked -- it is pure local
request-signing (no network call), so it runs for real even without a
reachable object store.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import generate_id
from app.core.jwt import create_access_token
from app.core.media_validation import SIZE_CAP_BYTES_BY_KIND
from app.core.security import hash_password
from app.models.attachment import Attachment, AttachmentKind
from app.models.channel import Channel
from app.models.channel_member import ChannelMember, ChannelMemberRole
from app.models.message import Message
from app.models.session import Session
from app.models.user import User
from app.services.channels import leave_channel
from tests.conftest import REQUIRED_ENV

pytestmark = pytest.mark.usefixtures("configured_env")


def _test_login_secret() -> str:
    """Not a real secret -- see `test_channels_api.py`'s identical helper."""

    return "correct-horse-1"


def _settings() -> object:
    from app.core.config import Settings

    return Settings(**{k.lower(): v for k, v in REQUIRED_ENV.items()})  # type: ignore[arg-type]


async def _make_user(db: AsyncSession, *, is_active: bool = True) -> User:
    unique = generate_id().hex[-12:]
    user = User(
        id=generate_id(),
        username=f"user{unique}",
        email=f"{unique}@example.com",
        hashed_password=hash_password(_test_login_secret()),
        first_name="Test",
        last_name="User",
        is_active=is_active,
        is_system_admin=False,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_session(db: AsyncSession, user: User) -> Session:
    now = datetime.now(UTC)
    session = Session(
        id=generate_id(),
        user_id=user.id,
        refresh_token_hash=f"hash-{generate_id()}",
        issued_at=now,
        expires_at=now + timedelta(days=30),
        revoked_at=None,
    )
    db.add(session)
    await db.flush()
    return session


def _bearer_token_for(user: User, session: Session) -> str:
    token, _ = create_access_token(
        user_id=str(user.id), session_id=str(session.id), settings=_settings()
    )
    return token


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _authed_user(db: AsyncSession) -> tuple[User, str]:
    user = await _make_user(db)
    session = await _make_session(db, user)
    await db.commit()
    return user, _bearer_token_for(user, session)


async def _make_channel(
    db: AsyncSession, *, creator: User, members: list[User] | None = None
) -> Channel:
    channel = Channel(
        id=generate_id(),
        name=f"channel-{generate_id().hex[-8:]}",
        is_private=False,
        created_by=creator.id,
    )
    db.add(channel)
    await db.flush()
    db.add(ChannelMember(channel_id=channel.id, user_id=creator.id, role=ChannelMemberRole.ADMIN))
    for member in members or []:
        db.add(
            ChannelMember(channel_id=channel.id, user_id=member.id, role=ChannelMemberRole.MEMBER)
        )
    await db.flush()
    return channel


async def _make_channel_message(db: AsyncSession, *, channel: Channel, sender: User) -> Message:
    message = Message(
        id=generate_id(),
        channel_id=channel.id,
        recipient_id=None,
        sender_id=sender.id,
        content="hello",
    )
    db.add(message)
    await db.flush()
    return message


async def _make_dm_message(db: AsyncSession, *, sender: User, recipient: User) -> Message:
    message = Message(
        id=generate_id(),
        channel_id=None,
        recipient_id=recipient.id,
        sender_id=sender.id,
        content="hey",
    )
    db.add(message)
    await db.flush()
    return message


async def _make_attachment(
    db: AsyncSession,
    *,
    uploader: User,
    message_id: object | None = None,
    kind: AttachmentKind = AttachmentKind.IMAGE,
    content_type: str = "image/png",
    filename: str = "screenshot.png",
    byte_size: int = 1024,
) -> Attachment:
    attachment = Attachment(
        id=generate_id(),
        message_id=message_id,
        uploader_id=uploader.id,
        kind=kind,
        content_type=content_type,
        storage_key=f"attachments/{generate_id()}",
        filename=filename,
        byte_size=byte_size,
    )
    db.add(attachment)
    await db.flush()
    return attachment


def _jpeg_bytes_with_exif() -> bytes:
    image = Image.new("RGB", (4, 4), color=(1, 2, 3))
    exif = image.getexif()
    exif[0x0110] = "Test Camera"
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def _fake_put_object(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Monkeypatch `app.services.media.put_object`; returns a dict capturing the last call."""

    captured: dict[str, object] = {}

    async def _fake(
        client: object, *, bucket: str, key: str, body: bytes, content_type: str
    ) -> None:
        captured["body"] = body
        captured["content_type"] = content_type
        captured["key"] = key

    monkeypatch.setattr("app.services.media.put_object", _fake)
    return captured


class TestUploadMedia:
    async def test_uploads_image_strips_exif_and_returns_201(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _, token = await _authed_user(db_session)
        captured = _fake_put_object(monkeypatch)
        source = _jpeg_bytes_with_exif()

        response = client.post(
            "/v1/media",
            headers=_auth_header(token),
            data={"declared_content_type": "image/jpeg", "kind": "image", "filename": "photo.jpg"},
            files={"file": ("photo.jpg", source, "image/jpeg")},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["kind"] == "image"
        assert body["content_type"] == "image/jpeg"
        assert body["filename"] == "photo.jpg"
        assert body["size"] > 0
        assert "media_id" in body and "created_at" in body

        # Stored bytes have EXIF stripped (F61).
        stored = captured["body"]
        assert isinstance(stored, bytes)
        result_image = Image.open(io.BytesIO(stored))
        assert not result_image.getexif()

    async def test_missing_multipart_part_is_400(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, token = await _authed_user(db_session)

        response = client.post(
            "/v1/media",
            headers=_auth_header(token),
            data={"declared_content_type": "image/png", "kind": "image"},
            files={"file": ("x.png", b"\x89PNG\r\n\x1a\n" + b"0" * 32, "image/png")},
        )

        assert response.status_code == 400
        assert response.headers["content-type"] == "application/problem+json"

    async def test_unauthenticated_is_401(self, migrated_db: None, client: TestClient) -> None:
        response = client.post(
            "/v1/media",
            data={"declared_content_type": "image/png", "kind": "image", "filename": "x.png"},
            files={"file": ("x.png", b"\x89PNG\r\n\x1a\n" + b"0" * 32, "image/png")},
        )

        assert response.status_code == 401

    async def test_oversize_image_is_413(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, token = await _authed_user(db_session)
        oversize = b"\x89PNG\r\n\x1a\n" + b"0" * (SIZE_CAP_BYTES_BY_KIND[AttachmentKind.IMAGE] + 1)

        response = client.post(
            "/v1/media",
            headers=_auth_header(token),
            data={"declared_content_type": "image/png", "kind": "image", "filename": "big.png"},
            files={"file": ("big.png", oversize, "image/png")},
        )

        assert response.status_code == 413
        assert response.headers["content-type"] == "application/problem+json"

    async def test_svg_excluded_from_image_allowlist_is_415(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, token = await _authed_user(db_session)
        svg = b"<?xml version='1.0'?><svg xmlns='http://www.w3.org/2000/svg'></svg>"

        response = client.post(
            "/v1/media",
            headers=_auth_header(token),
            data={
                "declared_content_type": "image/svg+xml",
                "kind": "image",
                "filename": "evil.svg",
            },
            files={"file": ("evil.svg", svg, "image/svg+xml")},
        )

        assert response.status_code == 415
        assert response.headers["content-type"] == "application/problem+json"

    async def test_sniff_mismatch_is_415(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, token = await _authed_user(db_session)
        jpeg_bytes = b"\xff\xd8\xff\xe0" + b"0" * 64  # actually a JPEG signature

        response = client.post(
            "/v1/media",
            headers=_auth_header(token),
            data={"declared_content_type": "image/png", "kind": "image", "filename": "x.png"},
            files={"file": ("x.png", jpeg_bytes, "image/png")},
        )

        assert response.status_code == 415

    async def test_disallowed_kind_is_400(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, token = await _authed_user(db_session)

        response = client.post(
            "/v1/media",
            headers=_auth_header(token),
            data={"declared_content_type": "image/png", "kind": "not-a-kind", "filename": "x.png"},
            files={"file": ("x.png", b"\x89PNG\r\n\x1a\n" + b"0" * 32, "image/png")},
        )

        assert response.status_code == 400

    async def test_kind_file_real_image_bytes_rejected_even_with_matching_declared_type(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        # T28 code review blocker #1: a real image uploaded as kind=file
        # with a declared_content_type that happens to match the real
        # bytes must still be rejected -- kind=file must never be usable
        # to bypass the mandatory EXIF-strip requirement (F61) or the
        # smaller image size cap.
        _, token = await _authed_user(db_session)
        source = _jpeg_bytes_with_exif()

        response = client.post(
            "/v1/media",
            headers=_auth_header(token),
            data={"declared_content_type": "image/jpeg", "kind": "file", "filename": "photo.jpg"},
            files={"file": ("photo.jpg", source, "image/jpeg")},
        )

        assert response.status_code == 415
        assert response.headers["content-type"] == "application/problem+json"

    async def test_kind_file_denylisted_content_type_is_415(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        # T28 security review HIGH-2: kind=file must reject browser-active
        # declared types outright, even for bytes the sniffer doesn't
        # otherwise recognize (plain HTML/JS).
        _, token = await _authed_user(db_session)

        response = client.post(
            "/v1/media",
            headers=_auth_header(token),
            data={
                "declared_content_type": "text/html",
                "kind": "file",
                "filename": "evil.html",
            },
            files={"file": ("evil.html", b"<script>alert(1)</script>", "text/html")},
        )

        assert response.status_code == 415
        assert response.headers["content-type"] == "application/problem+json"

    async def test_filename_is_sanitized(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _, token = await _authed_user(db_session)
        _fake_put_object(monkeypatch)

        response = client.post(
            "/v1/media",
            headers=_auth_header(token),
            data={
                "declared_content_type": "application/pdf",
                "kind": "file",
                "filename": "../../etc/passwd.pdf",
            },
            files={"file": ("evil.pdf", b"%PDF-1.4\n" + b"0" * 32, "application/pdf")},
        )

        assert response.status_code == 201
        assert response.json()["filename"] == "passwd.pdf"

    async def test_kind_file_stored_content_type_is_forced_octet_stream(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # T28 security review HIGH-2 / code review finding #2: the
        # declared content_type is never trusted as the *stored* S3
        # object Content-Type for kind=file -- only used for API/client
        # display. The response body still echoes the client's declared
        # type (informational), but the object actually written to the
        # bucket is always application/octet-stream.
        _, token = await _authed_user(db_session)
        captured = _fake_put_object(monkeypatch)

        response = client.post(
            "/v1/media",
            headers=_auth_header(token),
            data={
                "declared_content_type": "application/pdf",
                "kind": "file",
                "filename": "doc.pdf",
            },
            files={"file": ("doc.pdf", b"%PDF-1.4\n" + b"0" * 32, "application/pdf")},
        )

        assert response.status_code == 201
        assert response.json()["content_type"] == "application/pdf"
        assert captured["content_type"] == "application/octet-stream"


class TestGetMediaUrl:
    async def test_channel_member_gets_signed_url(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        uploader, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=uploader)
        message = await _make_channel_message(db_session, channel=channel, sender=uploader)
        attachment = await _make_attachment(db_session, uploader=uploader, message_id=message.id)
        await db_session.commit()

        response = client.get(f"/v1/media/{attachment.id}/url", headers=_auth_header(token))

        assert response.status_code == 200
        body = response.json()
        assert body["content_type"] == "image/png"
        assert body["filename"] == "screenshot.png"
        assert body["size"] == 1024
        assert isinstance(body["url"], str) and body["url"]
        assert "expires_at" in body

    async def test_non_member_gets_403(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        uploader, _ = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=uploader)
        message = await _make_channel_message(db_session, channel=channel, sender=uploader)
        attachment = await _make_attachment(db_session, uploader=uploader, message_id=message.id)
        _, outsider_token = await _authed_user(db_session)
        await db_session.commit()

        response = client.get(
            f"/v1/media/{attachment.id}/url", headers=_auth_header(outsider_token)
        )

        assert response.status_code == 403

    async def test_unbound_media_is_404(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        uploader, token = await _authed_user(db_session)
        attachment = await _make_attachment(db_session, uploader=uploader, message_id=None)
        await db_session.commit()

        response = client.get(f"/v1/media/{attachment.id}/url", headers=_auth_header(token))

        assert response.status_code == 404

    async def test_nonexistent_media_is_404(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, token = await _authed_user(db_session)

        response = client.get(f"/v1/media/{generate_id()}/url", headers=_auth_header(token))

        assert response.status_code == 404

    async def test_dm_participant_gets_signed_url(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        sender, sender_token = await _authed_user(db_session)
        recipient, _ = await _authed_user(db_session)
        message = await _make_dm_message(db_session, sender=sender, recipient=recipient)
        attachment = await _make_attachment(db_session, uploader=sender, message_id=message.id)
        await db_session.commit()

        response = client.get(f"/v1/media/{attachment.id}/url", headers=_auth_header(sender_token))

        assert response.status_code == 200

    async def test_dm_non_participant_gets_403(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        sender, _ = await _authed_user(db_session)
        recipient, _ = await _authed_user(db_session)
        message = await _make_dm_message(db_session, sender=sender, recipient=recipient)
        attachment = await _make_attachment(db_session, uploader=sender, message_id=message.id)
        _, outsider_token = await _authed_user(db_session)
        await db_session.commit()

        response = client.get(
            f"/v1/media/{attachment.id}/url", headers=_auth_header(outsider_token)
        )

        assert response.status_code == 403

    async def test_unauthenticated_is_401(self, migrated_db: None, client: TestClient) -> None:
        response = client.get(f"/v1/media/{generate_id()}/url")

        assert response.status_code == 401

    async def test_kind_file_url_forces_download_disposition_and_octet_stream(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        # T28 security review HIGH-2 / code review finding #2: a
        # presigned URL for kind=file media must force a download
        # (Content-Disposition: attachment) and a non-rendering
        # Content-Type, regardless of what was declared at upload time --
        # otherwise a direct-navigation open could render/execute
        # attacker-controlled content in the browser.
        uploader, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=uploader)
        message = await _make_channel_message(db_session, channel=channel, sender=uploader)
        attachment = await _make_attachment(
            db_session,
            uploader=uploader,
            message_id=message.id,
            kind=AttachmentKind.FILE,
            content_type="application/pdf",
            filename="report.pdf",
        )
        await db_session.commit()

        response = client.get(f"/v1/media/{attachment.id}/url", headers=_auth_header(token))

        assert response.status_code == 200
        url = unquote(response.json()["url"])
        assert 'response-content-disposition=attachment; filename="report.pdf"' in url
        assert "response-content-type=application/octet-stream" in url

    async def test_image_url_does_not_force_download_disposition(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        # Contrast case: kind=image (a strictly allowlisted, safe raster
        # type) is unaffected -- no forced download override.
        uploader, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=uploader)
        message = await _make_channel_message(db_session, channel=channel, sender=uploader)
        attachment = await _make_attachment(db_session, uploader=uploader, message_id=message.id)
        await db_session.commit()

        response = client.get(f"/v1/media/{attachment.id}/url", headers=_auth_header(token))

        assert response.status_code == 200
        url = unquote(response.json()["url"])
        assert "response-content-disposition" not in url

    async def test_media_on_soft_deleted_message_is_404(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        # T28 code review finding #3: once the bound message is
        # soft-deleted, its media must no longer be fetchable, matching
        # every other endpoint's `deleted_at IS NULL` filtering.
        uploader, token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=uploader)
        message = await _make_channel_message(db_session, channel=channel, sender=uploader)
        attachment = await _make_attachment(db_session, uploader=uploader, message_id=message.id)
        message.deleted_at = datetime.now(UTC)
        await db_session.commit()

        response = client.get(f"/v1/media/{attachment.id}/url", headers=_auth_header(token))

        assert response.status_code == 404

    async def test_member_who_left_channel_loses_access_to_current_membership_check(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        # T28 code review finding #6: distinguishes F59's "CURRENT
        # membership" re-check from a naive stale-membership check -- a
        # member who uploaded/bound media, then left the channel, must be
        # rejected on a subsequent fetch even though they were a member
        # at bind time.
        creator = await _make_user(db_session)
        member, member_token = await _authed_user(db_session)
        channel = await _make_channel(db_session, creator=creator, members=[member])
        message = await _make_channel_message(db_session, channel=channel, sender=member)
        attachment = await _make_attachment(db_session, uploader=member, message_id=message.id)
        await db_session.commit()

        await leave_channel(db_session, channel_id=channel.id, user_id=member.id)
        await db_session.commit()

        response = client.get(
            f"/v1/media/{attachment.id}/url", headers=_auth_header(member_token)
        )

        assert response.status_code == 403
