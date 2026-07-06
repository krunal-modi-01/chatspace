"""Application-side UUIDv7 id generation — the single source of ids.

Per ADR-0005 (message-id-scheme) and the frozen database design, **every**
primary key in this system (`users`, `channels`, `messages`, `attachments`,
`invites`, `password_reset_tokens`, `sessions`, ...) is a UUIDv7 value
generated **in the application**, never a Postgres-side `DEFAULT`. This
module is the one helper every service/model must call to obtain an id.

Why app-side and why UUIDv7:

- The id must be known **before** persist so it can accompany the
  WebSocket fan-out payload (persist-then-publish, ADR-0004) without an
  extra DB round-trip to allocate it.
- UUIDv7 (RFC 9562) embeds a millisecond timestamp in its most-significant
  bits, which makes ids time-sortable. This backs the `(created_at, id)`
  tie-break ordering (R39) and keeps b-tree inserts near-append-only
  (unlike random UUIDv4).

Library: `uuid6` (MIT license, zero runtime dependencies, actively
maintained — see `knowledge/decisions/dependency-uuid6.md` for the full
`dependency-update` vetting record backing this choice).

Monotonicity caveat and why we wrap the library call: `uuid6.uuid7()`
only forces its embedded millisecond timestamp to be non-decreasing
across calls; the trailing ~76 bits are cryptographically random, so two
calls landing in the *same* millisecond are not guaranteed to compare as
`a < b` purely as 128-bit integers. That is too weak for our ordering
guarantee ("clients order by the time-sortable message id", contract
§WS), so this helper adds a process-local, lock-protected monotonic
counter: if a freshly generated id would not compare strictly greater
than the previous one, we bump it by the smallest possible increment.
This makes `generate_id()` **strictly increasing** within a process,
which is a strictly stronger (and sufficient) property than "monotonic".
"""

from __future__ import annotations

import threading
from uuid import UUID

from uuid6 import UUID as _UUIDv7Type
from uuid6 import uuid7 as _uuid7

_lock = threading.Lock()
_last_generated_int: int | None = None


def generate_id() -> UUID:
    """Return a new, application-generated UUIDv7 id.

    This is the **single** helper used for all id assignment across every
    table/entity in the system. Call it before constructing/persisting any
    row so the id is available to accompany a fan-out/publish payload.

    Ids returned by successive calls within the same process are
    **strictly increasing** (hence time-sortable), which is required for
    `(created_at, id)` tie-break ordering and cursor pagination.
    """

    global _last_generated_int

    with _lock:
        candidate = _uuid7()
        candidate_int = candidate.int
        if _last_generated_int is not None and candidate_int <= _last_generated_int:
            # Same millisecond as (or, in pathological clock scenarios,
            # earlier than) the previous id — force strict monotonicity by
            # advancing to the next representable value. The version/
            # variant bits are re-applied so the result stays a valid,
            # well-formed UUIDv7 even in the astronomically unlikely case
            # the increment carries into them.
            candidate_int = _last_generated_int + 1
            candidate = _UUIDv7Type(int=candidate_int, version=7)
        _last_generated_int = candidate_int
        return candidate
