# ADR-0005: Time-sortable message identifiers (UUIDv7)

> Owner: `architect` / `documentation-writer`. Indexed in `architecture/adr/README.md`.

- **Status:** Proposed
- **Date:** 2026-07-02
- **Deciders:** architect + human architecture gate
- **Tags:** data, api, performance

## Context
Each message must carry a **server-assigned, globally-unique, time-sortable id**; server `created_at` is authoritative for ordering and ties are broken by id (F41, R39). The id is the basis for chronological ordering, cursor pagination (ADR-0003), client-side dedup under at-least-once delivery (ADR-0004, F54), and reconnect catch-up "since last id" (F55). The constitution recommends ULID/UUIDv7-class ids. It must be generatable by the app server (not require a DB round-trip to allocate), so the id can be attached before publish and returned to the client.

The forcing question: which id scheme — a time-sortable 128-bit id (UUIDv7/ULID) or a classic auto-increment / random UUIDv4?

## Decision
We will use **UUIDv7** (128-bit, time-ordered, RFC 9562) as the message primary key, **generated in the application server** and stored in Postgres' native `uuid` column type. UUIDv7's leading millisecond timestamp makes ids **monotonically time-sortable**, which we use as the tiebreaker order alongside authoritative `created_at`. Cursor pagination (ADR-0003) orders by `(created_at, id)`; because UUIDv7 is time-ordered, the composite order is stable and index-friendly. Native `uuid` storage keeps index locality good (near-append-only inserts) versus random UUIDv4. ULID is an accepted equivalent if a string-render is preferred, but UUIDv7 wins on native Postgres type support and index efficiency.

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| A (chosen) — UUIDv7, app-generated, native `uuid` column | Globally unique without coordination; time-sortable (satisfies R39 directly); no DB round-trip to allocate (id known before persist-then-publish); native pg `uuid` type = compact 16 bytes + good index locality from time-ordering; standardised (RFC 9562) | Slightly larger than a bigint; requires a UUIDv7 generation lib until stdlib support is ubiquitous |
| B — ULID (Crockford base32 string) | Time-sortable; human-readable 26-char; widely libraried | Stored as text/16-byte custom type; larger index footprint or extra encoding vs native uuid; non-standard type handling in tooling |
| C — Auto-increment `bigint` | Tiny, fast, naturally ordered | Requires a DB round-trip to allocate (breaks "id known before publish"); leaks volume/enumeration; not globally unique across future splits; ordering coupled to a single sequence |
| D — Random UUIDv4 | Globally unique, no coordination | **Not** time-sortable → cannot serve as ordering tiebreaker (fails R39); random inserts cause index fragmentation/write amplification |

## Consequences
- **Positive:** One value simultaneously serves as PK, ordering tiebreaker, pagination cursor component, dedup key, and catch-up marker. App-side generation lets the id accompany the message through persist-then-publish (ADR-0004) with no extra round-trip. Time-ordering keeps b-tree inserts near-sequential, protecting write latency at 1,000 users.
- **Negative / trade-offs:** Depends on a UUIDv7 generation library until Python stdlib coverage is standard; `dependency-update` vetting applies. UUIDv7 embeds a coarse creation timestamp in the id (millisecond precision) — a minor information-leak, acceptable since `created_at` is already returned with each message.
- **Follow-ups:** `dependency-update` skill vets the chosen UUIDv7 library; `database-engineer` sets the `uuid` PK type and confirms the `(created_at, id)` / DM-pair indexes (ADR-0002, ADR-0003); `backend-engineer` generates the id at message-service creation time, before publish.

## Compliance / reversibility
Hard to reverse once ids are minted and stored in cursors/clients — the id scheme is effectively permanent for existing data. This raises the bar for getting it right now, which is why a proven, standardised, time-sortable scheme (UUIDv7) is chosen over novelty. No regulatory implication.
