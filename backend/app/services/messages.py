"""Channel message send/edit/delete/history business logic (T21, F38-F45).

Persist-only: this module never publishes a WS event or Redis pub/sub
message (`message.created`/`edited`/`deleted`) — that fan-out is T24's
scope. Every function here does exactly the durable-state half of the
frozen contract's four endpoints and returns plain ORM rows for
`app.api.messages` to serialize.

## Idempotency mechanism (F40) — Redis-backed key -> message-id map

The frozen database design has **no idempotency table/column** ("this is
an app/service-layer concern... not modeled in Postgres in this design")
and explicitly suggests, as one acceptable option, "a Redis-backed
key->message_id map, matching the CLAUDE.md pattern of using Redis for
such state." That is exactly what this module implements — no schema
change, no new table, nothing added to the frozen `messages` design.

Key shape: `idem:message_send:{sender_id}:{idempotency_key}` -> the
`str(message_id)` that key ultimately produced, `SET ... NX` with a
generous TTL (`IDEMPOTENCY_TTL_SECONDS`, 24h) so a replay well after the
original send still returns the same row. Flow:

1. `_load_existing_claim` — GET the key. If present, the request is a
   replay: load that message (plus its bound media) and return it,
   `created=False`, with **no** re-validation of membership/content/
   media — the frozen contract keys idempotency on `(sender_id, key)`
   only, not `(channel_id, key)`, so a replay must short-circuit before
   any other business check runs.
2. If absent, the caller runs the full validation pipeline (channel
   exists, membership, content, media ownership/unbound) and generates
   the message id, then attempts `_claim_idempotency_key` (`SET NX`) with
   that id as the value.
3. If the claim call itself loses a race (another concurrent request with
   the same key claimed it first), the loser **never** falls through to a
   blind insert while the winner's claim is still held — that fallthrough
   was a real bug (the winner's row is not yet visible to the loser's
   session under READ COMMITTED until the winner commits, so a naive
   "re-read once, insert if still not found" produced a second row). The
   fix is a **bounded resolve loop** (`_resolve_existing_claim`) that is
   also careful never to hold a pooled DB connection across a sleep (a
   HIGH-severity DoS regression a prior version of this loop had — see
   that function's docstring):
   - Check once, immediately, whether the claim already points at a
     visible row; if so, return that row as the replay (`created=False`)
     — this is what makes "exactly one row" hold even under a concurrent
     replay-race, not just sequential replay.
   - Otherwise release the connection (`db.rollback()`) and back off with
     Redis-only probes (no DB statement runs while sleeping): if the claim
     key *disappears* (the winner's own insert failed and it released the
     key, best-effort — see point 4), the loser loops back and attempts
     the claim itself instead of giving up.
   - If the key is still claimed once the backoff budget
     (`_RESOLVE_MAX_ATTEMPTS` attempts, `_RESOLVE_BACKOFF_SECONDS` apart —
     comfortably under any request timeout) is spent, it re-acquires a
     connection for exactly one final read; if that still finds nothing
     visible, this fails closed: it raises
     `IdempotencyResolutionTimeoutError` (mapped to a `503` with
     `Retry-After` by `app.api.messages`) rather than ever inserting a
     duplicate. The whole claim-or-resolve dance is itself bounded
     (`_CLAIM_MAX_ROUNDS`) so a pathological repeated claim/release
     ping-pong cannot loop forever either.
4. If persistence fails after a successful claim, the claim is deleted
   (best-effort) so a subsequent legitimate retry with the same key is not
   permanently blocked pointing at a row that was never created.

Caveat (flagged for the architect, not blocking T21 — and explicitly
accepted per the human architecture-gate decision to keep Redis rather
than add an idempotency column/table): Redis is not configured for
durability at this scale (CLAUDE.md: "no cluster," and presence/rate-limit
data there is explicitly ephemeral). If the Redis instance loses this key
*between* a successful claim and its TTL (restart without persistence,
eviction under memory pressure) — as opposed to the in-flight,
still-committing window the resolve loop above already handles — a replay
after that loss will insert a second row rather than returning the
original. This is a narrow, accepted durability gap inherent to keeping
idempotency state out of Postgres, consistent with this project's
at-least-once-delivery + client-side-dedup-by-message-id model (see
CLAUDE.md "Message delivery"). Not addressed further here since no schema
change is authorized without a fresh architect sign-off.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import generate_id
from app.core.pagination import CursorKey, Page, apply_keyset, paginate_rows
from app.models.attachment import Attachment
from app.models.channel import Channel
from app.models.message import Message
from app.services.channels import get_membership

# Generous replay window — long enough that a client retrying a genuinely
# slow/uncertain send (e.g. after a timeout on its side) still hits the
# same claim, short enough not to hold Redis memory for message-send keys
# indefinitely. Not part of the frozen contract (which does not specify a
# window) — a deliberate implementation choice, called out above for
# architect confirmation alongside the storage mechanism itself.
IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60

CONTENT_MAX_LENGTH = 4000

# Bounds on the loser-path resolve loop (`_resolve_existing_claim`): how many
# times to re-read the claim/re-check the row, and how long to sleep between
# attempts. 8 attempts * 50ms = 400ms worst case — long enough for a
# same-process concurrent winner's `flush()`+`commit()` to land, comfortably
# under any sane HTTP request timeout.
_RESOLVE_MAX_ATTEMPTS = 8
_RESOLVE_BACKOFF_SECONDS = 0.05

# Bounds the outer claim<->resolve ping-pong (steps 1<->3 in the module
# docstring): in the ordinary case a lost claim resolves on the very first
# `_resolve_existing_claim` call, so this only guards the pathological case
# where the key disappears (a concurrent winner's insert failed and released
# it) more than once in a row.
_CLAIM_MAX_ROUNDS = 3


class ChannelNotFoundError(Exception):
    """No such channel — maps to the frozen uniform `404`."""


class NotChannelMemberError(Exception):
    """Caller is authenticated but not a member of the channel — `403` (F34)."""


class InvalidContentError(Exception):
    """`content` is null/whitespace-only or exceeds 4000 chars — `422`."""


class InvalidMediaError(Exception):
    """A supplied `media_id` is unknown, not owned by the sender, or already
    bound to another message — `422` (F39). Deliberately a single,
    non-enumerating error class: the contract does not distinguish these
    three sub-cases on the wire.
    """


class MessageNotFoundError(Exception):
    """No such message — `404` (uniform)."""


class NotMessageAuthorError(Exception):
    """Caller is not the message's `sender_id` — `403`, no admin override (F42/F43)."""


