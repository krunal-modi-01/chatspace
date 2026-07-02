# ADR-0001: Modular monolith FastAPI serving REST + WebSocket

> Owner: `architect` / `documentation-writer`. Indexed in `architecture/adr/README.md`.

- **Status:** Proposed
- **Date:** 2026-07-02
- **Deciders:** architect + human architecture gate
- **Tags:** architecture, scale, deployment

## Context
chatspace v1 must deliver a full communication loop (auth, channels, messaging, DMs, media, presence, real-time delivery) for **~1,000 concurrent users on a single deployment** (`CLAUDE.md` Operating Principle #7, R21). The functional spec requires both REST (CRUD, history, auth, invites, admin — §5b) and WebSocket real-time delivery (F51–F56), with cross-instance fan-out via Redis pub/sub (F53). The constitution explicitly forbids sharding, message-queue clusters, multi-region, and Kubernetes at this scale, and asks for "the simplest proven design."

The forcing question: how many deployable units should the backend be, and where do the WebSocket and REST responsibilities live?

## Decision
We will build the backend as a **single modular monolith FastAPI application** that serves both the REST API and the WebSocket endpoint in the same process, deployed as **1–2 identical stateless instances** behind the platform load balancer. Internally the app is organised into modules by domain (`auth`, `users`, `channels`, `messages`, `dm`, `ws`, `presence`, `media`, `invites`, `admin`, `ratelimit`) with a service layer, per `CLAUDE.md` repository structure. Cross-instance WebSocket broadcast is achieved through Redis pub/sub (see ADR-0004), so any instance can serve any connection. Instances hold no session affinity beyond the lifetime of an individual WebSocket connection.

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| A (chosen) — Single modular monolith (REST + WS in one FastAPI app, 1–2 instances) | Simplest to build/operate/observe; one deploy artifact; matches 1,000-user ceiling and constitution #7; module boundaries preserve future extractability; Redis pub/sub already required for fan-out so multi-instance works without stickiness | One codebase can grow coupled without discipline; a crash takes REST + WS together on that instance (mitigated by ≥2 instances behind LB) |
| B — Split WebSocket service from REST service (2 deployables) | Independent scaling of connection-heavy WS tier | Premature at this scale; adds a second deploy pipeline, inter-service auth, and shared-DB coupling for no measured benefit; violates #7 |
| C — Microservices (auth/messaging/presence/media as separate services) | Independent teams/scaling; clear bounded contexts | Massive operational overhead (service mesh, distributed tracing, N pipelines); network hops blow the p95 < 500 ms budget; explicitly out of scope |

## Consequences
- **Positive:** One thing to build, test, deploy, and reason about. Latency budget preserved (no internal network hops). Stateless instances make horizontal add/remove trivial. Module seams give a clean extraction path if real usage later justifies splitting the WS tier (recorded as a future ADR, not guessed now).
- **Negative / trade-offs:** REST and WS share a process and resource envelope; a WS connection storm can pressure REST latency on the same instance. We accept this at 1,000 users and mitigate with ≥2 instances and per-user rate limits (F63–F64). Module discipline must be enforced in code review to avoid a big ball of mud.
- **Follow-ups:** Define module import boundaries in the TSD §3 component table; `backend-engineer` enforces the service-layer separation; `performance-engineer` load-tests the combined REST+WS envelope on one instance (F65) to confirm the two-instance headroom assumption.

## Compliance / reversibility
Reversible at moderate cost: because the app is modular and instances are stateless with Redis-mediated fan-out, extracting the WS tier into its own deployable later is a packaging/deploy change, not a rewrite. No regulatory implication. This ADR is the baseline all other ADRs assume.
