"""Integration tests for `app.services.media_sweep.sweep_orphaned_media` (T28, F62).

Exercises the real orphan-sweep query against Postgres (skipped when
unreachable): only unbound (`message_id IS NULL`) rows past the TTL are
swept; bound rows and not-yet-expired orphans are left alone; a purge
failure leaves its row in place for the next run rather than deleting
metadata for bytes that were never actually removed.

`delete_object` is monkeypatched (module-level, in
`app.services.media_sweep`'s own namespace) since no local MinIO is
assumed reachable in every dev/CI sandbox this suite runs in.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import generate_id
from app.core.security import hash_password
from app.models.attachment import Attachment, AttachmentKind
from app.models.message import Message
from app.models.user import User
from app.services.media_storage import MediaStorageError
from app.services.media_sweep import sweep_orphaned_media

pytestmark = pytest.mark.usefixtures("configured_env")


async def _make_user(db: AsyncSession) -> User:
    unique = generate_id().hex[-12:]
    user = User(
        id=generate_id(),
        username=f"user{unique}",
        email=f"{unique}@example.com",
        hashed_password=hash_password("correct-horse-1"),
        first_name="Test",
        last_name="User",
        is_active=True,
        is_system_admin=False,
    )
    db.add(user)
    await db.flush()
    return user


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
    db: AsyncSession, *, uploader: User, message_id: object | None, created_at: datetime
) -> Attachment:
    attachment = Attachment(
        id=generate_id(),
        message_id=message_id,
        uploader_id=uploader.id,
        kind=AttachmentKind.IMAGE,
        content_type="image/png",
        storage_key=f"attachments/{generate_id()}",
        filename="screenshot.png",
        byte_size=1024,
        created_at=created_at,
    )
    db.add(attachment)
    await db.flush()
    return attachment


def _fake_delete_object(
    monkeypatch: pytest.MonkeyPatch, *, fail_keys: set[str] | None = None
) -> list[str]:
    calls: list[str] = []
    fail_keys = fail_keys or set()

    async def _fake(client: object, *, bucket: str, key: str) -> None:
        calls.append(key)
        if key in fail_keys:
            raise MediaStorageError("simulated purge failure")

    monkeypatch.setattr("app.services.media_sweep.delete_object", _fake)
    return calls


class TestSweepOrphanedMedia:
    async def test_sweeps_only_expired_unbound_rows(
        self, migrated_db: None, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        uploader = await _make_user(db_session)
        recipient = await _make_user(db_session)
        message = await _make_dm_message(db_session, sender=uploader, recipient=recipient)
        now = datetime.now(UTC)

        old_orphan = await _make_attachment(
            db_session, uploader=uploader, message_id=None, created_at=now - timedelta(hours=48)
        )
        fresh_orphan = await _make_attachment(
            db_session, uploader=uploader, message_id=None, created_at=now - timedelta(minutes=5)
        )
        bound = await _make_attachment(
            db_session,
            uploader=uploader,
            message_id=message.id,
            created_at=now - timedelta(hours=48),
        )
        await db_session.commit()

        _fake_delete_object(monkeypatch)

        result = await sweep_orphaned_media(
            db_session, object(), ttl=timedelta(hours=24), batch_size=500
        )

        assert result.scanned == 1
        assert result.purged == 1
        assert result.purge_failures == 0

        remaining_ids = set((await db_session.execute(select(Attachment.id))).scalars().all())
        assert old_orphan.id not in remaining_ids
        assert fresh_orphan.id in remaining_ids
        assert bound.id in remaining_ids

    async def test_purge_failure_retains_row_for_next_run(
        self, migrated_db: None, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        uploader = await _make_user(db_session)
        now = datetime.now(UTC)
        orphan = await _make_attachment(
            db_session, uploader=uploader, message_id=None, created_at=now - timedelta(hours=48)
        )
        await db_session.commit()

        _fake_delete_object(monkeypatch, fail_keys={orphan.storage_key})

        result = await sweep_orphaned_media(db_session, object(), ttl=timedelta(hours=24))

        assert result.scanned == 1
        assert result.purged == 0
        assert result.purge_failures == 1

        remaining = await db_session.get(Attachment, orphan.id)
        assert remaining is not None  # row retained, not deleted, per module docstring

    async def test_row_bound_between_scan_and_processing_is_not_purged_or_deleted(
        self, migrated_db: None, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression test for T28 code review Major #2 (sweep/bind race).

        Two rows are both eligible in the initial batch scan. While the
        *first* row processed is being purged, something binds the
        *second* row to a message (mirroring `_bind_media_atomically`
        landing between the scan and this sweep reaching that row). The
        per-row `SELECT ... FOR UPDATE` re-check must detect this and skip
        the bound row entirely -- no purge call, no row deletion -- rather
        than deleting object bytes and metadata a message now references.
        """

        uploader = await _make_user(db_session)
        recipient = await _make_user(db_session)
        message = await _make_dm_message(db_session, sender=uploader, recipient=recipient)
        now = datetime.now(UTC)

        orphan_a = await _make_attachment(
            db_session, uploader=uploader, message_id=None, created_at=now - timedelta(hours=48)
        )
        orphan_b = await _make_attachment(
            db_session, uploader=uploader, message_id=None, created_at=now - timedelta(hours=48)
        )
        await db_session.commit()

        by_key = {orphan_a.storage_key: orphan_a, orphan_b.storage_key: orphan_b}
        calls: list[str] = []
        processed_first: dict[str, str] = {}

        async def _fake_delete_object(client: object, *, bucket: str, key: str) -> None:
            calls.append(key)
            if not processed_first:
                processed_first["key"] = key
                other = orphan_b if key == orphan_a.storage_key else orphan_a
                # Simulate a concurrent bind landing on the *other* (not yet
                # processed) row while this row's purge is in flight.
                await db_session.execute(
                    update(Attachment)
                    .where(Attachment.id == other.id)
                    .values(message_id=message.id)
                )

        monkeypatch.setattr("app.services.media_sweep.delete_object", _fake_delete_object)

        result = await sweep_orphaned_media(
            db_session, object(), ttl=timedelta(hours=24), batch_size=500
        )

        assert result.scanned == 2
        assert result.purged == 1
        assert result.purge_failures == 0
        # Only the first-processed row's bytes were ever touched -- the
        # bound row's bytes were never purged.
        assert len(calls) == 1

        purged_attachment = by_key[processed_first["key"]]
        bound_attachment = orphan_b if purged_attachment is orphan_a else orphan_a

        assert await db_session.get(Attachment, purged_attachment.id) is None

        remaining = await db_session.get(Attachment, bound_attachment.id)
        assert remaining is not None
        assert remaining.message_id == message.id

    async def test_no_orphans_is_a_clean_no_op(
        self, migrated_db: None, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fake_delete_object(monkeypatch)

        result = await sweep_orphaned_media(db_session, object(), ttl=timedelta(hours=24))

        assert result.scanned == 0
        assert result.purged == 0
        assert result.purge_failures == 0