class MessageAlreadyDeletedError(Exception):
    """Edit rejected because the message is already soft-deleted — `409` (F39)."""


class IdempotencyResolutionTimeoutError(Exception):
    """The bounded resolve loop could not settle a concurrent idempotency claim.

    Raised when another in-flight request holds the `(sender_id,
    idempotency_key)` claim but its message row never became visible to
    this session within `_RESOLVE_MAX_ATTEMPTS`/`_CLAIM_MAX_ROUNDS` — the
    fail-closed outcome so `send_channel_message` never inserts a
    duplicate row (F40). Maps to a `503` ("please retry the same
    Idempotency-Key") in `app.api.messages`, not a `4xx` — this is a
    transient timing condition, not a client error.
    """


def is_valid_content(content: str) -> bool:
    """Intentionally *stricter* mirror of the shipped `ck_messages_content` CHECK.

    The DB constraint is `char_length(content) <= 4000 AND btrim(content)
    <> ''`. Postgres's no-argument `btrim()` only strips ASCII space
    (`chr(32)`) from both ends, whereas Python's `str.strip()` strips every
    Unicode whitespace character (tabs, NBSP, zero-width space, etc.). So a
    content value that is *only* non-ASCII whitespace would pass the DB
    CHECK but fails this app-side check — that is by design (defense in
    depth, not a bug): it is never weaker than the DB constraint, only
    sometimes stricter, and every value this function accepts also passes
    the DB CHECK. Validated *before* persist either way, so a rejection
    here maps to the frozen `422`, never a raw `IntegrityError`.
    """

    return len(content) <= CONTENT_MAX_LENGTH and content.strip() != ""


def _idempotency_redis_key(sender_id: UUID, idempotency_key: str) -> str:
    return f"idem:message_send:{sender_id}:{idempotency_key}"


