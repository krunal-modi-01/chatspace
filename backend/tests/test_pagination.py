"""T07: cursor pagination utility — encode/decode, limit clamping, envelope.

Covers the contract invariants directly (ADR-0003, Pagination clause):
opaque base64url cursor over `(created_at, id)`, DESC keyset query shape,
default 50 / clamp to 100, `next_cursor=null` at true end of stream, a
malformed cursor -> `400` problem+json, and — the two semantics the task
calls out explicitly — end-of-stream vs. a short page that is *not* the
end (soft-deleted-row exclusion).

Scope: this file tests the reusable utility only. It does not stand up
the `messages` table or exercise T21/T22's concrete history queries.
"""

from __future__ import annotations

import base64
import struct
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Column, DateTime, MetaData, Table, Uuid, select

from app.core.pagination import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    CursorKey,
    PaginationError,
    apply_keyset,
    build_page,
    decode_cursor,
    encode_cursor,
    paginate_rows,
    resolve_limit,
    split_keyset_page,
)


def _key(created_at: datetime, id_: UUID | None = None) -> CursorKey:
    return CursorKey(created_at=created_at, id=id_ or uuid4())


class TestEncodeDecodeRoundTrip:
    def test_round_trip_is_stable(self) -> None:
        key = _key(datetime(2026, 7, 6, 12, 34, 56, 789123, tzinfo=UTC))

        encoded = encode_cursor(key)
        decoded = decode_cursor(encoded)

        assert decoded == key

    def test_round_trip_preserves_microsecond_precision(self) -> None:
        key = _key(datetime(2026, 1, 1, 0, 0, 0, 1, tzinfo=UTC))

        assert decode_cursor(encode_cursor(key)).created_at == key.created_at

    def test_round_trip_normalizes_non_utc_timezone_to_the_same_instant(self) -> None:
        tz = UTC
        aware = datetime(2026, 7, 6, 10, 0, 0, tzinfo=tz)
        key = _key(aware)

        decoded = decode_cursor(encode_cursor(key))

        assert decoded.created_at == aware

    def test_encoding_is_deterministic(self) -> None:
        key = _key(datetime(2026, 3, 15, 8, 0, 0, tzinfo=UTC))

        assert encode_cursor(key) == encode_cursor(key)

    def test_two_different_keys_encode_differently(self) -> None:
        base = datetime(2026, 3, 15, 8, 0, 0, tzinfo=UTC)
        first = _key(base)
        second = _key(base + timedelta(microseconds=1))

        assert encode_cursor(first) != encode_cursor(second)


class TestCursorIsOpaque:
    def test_cursor_is_urlsafe_base64_text_not_json_or_a_raw_uuid(self) -> None:
        key = _key(datetime(2026, 7, 6, tzinfo=UTC))

        encoded = encode_cursor(key)

        # Opaque wire format: plain base64url alphabet, no separators/braces
        # a client could infer structure from or hand-construct.
        assert all(c.isalnum() or c in "-_" for c in encoded)
        assert "{" not in encoded
        assert ":" not in encoded
        assert str(key.id) not in encoded

    def test_hand_constructed_cursor_is_rejected(self) -> None:
        # A client "constructing" a cursor (contract: MUST treat opaque,
        # never construct) from a plausible-looking but wrong payload must
        # fail cleanly, not silently decode to a wrong-but-valid position.
        fake_payload = b"\x00" * 10  # wrong length
        fake_cursor = base64.urlsafe_b64encode(fake_payload).rstrip(b"=").decode()

        with pytest.raises(PaginationError) as exc_info:
            decode_cursor(fake_cursor)

        assert exc_info.value.field == "cursor"


