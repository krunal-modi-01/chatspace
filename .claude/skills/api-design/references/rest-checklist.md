# REST API Review Checklist

Pre-merge checklist for the `api-design` skill. Every box should be a deliberate "yes" or a documented exception.

## Resource modeling & naming
- [ ] URLs are nouns, plural for collections (`/orders`, `/orders/{id}`), hierarchy reflects containment.
- [ ] No RPC verbs in paths (`/getOrder`, `/doThing`) — use HTTP methods.
- [ ] Casing/naming is consistent with the rest of the API.
- [ ] Identifiers are stable and opaque to the client where possible (no leaking DB internals).

## HTTP methods
- [ ] GET is safe and side-effect free; cacheable where appropriate.
- [ ] POST for create/non-idempotent action; PUT for full idempotent replace; PATCH for partial; DELETE idempotent.
- [ ] Method matches semantics — no state change on GET.

## Status codes
- [ ] 201 + `Location` on resource creation; 202 for accepted-async; 204 for empty success.
- [ ] 400 malformed vs 422 semantically-invalid; 401 vs 403 correct; 404 vs 409 correct; 429 for rate limit.
- [ ] No 200-with-error-body. 5xx only for genuine server faults.

## Idempotency & concurrency
- [ ] Retriable creates/charges accept an `Idempotency-Key`; duplicates return the original result.
- [ ] Conditional updates supported (`ETag` / `If-Match`) or version field to prevent lost updates → 412/409 on conflict.

## Pagination, filtering, sorting
- [ ] Every collection is paginated (no unbounded lists).
- [ ] Cursor/keyset pagination for large or changing sets; offset only for small stable data.
- [ ] Filter/sort fields are whitelisted and documented; sensible defaults and max page size.
- [ ] List response envelope is consistent (data + pagination meta).

## Errors
- [ ] Single error envelope everywhere: stable machine `code`, human `message`, optional field details, correlation id.
- [ ] No stack traces / SQL / internal paths leaked.

## Versioning & backward compatibility
- [ ] Change is additive (new optional field/endpoint) — or explicitly versioned if breaking.
- [ ] Breaking check: no field removed/renamed, no type change, no tightened validation, no default/semantic change without a new version.
- [ ] Deprecations announced with `Deprecation`/`Sunset` and a timeline; old version runs in parallel.

## Security & limits
- [ ] Auth requirement and required scopes/permissions documented per operation.
- [ ] Rate limits and `Retry-After`/`RateLimit-*` headers defined.
- [ ] Input validated/bounded; no mass-assignment; PII minimized in responses. (Route through `security`.)

## Spec & tests
- [ ] Machine-readable spec (OpenAPI) is the source of truth and updated.
- [ ] Examples for non-obvious requests and each error case.
- [ ] Every write endpoint (`POST`/`PUT`/`PATCH`) with a body shows that body's **schema + example in the generated spec** — check the generated spec, not just the handler. If the handler validates the body manually (bypassing typed-body binding to control `400`-vs-`422`), attach the schema explicitly (FastAPI: `openapi_extra=` from the same model) — otherwise the spec shows an empty/untyped body while validation silently happens.
- [ ] Contract tests cover the new/changed behavior.