async def _load_claimed_message_id(
    redis: Redis, *, sender_id: UUID, idempotency_key: str
) -> UUID | None:
    raw = await redis.get(_idempotency_redis_key(sender_id, idempotency_key))
    if raw is None:
        return None
    # `decode_responses=True` (see `app.db.redis.build_client_kwargs`)
    # guarantees `str` at runtime; the client's stubs type this as
    # `bytes | str` since the option is only known at construction time.
    assert isinstance(raw, str)
    return UUID(raw)


async def _claim_idempotency_key(
    redis: Redis, *, sender_id: UUID, idempotency_key: str, message_id: UUID
) -> bool:
    """Attempt to atomically claim `(sender_id, idempotency_key)` -> `message_id`.

    Returns `True` if this call won the claim, `False` if another request
    already holds it (caller must then re-read and treat this as a
    replay).
    """

    claimed = await redis.set(
        _idempotency_redis_key(sender_id, idempotency_key),
        str(message_id),
        nx=True,
        ex=IDEMPOTENCY_TTL_SECONDS,
    )
    return bool(claimed)


async def _release_idempotency_key(redis: Redis, *, sender_id: UUID, idempotency_key: str) -> None:
    await redis.delete(_idempotency_redis_key(sender_id, idempotency_key))


async def _load_message_with_media(
    db: AsyncSession, message_id: UUID
) -> tuple[Message, list[Attachment]] | None:
    message = await db.get(Message, message_id)
    if message is None:
        return None
    media = await get_message_media(db, message_id)
    return message, media


async def get_message_media(db: AsyncSession, message_id: UUID) -> list[Attachment]:
    """Every attachment bound to `message_id`, ordered stably for the `media[]` array."""

    result = await db.execute(
        select(Attachment)
        .where(Attachment.message_id == message_id)
        .order_by(Attachment.created_at, Attachment.id)
    )
    return list(result.scalars().all())


async def get_media_for_messages(
    db: AsyncSession, message_ids: list[UUID]
) -> dict[UUID, list[Attachment]]:
    """Batch-fetch bound attachments for a page of messages (avoids N+1 on history)."""

    if not message_ids:
        return {}
    result = await db.execute(
        select(Attachment)
        .where(Attachment.message_id.in_(message_ids))
        .order_by(Attachment.created_at, Attachment.id)
    )
    grouped: dict[UUID, list[Attachment]] = {mid: [] for mid in message_ids}
    for attachment in result.scalars().all():
        assert attachment.message_id is not None
        grouped[attachment.message_id].append(attachment)
    return grouped


async def _validate_and_load_media(
    db: AsyncSession, *, media_ids: list[UUID], sender_id: UUID
) -> list[Attachment]:
    if not media_ids:
        return []

    result = await db.execute(select(Attachment).where(Attachment.id.in_(media_ids)))
    found = {attachment.id: attachment for attachment in result.scalars().all()}

    attachments: list[Attachment] = []
    for media_id in media_ids:
        attachment = found.get(media_id)
        if (
            attachment is None
            or attachment.uploader_id != sender_id
            or attachment.message_id is not None
        ):
            # Non-enumerating: unknown id, not-owned, and already-bound all
            # collapse to the same 422 class (F39) — never disclose which.
            raise InvalidMediaError(f"media_id {media_id} is not usable by this sender.")
        attachments.append(attachment)

    return attachments


async def _bind_media_atomically(
    db: AsyncSession, *, message_id: UUID, media_ids: list[UUID], sender_id: UUID
) -> list[Attachment]:
    """Atomically bind `media_ids` to `message_id`, closing the F39 media TOCTOU race.

    A single conditional `UPDATE attachments SET message_id = :message_id
    WHERE id = ANY(:media_ids) AND uploader_id = :sender_id AND message_id
    IS NULL`. The `message_id IS NULL` predicate takes a row lock on every
    matched attachment, so two concurrent sends racing to bind the *same*
    unbound attachment serialize on that row: whichever `UPDATE` commits
    first wins it, and the loser's `UPDATE` simply matches zero rows for
    that id (the predicate is no longer true once the winner's row lock
    releases). This replaces the previous read-check-then-assign pattern
    (`SELECT ... WHERE message_id IS NULL` then `attachment.message_id =
    message.id` in Python), which raced: two concurrent requests could
    both read "unbound" before either wrote, both assign, and both commit
    — leaving two messages pointing at the same attachment.

    Asserts every requested id was actually claimed by *this* call
    (`rowcount == len(media_ids)`); if fewer matched — unknown id, not
    owned by `sender_id`, or already bound (including by a concurrent
    winner that landed first) — raises the same non-enumerating
    `InvalidMediaError` the up-front check uses. The caller's own
    exception handler rolls back the whole transaction, so a partial bind
    is never committed.
    """

    if not media_ids:
        return []

    result = cast(
        CursorResult[Any],
        await db.execute(
            update(Attachment)
            .where(
                Attachment.id.in_(media_ids),
                Attachment.uploader_id == sender_id,
                Attachment.message_id.is_(None),
            )
            .values(message_id=message_id)
        ),
    )
    if result.rowcount != len(media_ids):
        # Non-enumerating (F39): never disclose which id failed to bind.
        raise InvalidMediaError(
            "One or more media_ids were not bound by this send (unknown, not "
            "owned by the sender, or already bound)."
        )

    # Re-read rather than trust the in-memory `Attachment` objects validated
    # earlier — this reflects exactly what *this* message actually bound,
    # not a possibly-stale pre-update snapshot.
    return await get_message_media(db, message_id)


