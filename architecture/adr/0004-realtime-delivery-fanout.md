# ADR-0004: Real-time delivery — Redis pub/sub, persist-then-publish, at-least-once + client dedup

> Owner: `architect` / `documentation-writer`. Indexed in `architecture/adr/README.md`.

- **Status:** Proposed
- **Date:** 2026-07-02
- **Deciders:** architect + human architecture gate
- **Tags:** architecture, realtime, data, performance

## Context
New messages, edits, and soft-deletes must appear live over WebSocket without a refresh (F51, F42, F43, R15/R52), and must fan out to members connected to **any** of the 1–2 app instances (F53, R17). The constitution mandates Redis pub/sub for cross-instance broadcast and **no message queue** (Kafka/RabbitMQ). Delivery is **persist-then-publish** (F45, R40): the durable record commits before the real-time event is emitted. Delivery is **at-least-once with client-side dedup by message id** (F54, R18), and reconnecting clients catch up via history from the last received id (F55). The open decision (PRD §12, spec §9): plain persist-then-publish vs a transactional outbox to close the dual-write gap.

The forcing question: how do we broadcast across instances, and how strong a delivery guarantee do we build now?

## Decision
We will use **Redis pub/sub** for cross-instance fan-out with **plain persist-then-publish** for v1:

1. On send/edit/delete, the app **commits the durable Postgres write first**, then **publishes** an event (`message.created` / `message.edited` / `message.deleted`, plus `typing` and `presence`) to a Redis channel keyed by the target — `chan:{channel_id}` for channels, `dm:{userA_id}:{userB_id}` (canonical pair, ADR-0002) for DMs.
2. Every app instance **subscribes** to the Redis channels for the conversations its locally-connected clients have joined, and relays received events to those WebSocket connections.
3. Delivery is **at-least-once**; every event carries the message id; **clients dedup by message id** (F54) and reconcile edits/deletes idempotently.
4. On reconnect, clients fetch history since their last received id (ADR-0003) and dedup — this is the recovery path for any event dropped during a disconnect (F55).

We explicitly **defer the transactional outbox** to a future ADR, to be triggered by load-test findings or observed dual-write loss. The residual dual-write risk (Postgres commit succeeds, Redis publish fails → live event missed) is bounded and **recovered by reconnect catch-up + periodic client resync**, which is acceptable at 1,000 users.

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| A (chosen) — Redis pub/sub + plain persist-then-publish + at-least-once/client-dedup | Simplest correct design at this scale; no queue infra; matches constitution + F45/F54/F55; reconnect catch-up already covers dropped publishes; fire-and-forget publish keeps send latency low | Dual-write gap: a failed publish after commit means live clients miss the event until they refetch (bounded by catch-up); Redis is a SPOF for live delivery (accepted, see failure modes) |
| B — Transactional outbox (write event to an `outbox` table in the same tx, a relay publishes) | Closes the dual-write gap; guaranteed eventual publish | Adds an outbox table + a relay loop/poller (a de-facto worker) — more moving parts than the constitution wants for v1; higher write amplification; not justified without evidence of loss |
| C — Message queue (RabbitMQ/Kafka) for delivery | Durable delivery, replay | Explicitly out of scope (§2 non-goals, constitution #7); massive operational overhead for 1,000 users |

## Consequences
- **Positive:** Live delivery works across instances with only the Redis that is already required; low send latency (publish is non-blocking after commit); the recovery story (history catch-up + dedup) is the same mechanism used for offline catch-up, so there is one code path to test. Persist-then-publish guarantees a live event is never emitted for an uncommitted message.
- **Negative / trade-offs:** A publish that fails after a successful commit produces a **temporary** live-delivery miss until the client refetches (bounded, self-healing). Redis loss stops all live delivery, presence, and rate limiting simultaneously (single-Redis SPOF, accepted per §9 / risk in TSD §12) — REST/history keep working from Postgres. Ordering across a fan-out is best-effort; clients order by the sortable message id (ADR-0005), not by arrival order.
- **Follow-ups:** `backend-engineer` implements the persist-then-publish sequence, the per-conversation subscribe/relay in the WS connection manager, and a lightweight periodic client resync; `performance-engineer` load-tests fan-out across 2 instances at 1,000 users (F65) and reports whether observed publish-loss justifies promoting to the outbox (Option B) in a follow-up ADR; `api-reviewer` documents the WS event envelope and dedup contract.

## Compliance / reversibility
Reversible: upgrading to a transactional outbox (Option B) later is additive (an `outbox` table + relay) and does not change the client-facing WS event contract or the dedup behaviour. No regulatory implication. This ADR depends on ADR-0005 (sortable message id used for ordering + dedup) and ADR-0002 (DM topic keying).
