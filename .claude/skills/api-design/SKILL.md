---
name: api-design
description: Designing and reviewing API contracts — REST, GraphQL, and gRPC. Covers resource modeling, naming, versioning, status codes, pagination, filtering, idempotency, error formats, and backward-compatible evolution. Use when designing a new endpoint/service contract, reviewing an API for consistency and compatibility, choosing REST vs GraphQL vs gRPC, or changing an existing contract that clients depend on. Used by the api-reviewer and backend-engineer agents. Stack-agnostic.
---
# API Design Skill

## Purpose
Produce API contracts that are predictable, evolvable, and hard to misuse: consistent naming and semantics, correct status/error signaling, safe pagination and idempotency, and a versioning/compatibility discipline that lets the API change without breaking existing clients. The contract is a long-lived promise — design it as one.

## When invoked
- The **api-reviewer** agent uses this to review proposed or changed contracts; the **backend-engineer** agent uses it when defining a new endpoint before implementing it.
- Triggered by: "design the API for…", "REST or GraphQL or gRPC?", "review this endpoint/schema", "how do we paginate/version/return errors?", "is this change backward-compatible?".
- Precedes `backend` (implementation) and feeds `documentation-writer` (published spec).

## Inputs
- The capability/use-cases the API must serve and its consumers (internal, partner, public) and their tolerance for change.
- Existing API conventions/style guide in the org (naming, error envelope, versioning scheme).
- Non-functional needs: latency, payload size, over-/under-fetching pressure, streaming, mobile/bandwidth constraints.
- Data model and invariants (from `database`/`architecture`).

## Outputs
- A contract: resources/operations, request/response schemas, status codes, error format, pagination, and auth requirements — ideally as a machine-readable spec (OpenAPI / GraphQL SDL / protobuf).
- A versioning and compatibility plan (what's stable, how it evolves, deprecation policy).
- A review verdict (for api-reviewer): consistent? compatible? correctly signaled? with concrete issues.

## Procedure
1. **Choose the style from the shape of the problem, not habit.** **REST** for resource-oriented CRUD and broad interoperability/caching. **GraphQL** when clients have widely varying data needs and over-/under-fetching hurts (typically aggregating many sources for varied UIs). **gRPC** for low-latency, high-throughput internal service-to-service and streaming. Mixing per boundary is fine.
2. **Model resources around nouns and stable identity** (REST) or a well-typed graph (GraphQL) / service methods (gRPC). Identify the resources, their identifiers, their relationships, and the operations. Avoid RPC-style verbs bolted onto REST URLs (`/getUser`, `/doThing`) — use HTTP methods on nouns.
3. **Apply consistent naming.** Pick a convention and hold it everywhere: plural nouns for collections (`/orders`, `/orders/{id}/items`), hierarchy reflects containment, consistent casing (kebab in paths, the org's convention in fields). Names are part of the contract — renaming later is a breaking change.
4. **Use HTTP methods and status codes precisely.** GET (safe, cacheable, no side effects), POST (create / non-idempotent action), PUT (full replace, idempotent), PATCH (partial update), DELETE (idempotent). Return the right class: 2xx success (201 + `Location` on create, 202 for async accepted, 204 for empty), 4xx client error (400 validation, 401 unauthenticated, 403 unauthorized, 404, 409 conflict, 422 semantic, 429 rate-limited), 5xx server fault. Don't return 200 with an error body. See `references/rest-checklist.md`.
5. **Design idempotency in.** GET/PUT/DELETE are idempotent by definition — honor that. For POST that creates or charges, support an **`Idempotency-Key`** header so a retried request returns the original result instead of duplicating. State idempotency guarantees in the contract.
6. **Paginate every unbounded collection** from day one. Prefer **cursor/keyset** pagination for large or frequently-changing sets (stable, no skipped/duplicated rows); offset/limit only for small, stable data. Return a `next` cursor and never an unbounded list. Provide filtering/sorting with documented, whitelisted fields.
7. **Standardize the error format.** One error envelope across the whole API: a stable machine-readable `code`, a human `message`, optionally `details`/field-level errors, and a correlation/trace id. Follow a known shape (e.g. RFC 9457 Problem Details) if you have no house style. Never leak stack traces, SQL, or internal paths.
8. **Version deliberately and evolve compatibly.** Prefer additive, backward-compatible change over new versions. **Backward-compatible (safe):** add optional fields, add endpoints, add enum values *only if clients tolerate unknowns*, relax constraints. **Breaking (needs a version / migration):** remove or rename fields, change types, tighten validation, change status/error semantics, change defaults. When you must break, version explicitly (URL `/v2` or media-type), run old and new in parallel, and publish a deprecation timeline with `Deprecation`/`Sunset` signaling.
9. **Specify auth, rate limits, and content negotiation** in the contract: how the client authenticates, required scopes/permissions per operation, rate-limit headers (`RateLimit-*`, `Retry-After`), and supported media types. Security review via the `security` skill.
10. **Write the spec down, machine-readable.** OpenAPI/SDL/protobuf as the source of truth; generate docs and, where possible, clients/servers from it. Add examples for the non-obvious requests and every error case. Contract-test against it (see `testing`).

## Best practices
- Design for the client's failure handling: predictable status codes and a single stable error shape beat clever HTTP gymnastics.
- Additive-only evolution wherever possible; treat any rename/removal as a breaking change requiring a version.
- Return created/updated representations (or a `Location`) so clients don't need a follow-up GET.
- Make list responses envelope-consistent (data + pagination + meta), not sometimes-array/sometimes-object.
- Document idempotency, pagination, and rate limits explicitly — undocumented behavior becomes an accidental contract.
- Keep GraphQL schemas nullable-by-intent and paginated (connections); keep gRPC messages evolvable (don't reuse field numbers).

## Anti-patterns
- **RPC verbs in REST URLs** (`/createOrder`, `/user/delete`) and ignoring HTTP methods.
- **200-with-error-body** and inconsistent/ad-hoc error shapes across endpoints.
- **Unbounded list endpoints** with no pagination — a latency and memory time-bomb.
- **Offset pagination over large, changing data** — skipped and duplicated rows.
- **Breaking changes shipped silently** — renaming/removing fields, tightening validation, or changing defaults without a version or deprecation window.
- **Leaking internals** — stack traces, DB errors, or internal ids/enums in responses.
- **Chatty designs** forcing N+1 client round-trips (or the GraphQL server-side N+1 without batching/dataloader).

## Files included
- `references/rest-checklist.md` — a concrete pre-merge checklist for REST endpoints and compatibility.