async def _resolve_existing_claim(
    db: AsyncSession, redis: Redis, *, sender_id: UUID, idempotency_key: str
) -> tuple[Message, list[Attachment]] | None:
    """Resolve an idempotency claim that may already exist, bounded and fail-closed.

    Returns the claimed `(message, media)` once the claim's row becomes
    visible to `db`. Returns `None` if the key is (or becomes, mid-loop)
    absent — either nothing has claimed it yet, or a concurrent winner's
    insert failed and it released the key (see `send_channel_message`'s
    `except` clause) — telling the caller it is safe to attempt the claim
    itself.

    Raises `IdempotencyResolutionTimeoutError` if the key stays claimed for
    the full `_RESOLVE_MAX_ATTEMPTS` retry window without its row ever
    becoming visible. This is the fail-closed replacement for the old
    "re-read once, insert if still not found" fallthrough that produced a
    duplicate row under concurrent replay (the F40 bug this function
    fixes): a caller of this function must never fall through to a blind
    insert while `IdempotencyResolutionTimeoutError` propagates.

    Connection-lifecycle note (security fix — HIGH-severity DoS
    regression): this function must never hold a pooled DB connection
    across `asyncio.sleep`. The app pool is only `db_pool_size` (10) +
    `db_max_overflow` (5) = 15 connections process-wide, and there is no
    per-user rate limiting yet (T27), so a caller firing ~16+ concurrent
    POSTs with the *same* `Idempotency-Key` would previously have each
    loser hold a checked-out connection through the entire bounded backoff
    window, exhausting the pool for the whole instance. So the one-time
    "is it already visible" check below releases the session's connection
    (`db.rollback()` — there is nothing to lose; this path has not written
    anything) *before* the backoff loop starts, and everything inside that
    loop talks to Redis only. Only the very last attempt re-acquires a
    connection, for exactly one final `db.get()`, before failing closed.
    """

    claimed_id = await _load_claimed_message_id(
        redis, sender_id=sender_id, idempotency_key=idempotency_key
    )
    if claimed_id is None:
        return None

    # Fast path: the winner may have already committed by the time we get
    # here (common case for a sequential replay, not a concurrent race) —
    # worth one immediate check before paying for any backoff at all.
    loaded = await _load_message_with_media(db, claimed_id)
    if loaded is not None:
        return loaded

    # Not yet visible under READ COMMITTED. Release this session's pooled
    # connection *before* backing off — see the connection-lifecycle note
    # above. No DB statement runs anywhere below while this loop sleeps.
    await db.rollback()

    for attempt in range(1, _RESOLVE_MAX_ATTEMPTS):
        await asyncio.sleep(_RESOLVE_BACKOFF_SECONDS)

        # Redis-only probe — no pooled connection is held here.
        claimed_id = await _load_claimed_message_id(
            redis, sender_id=sender_id, idempotency_key=idempotency_key
        )
        if claimed_id is None:
            # The claim vanished — a concurrent winner's own insert failed
            # and it released the key (see `send_channel_message`'s
            # `except` clause). Safe for the caller to attempt the claim.
            return None

        if attempt < _RESOLVE_MAX_ATTEMPTS - 1:
            continue

        # Final attempt: re-acquire a connection for exactly one last read
        # before failing closed.
        loaded = await _load_message_with_media(db, claimed_id)
        if loaded is not None:
            return loaded

    raise IdempotencyResolutionTimeoutError(
        f"idempotency claim for sender {sender_id} did not resolve to a "
        f"visible row within {_RESOLVE_MAX_ATTEMPTS} attempts."
    )