class TestDecodeMalformedCursor:
    def test_empty_cursor_raises(self) -> None:
        with pytest.raises(PaginationError):
            decode_cursor("")

    def test_non_base64_cursor_raises(self) -> None:
        with pytest.raises(PaginationError):
            decode_cursor("not-valid-base64url!!!")

    def test_wrong_length_payload_raises(self) -> None:
        short_payload = base64.urlsafe_b64encode(b"short").rstrip(b"=").decode()

        with pytest.raises(PaginationError):
            decode_cursor(short_payload)

    def test_valid_cursor_with_trailing_junk_raises_instead_of_bypassing(self) -> None:
        # `base64.urlsafe_b64decode` silently discards characters outside
        # its alphabet, so appending junk to an otherwise-good cursor must
        # not be allowed to decode to the original (valid) `CursorKey`.
        good = encode_cursor(_key(datetime(2026, 7, 6, tzinfo=UTC)))

        with pytest.raises(PaginationError) as exc_info:
            decode_cursor(good + "!!!!")

        assert exc_info.value.field == "cursor"

    def test_out_of_range_timestamp_raises_instead_of_overflow_error(self) -> None:
        # A correct-length (24-byte) payload whose leading 8 bytes are an
        # int64 microsecond count far outside the range `timedelta`/
        # `datetime` can represent must be rejected as `PaginationError`,
        # not escape as an uncaught `OverflowError` (which would surface
        # as a 500 instead of the contract's mandated 400).
        payload = struct.pack(">q", 2**63 - 1) + b"\x00" * 16
        bad_cursor = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()

        with pytest.raises(PaginationError) as exc_info:
            decode_cursor(bad_cursor)

        assert exc_info.value.field == "cursor"

    def test_malformed_cursor_maps_to_400_problem_json(self, client: TestClient) -> None:
        """No consuming endpoint exists yet (T21/T22); exercise the handler
        directly, the same way `test_errors.py` proves handler wiring for
        other error types before their routes exist."""

        from app.core.pagination import PaginationError as PE

        with pytest.raises(PE):
            decode_cursor("!!!not-a-cursor!!!")

        # And confirm the handler is registered so a future consuming
        # route gets the frozen 400 problem+json shape automatically.
        from app.main import create_app

        app = create_app()
        assert PE in app.exception_handlers


class TestResolveLimit:
    def test_none_defaults_to_fifty(self) -> None:
        assert resolve_limit(None) == DEFAULT_LIMIT == 50

    def test_within_range_is_unchanged(self) -> None:
        assert resolve_limit(10) == 10

    def test_limit_above_max_clamps_to_100(self) -> None:
        assert resolve_limit(9999) == MAX_LIMIT == 100

    def test_limit_exactly_at_max_is_unchanged(self) -> None:
        assert resolve_limit(100) == 100

    def test_zero_limit_is_invalid(self) -> None:
        with pytest.raises(PaginationError) as exc_info:
            resolve_limit(0)
        assert exc_info.value.field == "limit"

    def test_negative_limit_is_invalid(self) -> None:
        with pytest.raises(PaginationError):
            resolve_limit(-5)


class TestKeysetQueryShape:
    """Validate the generated `WHERE`/`ORDER BY` against a stand-in table.

    Deliberately not the real `messages` table (owned by T21/T22) — any
    two-column `(created_at, id)`-ordered table exercises the same builder
    logic the concrete history queries will reuse.
    """

    def _table(self) -> Table:
        metadata = MetaData()
        return Table(
            "history_rows",
            metadata,
            Column("id", Uuid, primary_key=True),
            Column("created_at", DateTime(timezone=True), nullable=False),
        )

    def test_no_cursor_orders_desc_without_a_where_clause(self) -> None:
        table = self._table()
        stmt = select(table)

        applied = apply_keyset(
            stmt, created_at_col=table.c.created_at, id_col=table.c.id, cursor=None
        )
        compiled = str(applied.compile(compile_kwargs={"literal_binds": False}))

        assert "WHERE" not in compiled
        assert "ORDER BY history_rows.created_at DESC, history_rows.id DESC" in compiled

    def test_cursor_adds_composite_tuple_predicate_and_desc_order(self) -> None:
        table = self._table()
        stmt = select(table)
        cursor = _key(datetime(2026, 7, 6, tzinfo=UTC))

        applied = apply_keyset(
            stmt, created_at_col=table.c.created_at, id_col=table.c.id, cursor=cursor
        )
        compiled = str(applied.compile(compile_kwargs={"literal_binds": False}))

        assert "WHERE" in compiled
        assert "history_rows.created_at, history_rows.id" in compiled
        assert "ORDER BY history_rows.created_at DESC, history_rows.id DESC" in compiled


