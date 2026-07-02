# Architectural Patterns Cheat-Sheet

Quick reference for the `architecture` skill. Pick per boundary, not per system — mixing is normal.

## Decision shortcuts
- **Default:** modular monolith + single primary datastore. Deviate only when a named driver forces it.
- **Rich domain logic to protect from I/O churn?** → Hexagonal (ports & adapters).
- **Components must decouple in time / fan out / absorb spikes?** → Event-driven.
- **Independent deploy cadence, independent scaling, fault isolation, or team autonomy is a proven need?** → Microservices.
- **CRUD-dominant, thin logic?** → Layered.

## Trade-offs table

| Pattern | Use when | Strengths | Costs / risks | Avoid when |
|---|---|---|---|---|
| **Layered (n-tier)** | CRUD-heavy apps, thin domain logic, small teams | Simple, universally understood, fast to start | Business logic leaks into controllers/DB; poor domain isolation | Domain rules are complex or long-lived |
| **Modular monolith** | Most new systems; unclear boundaries; one team or a few | One deploy, strong consistency, easy refactor, cheap to run; can later split | Requires discipline to keep module boundaries; scales as one unit | You genuinely need independent deploy/scale per module |
| **Hexagonal (ports & adapters)** | Rich domain that must outlive its I/O (DBs, queues, APIs) | Domain testable in isolation; swappable adapters; clear inbound/outbound ports | More upfront structure; overkill for CRUD | Logic is trivial pass-through |
| **Event-driven (pub/sub, streaming)** | Temporal decoupling, fan-out, spike absorption, audit/event-sourcing | Loose coupling, resilience, scalability, replay/audit | Eventual consistency; hard to trace/debug; ordering & dedup complexity | You need immediate read-after-write and simple flows |
| **CQRS** | Read and write loads/shapes diverge sharply | Independent optimization/scaling of reads vs writes | Two models to keep in sync; added complexity | Reads and writes are symmetric and modest |
| **Microservices** | Independent deploy/scale/fault-isolation; large org; polyglot | Autonomy, isolation, targeted scaling | Distributed-systems tax: network, partial failure, data consistency, ops overhead | Small team, shared data, tight coupling — you'll get a distributed monolith |
| **Serverless / FaaS** | Spiky/low-baseline workloads, event glue, ops-light | No server mgmt, scale-to-zero, pay-per-use | Cold starts, vendor lock-in, local-dev & long-running limits | Steady high load or latency-critical hot paths |

## Consistency & communication at seams
- **Sync (request/response):** simplest mental model; couples availability (caller down when callee down). Add timeout + retry (idempotent only) + circuit breaker.
- **Async (event/message):** decouples availability and time; buy it with eventual consistency, idempotent consumers, and dead-letter handling.
- **Strong consistency** inside a bounded context; **eventual consistency** across them (with a saga/outbox for cross-context workflows).

## Red flags that you chose wrong
- Two "independent" services always deploy together → merge them.
- Every feature touches 4+ services → boundaries are wrong.
- Synchronous call chains 3+ deep on the hot path → latency/availability will suffer; consider async or co-location.
- Shared database across services → distributed monolith; give each context its own store or make one the clear owner.