async def ensure_channel_and_membership(
    db: AsyncSession, *, channel_id: UUID, user_id: UUID
) -> None:
    """Shared `404`/`403` gate for both send (`POST`) and history (`GET`), F34.

    Checked in this order — existence before authorization — to match the
    frozen contract's status table exactly: a genuinely missing channel is
    `404` regardless of membership, while an existing channel the caller
    is not a member of is `403`.
    """

    channel = await db.get(Channel, channel_id)
    if channel is None:
        raise ChannelNotFoundError(f"No channel {channel_id}.")

    membership = await get_membership(db, channel_id=channel_id, user_id=user_id)
    if membership is None:
        raise NotChannelMemberError(f"{user_id} is not a member of {channel_id}.")


@dataclass(frozen=True, slots=True)
class SendMessageResult:
    """Outcome of `send_channel_message` — `created=False` means idempotent replay."""

    message: Message
    media: list[Attachment]
    created: bool


async def send_channel_message(
    db: AsyncSession,
    redis: Redis,
    *,
    channel_id: UUID,
    sender_id: UUID,
    content: str,
    media_ids: list[UUID],
    idempotency_key: str,
) -> SendMessageResult:
    """Persist a new channel message, or return the original of a replay (F38-F41).

    Raises `ChannelNotFoundError` / `NotChannelMemberError` /
    `InvalidContentError` / `InvalidMediaError` for the route layer to map
    to the frozen `404`/`403`/`422`, or `IdempotencyResolutionTimeoutError`
    (fail-closed, `503`) if a concurrent claim never resolves within the
    bounded retry window — see the module docstring and
    `_resolve_existing_claim`. Never publishes a WS/Redis fan-out event
    (T24's scope) — persist only.
    """

    resolved = await _resolve_existing_claim(
        db, redis, sender_id=sender_id, idempotency_key=idempotency_key
    )
    if resolved is not None:
        message, media = resolved
        return SendMessageResult(message=message, media=media, created=False)

    await ensure_channel_and_membership(db, channel_id=channel_id, user_id=sender_id)

    if not is_valid_content(content):
        raise InvalidContentError("content must be 1-4000 non-whitespace characters.")

    # Friendly, early 422 — not the load-bearing guarantee against a
    # concurrent double-bind. That guarantee is the atomic `UPDATE` in
    # `_bind_media_atomically` below, run inside the send transaction.
    await _validate_and_load_media(db, media_ids=media_ids, sender_id=sender_id)

    message_id = generate_id()

    for _round in range(_CLAIM_MAX_ROUNDS):
        claimed = await _claim_idempotency_key(
            redis, sender_id=sender_id, idempotency_key=idempotency_key, message_id=message_id
        )
        if claimed:
            try:
                message = Message(
                    id=message_id,
                    channel_id=channel_id,
                    recipient_id=None,
                    sender_id=sender_id,
                    content=content,
                )
                db.add(message)
                await db.flush()

                bound_media = await _bind_media_atomically(
                    db, message_id=message.id, media_ids=media_ids, sender_id=sender_id
                )

                await db.commit()
            except Exception:
                await db.rollback()
                await _release_idempotency_key(
                    redis, sender_id=sender_id, idempotency_key=idempotency_key
                )
                raise

            return SendMessageResult(message=message, media=bound_media, created=True)

        # Lost the claim race to a concurrent identical request. Resolve
        # the winner's row (bounded retries inside `_resolve_existing_claim`)
        # rather than ever falling through to a blind insert — this is the
        # F40 fix. `None` here means the key disappeared between the failed
        # claim above and now (the winner's own insert failed and it
        # released the key) — loop back and attempt the claim ourselves.
        resolved = await _resolve_existing_claim(
            db, redis, sender_id=sender_id, idempotency_key=idempotency_key
        )
        if resolved is not None:
            message, media = resolved
            return SendMessageResult(message=message, media=media, created=False)

    raise IdempotencyResolutionTimeoutError(
        f"could not claim or resolve the idempotency key for sender "
        f"{sender_id} within {_CLAIM_MAX_ROUNDS} claim/resolve rounds."
    )


