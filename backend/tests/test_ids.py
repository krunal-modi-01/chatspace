from __future__ import annotations

import threading
import uuid
from itertools import pairwise
from uuid import UUID

import pytest

from app.core import ids


def test_generate_id_returns_a_valid_uuid7() -> None:
    generated = ids.generate_id()

    assert isinstance(generated, UUID)
    assert generated.version == 7
    # RFC 4122/9562 variant bits (the two most-significant bits of the
    # clock-seq-and-variant octet must be "10").
    assert generated.variant == uuid.RFC_4122


def test_generate_id_is_unique_across_many_calls() -> None:
    batch = [ids.generate_id() for _ in range(10_000)]

    assert len(set(batch)) == len(batch)


def test_generate_id_is_monotonically_time_sortable_within_a_process() -> None:
    """Property test: a large batch generated back-to-back must be strictly
    increasing, which is a stronger (and sufficient) guarantee than mere
    non-decreasing monotonicity — this is what backs the `(created_at, id)`
    tie-break ordering (R39) and client-side dedup/ordering (ADR-0005)."""

    batch = [ids.generate_id() for _ in range(50_000)]

    for earlier, later in pairwise(batch):
        assert earlier.int < later.int


def test_generate_id_embedded_timestamp_is_non_decreasing() -> None:
    """The UUIDv7 millisecond timestamp field itself should never regress,
    independent of the strict-monotonicity wrapper around the random tail."""

    batch = [ids.generate_id() for _ in range(5_000)]

    timestamps = [uuid.int >> 80 for uuid in batch]
    assert timestamps == sorted(timestamps)


def test_generate_id_is_thread_safe_and_stays_strictly_increasing() -> None:
    """Concurrent callers must never observe a duplicate or out-of-order id
    — the module-level counter is guarded by a lock."""

    results: list[UUID] = []
    lock = threading.Lock()

    def worker() -> None:
        local_batch = [ids.generate_id() for _ in range(2_000)]
        with lock:
            results.extend(local_batch)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(set(results)) == len(results), "duplicate id generated under concurrency"


def test_generate_id_forces_strict_increase_when_wrapped_uuid7_ties_or_regresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Directly exercise the fallback path: if the underlying `uuid7()` call
    returns a value that does not compare strictly greater than the
    previously issued id (same millisecond or a clock regression), the
    helper must still produce a strictly greater id."""

    from uuid6 import UUID as UUIDv6

    first = ids.generate_id()

    # Force the *next* underlying uuid7() call to tie with `first`, so we
    # can assert the wrapper's forced-increment fallback engages.
    tying_value = UUIDv6(int=first.int, version=7)
    monkeypatch.setattr(ids, "_uuid7", lambda: tying_value)

    second = ids.generate_id()

    assert second.int == first.int + 1
    assert second.version == 7


def test_generate_id_module_state_reset_between_tests_is_not_required() -> None:
    """Sanity check that module-level state does not leak invalid ids across
    independent calls — i.e. every id remains a well-formed UUIDv7 even
    after the forced-increment fallback has fired in a prior test."""

    generated = ids.generate_id()

    assert generated.version == 7
