"""Integration tests for `/v1/dms/{user_id}/messages` (T22, frozen contract).

Exercises the real routes end-to-end against Postgres + Redis (skipped
when unreachable): idempotent DM create-or-replay reusing T21's shared
send/idempotency helper (F40), self-DM `422` (not `404`), missing/inactive
recipient `404`, content/media validation `422` (F39), and
cursor-paginated DM history keyed on the canonical
`least(sender_id, recipient_id)`/`greatest(...)` user pair (F48),
including its own self-conversation `422` / missing-participant `404`
gates and its participant-only visibility.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.core.metrics import reset_metrics
from app.core.metrics import snapshot as metrics_snapshot
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import generate_id
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.models.attachment import Attachment, AttachmentKind
from app.models.message import Message
from app.models.session import Session
from app.models.user import User
from tests.conftest import REQUIRED_ENV

pytestmark = pytest.mark.usefixtures("configured_env")


def _test_login_secret() -> str:
    """Not a real secret — see `test_channels_api.py`'s identical helper."""

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


async def _make_attachment(db: AsyncSession, *, uploader: User) -> Attachment:
    attachment = Attachment(
        id=generate_id(),
        message_id=None,
        uploader_id=uploader.id,
        kind=AttachmentKind.IMAGE,
        content_type="image/png",
        storage_key=f"key-{generate_id()}",
        filename="screenshot.png",
        byte_size=1024,
    )
    db.add(attachment)
    await db.flush()
    return attachment


def _idem_key() -> str:
    return str(uuid.uuid4())


