"""Cursor (keyset) pagination utility — ADR-0003, API contract Pagination clause.

This is the single reusable helper for cursor-based pagination over
`(created_at, id)`, the ordering shared by message history and DM history
(T21/T22, out of scope here) and by message identity itself (ADR-0005).

Scope (T07): the opaque cursor encode/decode, the `{items, next_cursor}`
envelope, and a keyset `WHERE`/`ORDER BY` builder consumers plug their own
`Select` into. Explicitly **out of scope**: offset pagination (T18, a
different style entirely — see `?page=` on `GET /v1/channels/public`) and
the concrete message/DM history queries themselves (T21/T22), which own
their own partition predicates (channel membership, DM pair) and reuse
only the primitives below.

Cursor encoding: opaque base64url over the 24-byte tuple
`(microseconds-since-epoch int64, UUID bytes)` — microsecond precision on
`created_at` and the full 128 bits of `id` round-trip losslessly, so
encode -> decode is stable per the contract. Clients MUST treat the
result as an opaque token and never construct one themselves; this module
is the only place that assembles or parses the byte layout.

End-of-stream semantics (contract, verbatim): "`items.length <= limit` is
expected ... a page can be shorter than `limit` without meaning
end-of-stream; end-of-stream is determined by the keyset query returning
nothing further, not by a short page." Concretely: soft-deleted rows are
excluded by the *query predicate* (F44, baked into the partial indexes),
never by post-filtering an already-limited result set here — so this
module never infers "no more rows" from `len(items) < limit`. Instead,
`next_cursor` is derived from an explicit `has_more` signal the caller
establishes (conventionally via the standard "fetch `limit + 1` rows,
trim to `limit`" keyset technique — see `split_keyset_page`). Keeping
`has_more` a first-class, explicit input (rather than inferring it from
page length) is what makes a short page and end-of-stream independently
representable, which is exactly the property the contract calls out and
the property the two most important unit tests below exist to pin down.
"""

from __future__ import annotations

import base64
import re
import struct
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Select, desc, tuple_

DEFAULT_LIMIT = 50
MAX_LIMIT = 100

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
# 8 bytes signed microseconds-since-epoch + 16 raw UUID bytes.
_CURSOR_PAYLOAD_LEN = 24
_MICROS_STRUCT = struct.Struct(">q")
# `encode_cursor` strips base64 padding, so a well-formed cursor is pure
# URL-safe base64 alphabet with no `=`. `base64.urlsafe_b64decode` silently
# drops any characters outside that alphabet instead of rejecting them, so
# this must be checked *before* decoding or a garbage-suffixed cursor would
# decode to a valid (but wrong) `CursorKey` instead of raising.
_BASE64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class PaginationError(ValueError):
    """A client-supplied `limit` or `cursor` fails validation.

    Callers (T21/T22 endpoints) catch this — or let it propagate to the
    `install_error_handlers`-registered handler in `app.core.errors` — to
    produce the frozen `400` problem+json response. `field` identifies
    which query parameter was invalid (`"limit"` or `"cursor"`) for the
    `errors` array; `detail` is safe to surface (never echoes the raw
    cursor bytes or any row data).
    """

    def __init__(self, *, field: str, detail: str) -> None:
        self.field = field
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True, slots=True)
class CursorKey:
    """The `(created_at, id)` keyset position a cursor encodes."""

    created_at: datetime
    id: UUID


@dataclass(frozen=True, slots=True)
class Page[T]:
    """The frozen `{ items, next_cursor }` response envelope."""

    items: list[T]
    next_cursor: str | None


def encode_cursor(key: CursorKey) -> str:
    """Encode a `(created_at, id)` position into an opaque base64url token.

    Losslessly serializes microsecond-precision UTC time plus the full
    128-bit id, so `decode_cursor(encode_cursor(k)) == k` for every valid
    `k` (round-trip stability is a contract requirement).
    """

    created_at_utc = key.created_at.astimezone(UTC)
    micros = (created_at_utc - _EPOCH) // timedelta(microseconds=1)
    payload = _MICROS_STRUCT.pack(micros) + key.id.bytes
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def decode_cursor(cursor: str) -> CursorKey:
    """Decode an opaque cursor token, raising `PaginationError` if malformed.

    Any structurally invalid input (bad base64, wrong payload length,
    corrupt bytes) is rejected here rather than propagating a raw
    `binascii`/`struct` exception — callers convert `PaginationError` into
    the frozen `400` problem+json shape.
    """

    if not cursor:
        raise PaginationError(field="cursor", detail="cursor must not be empty")

    # Reject anything outside the base64url alphabet *before* decoding:
    # `base64.urlsafe_b64decode` silently discards invalid characters
    # rather than raising, which would otherwise let a cursor with a
    # garbage suffix decode to a valid-looking (but wrong) position.
    if not _BASE64URL_RE.match(cursor):
        raise PaginationError(field="cursor", detail="cursor is not valid base64url")

    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        payload = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise PaginationError(field="cursor", detail="cursor is not valid base64url") from exc

    if len(payload) != _CURSOR_PAYLOAD_LEN:
        raise PaginationError(field="cursor", detail="cursor has an invalid length")

    try:
        (micros,) = _MICROS_STRUCT.unpack(payload[:8])
        cursor_id = UUID(bytes=payload[8:])
        created_at = _EPOCH + timedelta(microseconds=micros)
    except (ValueError, OverflowError) as exc:
        raise PaginationError(field="cursor", detail="cursor payload is corrupt") from exc

    return CursorKey(created_at=created_at, id=cursor_id)


