# ADR-0012: Per-user WebSocket topic for membership lifecycle events

> Owner: `architect` / `documentation-writer`. Indexed in `architecture/adr/README.md`.

- **Status:** Proposed
- **Date:** 2026-07-13
- **Deciders:** architect + human architecture gate
- **Tags:** architecture, realtime, api, security

## Context
PRD v3 adds R57: when a user is added to or removed from a channel, all of that user's connected clients must update their channel list live, without a refresh (F74/F75). ADR-0004 keys every fan-out topic **per conversation** — `chan:{channel_id}` for channels, `dm:{a}:{b}` for DMs — and subscriptions are **client-initiated**: a connection sends a `join` frame, the server membership-checks it, then subscribes the connection to that topic.

A membership *grant* cannot be delivered on that model. The newly added user's client does not know the channel exists, so it cannot send a `join` frame for it; a removed user is being unsubscribed from the only topic that could tell them about the removal. R57 requires delivery addressed to a **user**, not to a conversation — a topic class ADR-0004 does not define, with subscription semantics (server-initiated) it does not cover.

The forcing question: on what topic, with what subscription rule, are membership lifecycle events delivered?

## Decision
We will introduce a **per-user Redis topic `user:{user_id}`**, auto-subscribed **server-side** for every authenticated WebSocket connection at connect time (immediately after token auth; no client frame involved, and no connection can ever subscribe to another user's topic).

1. On a committed membership change (self join, self leave, channel-admin add, channel-admin remove), the app publishes a membership event to the **affected user's** topic — `channel.member_added` (carrying the channel summary, so the client can insert without a follow-up fetch) or `channel.member_removed` (carrying the channel id). Publishing follows ADR-0004's persist-then-publish ordering and fail-open error handling.
2. Each app instance's relay pattern-subscribes `user:*` (exactly as it does `presence:*`) and forwards a received event to that user's locally connected clients only.
3. Events are **at-least-once with no replay**: clients reconcile idempotently by channel id, and a reconnecting client refetches `GET /v1/channels` (F73) instead of expecting missed membership events — mirroring the message catch-up model (F55).
4. Explicit non-events: deactivation-triggered removal (the target's connections are dropped anyway, F25/F52) and role-only changes (`my_role` staleness self-heals on the next list fetch).

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| A (chosen) — per-user topic `user:{user_id}`, server-auto-subscribed at connect | Structurally correct addressing for user-scoped events; identity == authorization (no membership check needed at subscribe); reusable push channel for future user-scoped events (e.g. DM notifications); mirrors the existing `presence:*` relay pattern | New topic class + new (server-initiated) subscription semantics beyond ADR-0004; one more pattern-subscription in the relay |
| B — publish membership events on the conversation topic `chan:{channel_id}` | No new topic class | Structurally fails: the added user is not subscribed to the channel topic yet, and the removed user is being unsubscribed — the one user who must receive the event is exactly the one who cannot |
| C — client polls `GET /v1/channels` | No WS change at all | Contradicts the R15/R57 live-without-refresh product bar; polling load scales with connected users for an event that is rare per user |
| D — single global membership topic, filtered client-side | One topic, simple publish | Leaks private-channel metadata to every connected client (violates the R7/§8 membership-authorization bar); fan-out volume scales with workspace-wide membership churn |

## Consequences
- **Positive:** The added-to-a-private-channel user learns about the channel the moment the membership commits — closing the R56/R57 gap end-to-end. The topic is a general-purpose, authorization-safe per-user push channel future features can reuse. Privacy is structural: membership events reach only the affected user's connections, so private-channel metadata is delivered exclusively to the user whose membership just made them entitled to it.
- **Negative / trade-offs:** The relay carries one more pattern-subscription class (`user:*`). Membership events are fire-and-forget with no history/replay — the reconnect channel-list refetch is **mandatory** client behavior and must stay documented in the API contract (WS section) and FS Flow L, or at-least-once has a silent hole. Role-only changes deliberately emit no event; the displayed role may be stale until the next list fetch (accepted, documented in F75).
- **Follow-ups:** implemented by task T49 (topic helper, auto-subscribe, `user:*` relay pattern, publish-after-commit in the four membership mutation paths) with T51 as the consuming client; `api-reviewer` documents the two events and the no-replay note in the API contract; `security-reviewer` verifies the per-user delivery isolation (no cross-user receipt) as a T49 acceptance criterion.

## Compliance / reversibility
Additive within `/v1`: new WS event types are explicitly permitted by the API contract's versioning conventions, and clients must already tolerate unknown event types — so rollout order (server before client) is safe. Reversible by dropping the topic and events without breaking existing clients. No schema change and no regulatory implication. This ADR extends (does not amend) ADR-0004: conversation-keyed topics and their join-frame semantics are unchanged.