async def get_channel_message_history(
    db: AsyncSession,
    *,
    channel_id: UUID,
    caller_id: UUID,
    limit: int,
    cursor: CursorKey | None,
) -> Page[Message]:
    """Cursor-paginated, soft-delete-excluding channel history (F44/F55).

    Caller must already have resolved `limit`/`cursor` (via
    `app.core.pagination.resolve_limit`/`decode_cursor`) and confirmed
    channel existence + membership (`ChannelNotFoundError`/
    `NotChannelMemberError`, F34) before calling this. Queries via the
    exact keyset shape the frozen `ix_messages_channel_history` partial
    index requires: `WHERE channel_id = ? AND deleted_at IS NULL AND
    (created_at, id) < (?, ?) ORDER BY created_at DESC, id DESC LIMIT
    limit + 1`.
    """

    stmt = select(Message).where(
        Message.channel_id == channel_id,
        Message.deleted_at.is_(None),
    )
    stmt = apply_keyset(
        stmt,
        created_at_col=Message.__table__.c.created_at,
        id_col=Message.__table__.c.id,
        cursor=cursor,
    )
    stmt = stmt.limit(limit + 1)

    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    return paginate_rows(
        rows, limit=limit, cursor_key=lambda m: CursorKey(created_at=m.created_at, id=m.id)
    )


async def _ensure_caller_can_see_message(
    db: AsyncSession, message: Message, *, caller_id: UUID
) -> None:
    """Uniform-404 visibility gate (F34): a non-member cannot even learn a message exists.

    Per the frozen contract's PATCH/DELETE `404` clause ("No such message
    (or caller cannot see its conversation)"), a caller who is not a
    member of the message's channel gets the exact same `404` as a
    genuinely missing message — never a `403`, which would leak that the
    message exists. Only reachable for channel messages (`channel_id` set)
    in T21's scope; DM visibility (`recipient_id`) is T22's concern.
    """

    if message.channel_id is None:
        return
    membership = await get_membership(db, channel_id=message.channel_id, user_id=caller_id)
    if membership is None:
        raise MessageNotFoundError(f"No message {message.id} visible to {caller_id}.")


async def edit_message(
    db: AsyncSession, *, message_id: UUID, caller_id: UUID, content: str
) -> Message:
    """Author-only edit; sets `edited_at` unless the content is unchanged (F42).

    Raises `MessageNotFoundError` / `NotMessageAuthorError` /
    `MessageAlreadyDeletedError` / `InvalidContentError` for the route
    layer to map to `404`/`403`/`409`/`422`. Never publishes the
    `message.edited` WS event (T24's scope).
    """

    message = await db.get(Message, message_id)
    if message is None:
        raise MessageNotFoundError(f"No message {message_id}.")

    await _ensure_caller_can_see_message(db, message, caller_id=caller_id)

    if message.sender_id != caller_id:
        raise NotMessageAuthorError(f"{caller_id} did not author {message_id}.")

    if message.deleted_at is not None:
        raise MessageAlreadyDeletedError(f"Message {message_id} is already deleted.")

    if not is_valid_content(content):
        raise InvalidContentError("content must be 1-4000 non-whitespace characters.")

    if content != message.content:
        message.content = content
        message.edited_at = datetime.now(UTC)
        await db.flush()

    await db.commit()
    return message


async def delete_message(db: AsyncSession, *, message_id: UUID, caller_id: UUID) -> Message:
    """Author-only soft delete; idempotent (repeat delete is a no-op `204`, F43).

    Raises `MessageNotFoundError` / `NotMessageAuthorError` for the route
    layer to map to `404`/`403`. Never publishes the `message.deleted` WS
    event (T24's scope). Row is retained either way — never removed.
    """

    message = await db.get(Message, message_id)
    if message is None:
        raise MessageNotFoundError(f"No message {message_id}.")

    await _ensure_caller_can_see_message(db, message, caller_id=caller_id)

    if message.sender_id != caller_id:
        raise NotMessageAuthorError(f"{caller_id} did not author {message_id}.")

    if message.deleted_at is None:
        message.deleted_at = datetime.now(UTC)
        await db.flush()

    await db.commit()
    return message