class TestSendDmMessage:
    async def test_sends_dm_and_returns_201(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        sender, token = await _authed_user(db_session)
        recipient, _ = await _authed_user(db_session)

        reset_metrics()
        response = client.post(
            f"/v1/dms/{recipient.id}/messages",
            headers={**_auth_header(token), "Idempotency-Key": _idem_key()},
            json={"content": "hey, got a minute?"},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["channel_id"] is None
        assert body["recipient_id"] == str(recipient.id)
        assert body["sender_id"] == str(sender.id)
        assert body["content"] == "hey, got a minute?"
        assert body["media"] == []
        assert body["edited_at"] is None
        assert body["deleted_at"] is None
        uuid.UUID(body["id"])

        # Key metric (technical spec §9): "message send throughput" — a
        # first-time (non-replay) DM send increments
        # `message_send_success_total{conversation_kind=dm,replay=false}`
        # (T39; code review finding 1/2).
        counters = metrics_snapshot()["counters"]["message_send_success_total"]
        assert counters["conversation_kind=dm,replay=false"] == 1

    async def test_missing_idempotency_key_is_400(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, token = await _authed_user(db_session)
        recipient, _ = await _authed_user(db_session)

        response = client.post(
            f"/v1/dms/{recipient.id}/messages",
            headers=_auth_header(token),
            json={"content": "hello"},
        )

        assert response.status_code == 400
        assert response.headers["content-type"] == "application/problem+json"

    async def test_malformed_idempotency_key_is_400(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, token = await _authed_user(db_session)
        recipient, _ = await _authed_user(db_session)

        response = client.post(
            f"/v1/dms/{recipient.id}/messages",
            headers={**_auth_header(token), "Idempotency-Key": "not-a-uuid"},
            json={"content": "hello"},
        )

        assert response.status_code == 400

    async def test_replay_of_same_key_returns_original_row_exactly_once(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        sender, token = await _authed_user(db_session)
        recipient, _ = await _authed_user(db_session)

        key = _idem_key()
        first = client.post(
            f"/v1/dms/{recipient.id}/messages",
            headers={**_auth_header(token), "Idempotency-Key": key},
            json={"content": "hello world"},
        )
        second = client.post(
            f"/v1/dms/{recipient.id}/messages",
            headers={**_auth_header(token), "Idempotency-Key": key},
            json={"content": "hello world"},
        )

        assert first.status_code == 201
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]

        from sqlalchemy import func, select

        count = await db_session.scalar(
            select(func.count()).select_from(Message).where(Message.sender_id == sender.id)
        )
        assert count == 1

    async def test_self_dm_is_422_not_404(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        sender, token = await _authed_user(db_session)

        reset_metrics()
        response = client.post(
            f"/v1/dms/{sender.id}/messages",
            headers={**_auth_header(token), "Idempotency-Key": _idem_key()},
            json={"content": "hello myself"},
        )

        assert response.status_code == 422
        assert response.headers["content-type"] == "application/problem+json"

        # Key metric (technical spec §9): "message send error rate" — the
        # self-DM business-rule rejection increments
        # `message_send_error_total{conversation_kind=dm,error_type=self_dm}`
        # (T39; code review finding 1).
        counters = metrics_snapshot()["counters"]["message_send_error_total"]
        assert counters["conversation_kind=dm,error_type=self_dm"] == 1

    async def test_nonexistent_recipient_is_404(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, token = await _authed_user(db_session)

        response = client.post(
            f"/v1/dms/{generate_id()}/messages",
            headers={**_auth_header(token), "Idempotency-Key": _idem_key()},
            json={"content": "hello"},
        )

        assert response.status_code == 404
        assert response.headers["content-type"] == "application/problem+json"

    async def test_inactive_recipient_is_404(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, token = await _authed_user(db_session)
        recipient = await _make_user(db_session, is_active=False)
        await db_session.commit()

        response = client.post(
            f"/v1/dms/{recipient.id}/messages",
            headers={**_auth_header(token), "Idempotency-Key": _idem_key()},
            json={"content": "hello"},
        )

        assert response.status_code == 404

    @pytest.mark.parametrize("content", ["", "   ", "x" * 4001])
    async def test_invalid_content_is_422(
        self,
        migrated_db: None,
        client: TestClient,
        db_session: AsyncSession,
        content: str,
    ) -> None:
        _, token = await _authed_user(db_session)
        recipient, _ = await _authed_user(db_session)

        response = client.post(
            f"/v1/dms/{recipient.id}/messages",
            headers={**_auth_header(token), "Idempotency-Key": _idem_key()},
            json={"content": content},
        )

        assert response.status_code == 422
        assert response.headers["content-type"] == "application/problem+json"

    async def test_unknown_media_id_is_422(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, token = await _authed_user(db_session)
        recipient, _ = await _authed_user(db_session)

        response = client.post(
            f"/v1/dms/{recipient.id}/messages",
            headers={**_auth_header(token), "Idempotency-Key": _idem_key()},
            json={"content": "hello", "media_ids": [str(generate_id())]},
        )

        assert response.status_code == 422

    async def test_sends_with_valid_unbound_media(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        sender, token = await _authed_user(db_session)
        recipient, _ = await _authed_user(db_session)
        attachment = await _make_attachment(db_session, uploader=sender)
        await db_session.commit()

        response = client.post(
            f"/v1/dms/{recipient.id}/messages",
            headers={**_auth_header(token), "Idempotency-Key": _idem_key()},
            json={"content": "hello", "media_ids": [str(attachment.id)]},
        )

        assert response.status_code == 201
        body = response.json()
        assert len(body["media"]) == 1
        assert body["media"][0]["media_id"] == str(attachment.id)

        await db_session.refresh(attachment)
        assert attachment.message_id == uuid.UUID(body["id"])

    async def test_missing_auth_is_401(self, migrated_db: None, client: TestClient) -> None:
        response = client.post(
            f"/v1/dms/{generate_id()}/messages",
            headers={"Idempotency-Key": _idem_key()},
            json={"content": "hello"},
        )

        assert response.status_code == 401


class TestDmMessageHistory:
    async def test_returns_messages_for_canonical_pair_excluding_soft_deleted(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        alice, alice_token = await _authed_user(db_session)
        bob, _ = await _authed_user(db_session)

        # A -> B, B -> A, and one soft-deleted — all one conversation
        # regardless of sender/recipient direction (ADR-0002 canonical pair).
        forward = Message(
            id=generate_id(), sender_id=alice.id, recipient_id=bob.id, content="hi bob"
        )
        backward = Message(
            id=generate_id(), sender_id=bob.id, recipient_id=alice.id, content="hi alice"
        )
        deleted = Message(
            id=generate_id(),
            sender_id=alice.id,
            recipient_id=bob.id,
            content="oops",
            deleted_at=datetime.now(UTC),
        )
        db_session.add_all([forward, backward, deleted])
        await db_session.commit()

        response = client.get(f"/v1/dms/{bob.id}/messages", headers=_auth_header(alice_token))

        assert response.status_code == 200
        body = response.json()
        ids = [item["id"] for item in body["items"]]
        assert str(forward.id) in ids
        assert str(backward.id) in ids
        assert str(deleted.id) not in ids

    async def test_history_visible_from_either_participant(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        alice, alice_token = await _authed_user(db_session)
        bob, bob_token = await _authed_user(db_session)

        message = Message(
            id=generate_id(), sender_id=alice.id, recipient_id=bob.id, content="hi bob"
        )
        db_session.add(message)
        await db_session.commit()

        response_from_alice = client.get(
            f"/v1/dms/{bob.id}/messages", headers=_auth_header(alice_token)
        )
        response_from_bob = client.get(
            f"/v1/dms/{alice.id}/messages", headers=_auth_header(bob_token)
        )

        assert response_from_alice.status_code == 200
        assert response_from_bob.status_code == 200
        assert [item["id"] for item in response_from_alice.json()["items"]] == [str(message.id)]
        assert [item["id"] for item in response_from_bob.json()["items"]] == [str(message.id)]

    async def test_does_not_leak_other_conversations(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        alice, alice_token = await _authed_user(db_session)
        bob, _ = await _authed_user(db_session)
        carol, _ = await _authed_user(db_session)

        alice_bob = Message(
            id=generate_id(), sender_id=alice.id, recipient_id=bob.id, content="hi bob"
        )
        alice_carol = Message(
            id=generate_id(), sender_id=alice.id, recipient_id=carol.id, content="hi carol"
        )
        db_session.add_all([alice_bob, alice_carol])
        await db_session.commit()

        response = client.get(f"/v1/dms/{bob.id}/messages", headers=_auth_header(alice_token))

        assert response.status_code == 200
        ids = [item["id"] for item in response.json()["items"]]
        assert ids == [str(alice_bob.id)]

    async def test_cursor_pagination_walks_full_history(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        alice, alice_token = await _authed_user(db_session)
        bob, _ = await _authed_user(db_session)

        created_ids: list[str] = []
        base = datetime.now(UTC)
        for i in range(5):
            message = Message(
                id=generate_id(),
                sender_id=alice.id if i % 2 == 0 else bob.id,
                recipient_id=bob.id if i % 2 == 0 else alice.id,
                content=f"message {i}",
                created_at=base + timedelta(seconds=i),
            )
            db_session.add(message)
            await db_session.flush()
            created_ids.append(str(message.id))
        await db_session.commit()

        collected: list[str] = []
        cursor: str | None = None
        for _ in range(10):
            params = {"limit": "2"}
            if cursor is not None:
                params["cursor"] = cursor
            response = client.get(
                f"/v1/dms/{bob.id}/messages",
                headers=_auth_header(alice_token),
                params=params,
            )
            assert response.status_code == 200
            body = response.json()
            collected.extend(item["id"] for item in body["items"])
            cursor = body["next_cursor"]
            if cursor is None:
                break

        assert set(collected) == set(created_ids)
        assert len(collected) == len(created_ids)

    async def test_self_conversation_is_422(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        alice, alice_token = await _authed_user(db_session)

        response = client.get(f"/v1/dms/{alice.id}/messages", headers=_auth_header(alice_token))

        assert response.status_code == 422
        assert response.headers["content-type"] == "application/problem+json"

    async def test_missing_other_participant_is_404(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, token = await _authed_user(db_session)

        response = client.get(f"/v1/dms/{generate_id()}/messages", headers=_auth_header(token))

        assert response.status_code == 404

    async def test_inactive_other_participant_history_still_readable(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        """History `404` is existence-only (uniform); no `is_active` check per contract."""

        alice, alice_token = await _authed_user(db_session)
        bob = await _make_user(db_session, is_active=False)
        message = Message(
            id=generate_id(), sender_id=alice.id, recipient_id=bob.id, content="hi bob"
        )
        db_session.add(message)
        await db_session.commit()

        response = client.get(f"/v1/dms/{bob.id}/messages", headers=_auth_header(alice_token))

        assert response.status_code == 200
        assert [item["id"] for item in response.json()["items"]] == [str(message.id)]

    async def test_invalid_cursor_is_400(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, token = await _authed_user(db_session)
        recipient, _ = await _authed_user(db_session)

        response = client.get(
            f"/v1/dms/{recipient.id}/messages",
            headers=_auth_header(token),
            params={"cursor": "not-valid-base64!!"},
        )

        assert response.status_code == 400

    async def test_invalid_limit_is_400(
        self, migrated_db: None, client: TestClient, db_session: AsyncSession
    ) -> None:
        _, token = await _authed_user(db_session)
        recipient, _ = await _authed_user(db_session)

        response = client.get(
            f"/v1/dms/{recipient.id}/messages",
            headers=_auth_header(token),
            params={"limit": "0"},
        )

        assert response.status_code == 400

    async def test_missing_auth_is_401(self, migrated_db: None, client: TestClient) -> None:
        response = client.get(f"/v1/dms/{generate_id()}/messages")

        assert response.status_code == 401