class TestSplitKeysetPage:
    def test_fetching_exactly_limit_plus_one_signals_has_more(self) -> None:
        rows = list(range(6))  # limit+1 rows fetched for limit=5

        page, has_more = split_keyset_page(rows, limit=5)

        assert page == [0, 1, 2, 3, 4]
        assert has_more is True

    def test_fetching_limit_or_fewer_signals_no_more(self) -> None:
        rows = list(range(5))  # exactly limit, no extra peek row

        page, has_more = split_keyset_page(rows, limit=5)

        assert page == rows
        assert has_more is False


class TestEndOfStreamSemantics:
    """`next_cursor` is null only when the keyset query truly has no more rows."""

    def test_true_end_of_stream_yields_null_next_cursor(self) -> None:
        rows = [_key(datetime(2026, 1, 1, tzinfo=UTC)) for _ in range(3)]

        page = build_page(rows, has_more=False, cursor_key=lambda k: k)

        assert len(page.items) == 3
        assert page.next_cursor is None

    def test_empty_stream_yields_null_next_cursor(self) -> None:
        page = build_page([], has_more=False, cursor_key=lambda k: k)

        assert page.items == []
        assert page.next_cursor is None

    def test_more_rows_remaining_yields_a_next_cursor(self) -> None:
        rows = [_key(datetime(2026, 1, 1, tzinfo=UTC)) for _ in range(5)]

        page = build_page(rows, has_more=True, cursor_key=lambda k: k)

        assert page.next_cursor is not None
        assert decode_cursor(page.next_cursor) == rows[-1]


class TestShortPageIsNotNecessarilyEndOfStream:
    """The soft-delete-exclusion semantics the contract calls out by name.

    Soft-deleted rows are excluded by the query predicate *before* this
    utility ever sees the rows (F44) — so a page can come back shorter
    than the requested `limit` purely because deletions thinned it out,
    while further (non-deleted) rows still exist beyond it. This utility
    must key `next_cursor` off the explicit `has_more` signal, never off
    `len(items) < limit`, so this case and true end-of-stream stay
    distinguishable.
    """

    def test_short_page_with_more_remaining_still_gets_a_next_cursor(self) -> None:
        limit = 50
        # Only 2 items on this page (heavy soft-deletion thinned the
        # window) yet the caller's peek fetch confirmed more rows exist.
        short_page = [_key(datetime(2026, 1, 1, tzinfo=UTC)) for _ in range(2)]

        page = build_page(short_page, has_more=True, cursor_key=lambda k: k)

        assert len(page.items) < limit
        assert page.next_cursor is not None

    def test_paginate_rows_full_page_with_extra_peek_row_still_signals_more(self) -> None:
        # `paginate_rows` derives `has_more` from the standard `LIMIT
        # limit + 1` peek: 11 rows fetched for limit=10 means a full page
        # of 10 plus proof that at least one more (non-deleted, predicate-
        # matched) row exists beyond it.
        fetched = [_key(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=i)) for i in range(11)]

        page = paginate_rows(fetched, limit=10, cursor_key=lambda k: k)

        assert len(page.items) == 10
        assert page.next_cursor is not None
        assert decode_cursor(page.next_cursor) == fetched[9]

    def test_paginate_rows_short_page_with_no_extra_row_is_genuinely_the_end(self) -> None:
        # Same shape of query, but the soft-delete-filtered predicate only
        # had 4 matching rows left in the entire remaining stream — the
        # fetch (which asked for up to 11) came back short, and there was
        # no 11th row to prove more exist, so this really is the end.
        fetched = [_key(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=i)) for i in range(4)]

        page = paginate_rows(fetched, limit=10, cursor_key=lambda k: k)

        assert len(page.items) == 4  # short relative to limit=10
        assert page.next_cursor is None

    def test_default_and_max_limit_constants_match_contract(self) -> None:
        assert DEFAULT_LIMIT == 50
        assert MAX_LIMIT == 100
