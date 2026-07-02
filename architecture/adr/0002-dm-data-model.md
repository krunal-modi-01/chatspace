# ADR-0002: Direct-message data model (recipient_id on messages, no channel row)

> Owner: `architect` / `documentation-writer`. Indexed in `architecture/adr/README.md`.

- **Status:** Proposed
- **Date:** 2026-07-02
- **Deciders:** architect + human architecture gate
- **Tags:** data, api

## Context
v1 supports 1:1 DMs between two distinct active users (F46–F48, R12/R13); no group DMs, no DM blocking. The `CLAUDE.md` DOMAIN MODEL already defines `Message` with `channel_id (nullable if DM)` and `recipient_id (nullable if channel)`, and the functional spec §7 states behaviourally that "a DM message is a `Message` with `recipient_id` set and `channel_id` null." Authorization must be enforced on every DM read/write and media fetch (F34, F59). The open decision (PRD §12, spec §9): reuse the `channels` table as a 2-member private channel, or use a dedicated direct-message representation.

The forcing question: what is the physical identity of a DM conversation, and does DM authorization reuse channel-membership machinery?

## Decision
We will represent a DM message as a **`Message` row with `recipient_id` set and `channel_id` NULL** — no `channels` row is created for DMs. Conversation identity is the **unordered pair of the two user ids**, derived deterministically as `(least(sender_id, recipient_id), greatest(sender_id, recipient_id))`. DM history (F48) and live delivery target this canonical pair. DM authorization is a **participant check** (the requester must be `sender_id` or `recipient_id`), a separate, simpler code path from channel-membership checks — not a reuse of `ChannelMember`. A `CHECK` constraint enforces the "exactly one of `channel_id` / `recipient_id` is set" invariant, and self-DM (`sender_id = recipient_id`) is rejected at the API and by constraint (F47). Both participants are always current active users, so "membership" for a DM is simply "you are one of the two ids."

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| A (chosen) — Dedicated DM: `Message.recipient_id` + derived pair key, participant-check authz | Matches the existing domain model verbatim; no synthetic channel rows polluting the channels table / public list; no channel-name handling for DMs; DM authz is trivial and cheap; single `messages` table serves both channel and DM history with the same id/ordering/pagination (ADR-0003, ADR-0005) | Two authorization code paths (channel membership vs DM participant); a partial index / composite index on the pair is needed for efficient DM history |
| B — Reuse `channels` as a 2-member private channel per DM | One unified message + membership + authz path | Creates a channel row + 2 ChannelMember rows per conversation; must exclude these from the public-channel browse list (F30) and channel management; channel-name uniqueness (1–80 chars, R36) is meaningless for DMs; last-admin succession (F36) and zero-admin terminal state (F37) become nonsensical for DMs; more moving parts for a simpler feature — contradicts "simplest design" |

## Consequences
- **Positive:** The DM feature adds almost no schema surface — it rides the `messages` table already needed for channels. Ordering, sortable ids, cursor pagination, persist-then-publish, and client dedup all work identically for channel and DM messages. The channels domain (browse/join/leave/succession) stays clean and DM-free.
- **Negative / trade-offs:** DM authorization is a distinct branch that `security-reviewer` must verify independently from channel-membership checks (F34). DM history queries filter on the canonical user-pair rather than a single `channel_id`, so `database-engineer` must add the appropriate composite/partial index to keep DM history within the latency budget.
- **Follow-ups:** `database-engineer` specifies the DM pair index and the `CHECK` constraint in the `templates/database-design.md` instance; `api-reviewer` defines the DM history endpoint keyed by the other participant's user id in the `templates/api-contract.md` instance; the WebSocket delivery topic scheme (ADR-0004) must include a DM-conversation channel keyed by the canonical pair.

## Compliance / reversibility
Reversible but not free: moving to a channels-backed DM model later would require a data migration to synthesise channel + membership rows and a rewrite of DM authz. Given v1 has no group DMs on the roadmap, the dedicated model is the lower-risk bet. No regulatory implication; DM content and participant identities are PII/sensitive and governed by the same logging and access rules as channel messages.