def resolve_limit(raw_limit: int | None) -> int:
    """Validate and clamp a client-supplied `limit`.

    `None` -> `DEFAULT_LIMIT` (50). Values above `MAX_LIMIT` (100) are
    silently clamped down, per the contract ("a larger request is clamped
    to 100"). Non-positive values are a client error -> `PaginationError`
    (the contract's "invalid `limit`" -> `400` case; clamping only applies
    to the *upper* bound, not to nonsensical/negative input).
    """

    if raw_limit is None:
        return DEFAULT_LIMIT
    if raw_limit < 1:
        raise PaginationError(field="limit", detail="limit must be a positive integer")
    return min(raw_limit, MAX_LIMIT)


def keyset_predicate(
    created_at_col: ColumnElement[datetime],
    id_col: ColumnElement[UUID],
    cursor: CursorKey,
) -> ColumnElement[bool]:
    """Build the `(created_at, id) < (:cursor_created_at, :cursor_id)` predicate.

    Composite tuple comparison: `created_at` is the primary sort key, `id`
    is the tie-break, exactly matching the keyset indexes
    (`ix_messages_channel_history`, `ix_messages_dm_history`).
    """

    return tuple_(created_at_col, id_col) < (cursor.created_at, cursor.id)


def keyset_order_by(
    created_at_col: ColumnElement[datetime],
    id_col: ColumnElement[UUID],
) -> tuple[ColumnElement[Any], ColumnElement[Any]]:
    """Return the `ORDER BY created_at DESC, id DESC` clause pair (DESC keyset)."""

    return (desc(created_at_col), desc(id_col))


def apply_keyset(
    stmt: Select[Any],
    *,
    created_at_col: ColumnElement[datetime],
    id_col: ColumnElement[UUID],
    cursor: CursorKey | None,
) -> Select[Any]:
    """Apply the keyset `WHERE`/`ORDER BY` clauses to a caller-owned `Select`.

    The caller (T21/T22) supplies a `Select` already carrying its own
    partition predicate (channel membership / DM pair) and soft-delete
    exclusion (`deleted_at IS NULL`) — this function only adds the keyset
    continuation predicate (when `cursor` is given) and the DESC ordering
    that makes the tuple comparison correct. Callers apply `.limit(n + 1)`
    themselves (see `split_keyset_page`) before executing.
    """

    if cursor is not None:
        stmt = stmt.where(keyset_predicate(created_at_col, id_col, cursor))
    return stmt.order_by(*keyset_order_by(created_at_col, id_col))


def split_keyset_page[T](rows: Sequence[T], limit: int) -> tuple[list[T], bool]:
    """Split a `LIMIT limit + 1`-fetched row set into `(page, has_more)`.

    Standard keyset "peek" technique: the caller executes its query with
    `LIMIT limit + 1`. If more than `limit` rows come back, the extra row
    proves further matching rows exist beyond this page (`has_more=True`)
    and is discarded; otherwise the query has genuinely run out of
    matching rows (`has_more=False`) — the *query itself* (with its
    soft-delete-excluding predicate already applied) is the source of
    truth for end-of-stream, never `len(page) < limit` in isolation.
    """

    has_more = len(rows) > limit
    return list(rows[:limit]), has_more


def build_page[T](
    items: Sequence[T],
    *,
    has_more: bool,
    cursor_key: Callable[[T], CursorKey],
) -> Page[T]:
    """Build the `{ items, next_cursor }` envelope from an explicit `has_more`.

    `has_more` is taken as given rather than derived from `len(items)` —
    this is what lets a short page (soft-deleted rows filtered out of what
    would otherwise have been a full page) and "end of stream" be
    represented independently, exactly as the contract requires:
    `next_cursor` is `null` only when `has_more` is `False`, regardless of
    how many items are on the page.
    """

    items_list = list(items)
    next_cursor = encode_cursor(cursor_key(items_list[-1])) if has_more and items_list else None
    return Page(items=items_list, next_cursor=next_cursor)


def paginate_rows[T](
    rows: Sequence[T], *, limit: int, cursor_key: Callable[[T], CursorKey]
) -> Page[T]:
    """Convenience wrapper: `split_keyset_page` + `build_page` in one call.

    For the common case where a caller executed `LIMIT limit + 1` and just
    wants the envelope back. Callers with a different `has_more` source
    (e.g. a separate existence check) should call `build_page` directly.
    """

    page_rows, has_more = split_keyset_page(rows, limit)
    return build_page(page_rows, has_more=has_more, cursor_key=cursor_key)
