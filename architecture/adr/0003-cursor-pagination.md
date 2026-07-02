# ADR-0003: Cursor (keyset) pagination for message history

> Owner: `architect` / `documentation-writer`. Indexed in `architecture/adr/README.md`.

- **Status:** Proposed
- **Date:** 2026-07-02
- **Deciders:** architect + human architecture gate
- **Tags:** data, api, performance

## Context
Channel and DM history must be retrieved in chronological order, excluding soft-deleted content, with pagination (F44, F48, R11/R13). The PRD baseline (§5b) already mandates cursor-based pagination with the shape `?limit=&cursor=` → `{ items, next_cursor }`, and message ids are server-assigned, globally-unique, time-sortable values with `created_at` authoritative and ties broken by id (F41, R39, ADR-0005). Reconnect catch-up (F55) also needs to fetch "everything after the last received message id" cheaply and deterministically. This ADR confirms the mechanism and the cursor encoding.

The forcing question: keyset (cursor) vs offset pagination, and how is the cursor encoded?

## Decision
We will use **keyset (cursor) pagination** ordered by `(created_at, id)` — the same total order used for message identity (ADR-0005). The response shape is `{ items, next_cursor }`; `next_cursor` is **null** when no more rows exist. The cursor is an **opaque, base64url-encoded token** carrying the `(created_at, id)` of the last item in the page (not a raw offset), so clients treat it as opaque and the server can evolve its internals. Reconnect catch-up (F55) uses the same endpoint by passing the last received message id as the cursor origin. Default/expected page size follows §5a where applicable (public-channel list = 50); message-history page size is bounded by a server maximum defined in the API contract.

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| A (chosen) — Keyset/cursor on `(created_at, id)`, opaque base64url cursor | O(log n + page) via index seek regardless of depth; stable under concurrent inserts (no skipped/duplicated rows as new messages arrive); aligns naturally with the time-sortable id and reconnect catch-up (F55); opaque cursor hides internals and is tamper-evident-friendly | Cannot random-access "page N"; slightly more logic than `LIMIT/OFFSET`; cursor must encode a composite key to break `created_at` ties |
| B — Offset/limit (`LIMIT n OFFSET m`) | Trivial to implement; supports jump-to-page | Deep offsets scan-and-discard → latency grows with depth, blowing the p95 < 500 ms budget on active channels; concurrent inserts shift the window causing skipped/duplicated messages — unacceptable for a live feed |

## Consequences
- **Positive:** History reads stay fast and correct on hot channels no matter how deep the scroll; the same index `(channel_id, created_at, id)` / DM pair equivalent serves history, catch-up, and ordering; opaque cursors keep the contract stable and let the DB implementation change without breaking clients.
- **Negative / trade-offs:** No "go to page 47" affordance — acceptable for a chat timeline, which is inherently sequential. Clients must treat the cursor as opaque and not construct it. Soft-deleted rows are excluded by the query predicate (F44), so page sizes can be smaller than `limit` when deletions are dense — the contract documents that `items.length <= limit` is expected.
- **Follow-ups:** `database-engineer` defines the covering indexes for channel history `(channel_id, created_at, id)` and the DM pair equivalent (ADR-0002) and confirms soft-delete filtering is index-friendly; `api-reviewer` specifies the exact cursor encoding, max page size, and the `{items, next_cursor}` schema in the API contract.

## Compliance / reversibility
Reversible cheaply while cursors remain opaque: the encoding and underlying ordering can change without a client-visible contract change. No regulatory implication.
