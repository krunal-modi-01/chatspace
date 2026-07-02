---
name: backend
description: Server-side implementation — service/module structure, error handling, idempotency, transactions and units of work, concurrency, and resilience (timeouts, retries, backoff, circuit breakers, bulkheads). Use when implementing or reviewing server-side logic, background jobs, integrations with external services, or anything that writes to a datastore or handles money/state. Used by the backend-engineer agent. Stack-agnostic — detect language/framework from the project.
---
# Backend Skill

## Purpose
Implement server-side logic that is correct under concurrency and partial failure: state changes are atomic and idempotent, external calls are bounded and defensive, and errors are handled deliberately rather than swallowed. Speed matters, but correctness of state is the non-negotiable.

## When invoked
- The **backend-engineer** agent uses this when implementing services, use-cases, background workers, schedulers, or integrations that call other systems.
- Triggered by: "implement the … endpoint/service/job", "call the payment/email/third-party API", "make this operation safe to retry", "why did we double-charge / double-send?", or any write path that touches persistent state.
- Pairs with `api-design` (the contract), `database` (persistence, transactions, migrations), `testing`, and `security`.

## Inputs
- The API/contract or job trigger being implemented (from `api-design` / product spec).
- Data model and transaction boundaries (from `database`).
- Non-functional targets: latency budget, expected concurrency, downstream SLAs.
- Existing conventions: framework, error type hierarchy, logging/tracing setup, config/secrets access.

## Outputs
- Service/use-case code with a clear structure (transport → application/use-case → domain → adapters), thin transport and I/O-isolated core.
- Deliberate error handling: typed/domain errors mapped to transport responses; no silent catches.
- Idempotent write paths where retries are possible (idempotency keys, natural keys, or dedup).
- Correct transaction scoping and concurrency control.
- Resilient outbound calls: timeouts, bounded retries with backoff+jitter, circuit breakers where warranted.
- Structured logs, metrics, and trace spans at the meaningful boundaries.

## Procedure
1. **Locate the layer.** Keep transport (HTTP/gRPC/queue handler) thin: parse, authenticate/authorize, validate, then delegate to a use-case function that knows nothing about the transport. Put business rules in the domain/application layer; put I/O behind adapters (repositories, clients). This is what makes logic testable without a network.
2. **Validate at the boundary.** Reject malformed or unauthorized input before any work. Validate types, ranges, and invariants; convert to internal domain types once, so the core trusts its inputs.
3. **Define the transaction boundary explicitly.** One use-case = one unit of work where possible. Decide what must be atomic. Do **not** perform external network calls inside a DB transaction — the transaction holds locks while you wait on a flaky network. Use the **transactional outbox** pattern to publish events/side-effects reliably after commit.
4. **Make writes idempotent.** Any operation a client or queue may retry must be safe to run twice. Use an **idempotency key** (client-supplied or derived) stored with the result, a natural unique key, or an upsert. For money and messaging this is mandatory, not optional. Return the original result on a duplicate rather than re-doing the work.
5. **Choose concurrency control.** For contended updates use **optimistic concurrency** (version column / compare-and-set) and retry on conflict, or **pessimistic locking** (`SELECT ... FOR UPDATE`) for short critical sections. Never read-modify-write without one of these. Guard shared in-process state; prefer immutable data and message passing over shared mutable state.
6. **Bound every outbound call.** No call to another service leaves without a **timeout** (connect + read). Set it from the latency budget, not a vague default. A hung dependency must not hang your request.
7. **Retry only what's safe.** Retry on transient failures (timeout, 5xx, connection reset) — never on 4xx or non-idempotent operations without an idempotency key. Use **exponential backoff with jitter** and a small cap. Retrying a non-idempotent write is how you double-charge.
8. **Add a circuit breaker** around dependencies that can fail en masse: after N consecutive failures, fail fast (open) for a cooldown, then probe (half-open). This prevents cascading failure and gives the dependency room to recover. Isolate resources with **bulkheads** (separate pools/limits) so one slow dependency can't exhaust all threads/connections.
9. **Handle errors deliberately.** Distinguish expected domain errors (validation, not-found, conflict) from unexpected faults. Map each to the right transport status/response. Never swallow an exception to make it "work"; never log-and-continue on a corrupted state change. Include enough context (ids, operation) without leaking secrets or PII.
10. **Design for graceful degradation & shutdown.** On dependency failure, degrade (cached/partial response, queue-for-later) where the product allows, rather than hard-failing. Handle SIGTERM: stop accepting new work, drain in-flight, close connections.
11. **Instrument the boundaries.** Emit a structured log with correlation/trace id, a latency metric, and a trace span at each significant seam (inbound handler, DB call, outbound call). You cannot debug in production what you didn't instrument.
12. **Test the failure paths.** Unit-test the domain core with fakes; integration-test the real transaction and idempotency behavior; test timeout/retry/circuit-breaker with a fault-injecting stub. Hand to `testing` for coverage strategy.

## Best practices
- Push I/O to the edges; keep the domain pure and synchronous-looking so it's trivially testable.
- Make illegal states unrepresentable — use types/enums/value objects instead of stringly-typed flags.
- Prefer idempotent-by-design endpoints (PUT/upsert with a key) over "retry-safe if you're careful".
- Set timeouts and pool sizes from the latency/concurrency budget, and load-test to confirm.
- Keep configuration and secrets out of code; read them once at startup and fail fast if missing.
- Log intent and outcome at boundaries; use structured fields, not string concatenation.

## Anti-patterns
- **Network calls inside a database transaction** — holds locks across an unbounded wait.
- **Unbounded retries or retries without backoff** — turns a blip into a self-inflicted DDoS (retry storm).
- **Retrying non-idempotent writes** — the classic double-charge / double-send.
- **Swallowed exceptions** (`catch {}`) and log-and-continue on state corruption.
- **Read-modify-write with no version check or lock** — lost updates under concurrency.
- **Fat controllers / anemic everything-in-the-handler** — untestable, un-reusable logic welded to the transport.
- **No timeout on outbound calls** — one hung dependency exhausts the pool and takes the service down.
- **Fire-and-forget side effects with no outbox** — events silently lost on crash between commit and publish.
