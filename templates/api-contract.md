# API Contract — <Resource / Service>

> Owner: `api-reviewer` (+ `backend-engineer`). Guarded by `api-change-guard` hook. Source of truth: the OpenAPI/proto/GraphQL file; this doc is the human-readable companion.

## Overview
Purpose, style (REST / GraphQL / gRPC), base path, version (`v1`).

## Conventions
- **Versioning:** URI (`/v1`) or header; breaking changes bump version.
- **Auth:** scheme (e.g., Bearer JWT / mTLS), required scopes.
- **Errors:** consistent envelope `{ "error": { "code", "message", "details" } }`; correct HTTP status.
- **Pagination:** cursor-based (`limit` + `cursor`).
- **Idempotency:** mutating endpoints accept `Idempotency-Key`.
- **Rate limits:** documented per client.

## Endpoints
### `POST /v1/<resource>`
- **Purpose:** …
- **Auth / scope:** …
- **Idempotent:** yes (Idempotency-Key)
- **Request:**
```json
{ "field": "…" }
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 201 | Created | resource |
  | 400 | Validation error | error envelope |
  | 401/403 | Auth | error envelope |
  | 409 | Conflict / duplicate | error envelope |
  | 429 | Rate limited | error envelope |

(repeat per endpoint)

## Backward-compatibility checklist
- [ ] No field removed/renamed without a version bump.
- [ ] New fields optional with safe defaults.
- [ ] Enum additions tolerated by clients.
- [ ] Consumers notified; clients regenerated.
