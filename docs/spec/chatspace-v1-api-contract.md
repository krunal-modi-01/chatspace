# API Contract — chatspace v1

> Owner: `api-reviewer` (+ `backend-engineer`). Guarded by `api-change-guard` hook. Source of truth: the OpenAPI/proto/GraphQL file; this doc is the human-readable companion.

**Status: Draft** · Version: `1.0.0` · Base path: `/v1` · Traces to: [`chatspace-v1-functional-spec.md`](chatspace-v1-functional-spec.md) (F1–F70), [`chatspace-v1-technical-spec.md`](chatspace-v1-technical-spec.md) §5 · ADRs: [0002](../../architecture/adr/0002-dm-data-model.md) · [0003](../../architecture/adr/0003-cursor-pagination.md) · [0004](../../architecture/adr/0004-realtime-delivery-fanout.md) · [0005](../../architecture/adr/0005-message-id-scheme.md) · [0006](../../architecture/adr/0006-revocable-sessions.md) · [0007](../../architecture/adr/0007-media-object-storage.md)

## Overview

This contract defines the complete v1 surface for **chatspace**, a single-workspace, self-hostable Slack-style team chat.

- **Purpose:** the promise made to every current and future consumer (React SPA today; future clients) of the chatspace backend. It covers authentication & sessions, invites, profile, channels & membership, channel messages, 1:1 DMs, media, workspace admin, and the real-time WebSocket surface.
- **Style:** hybrid — **REST (JSON)** for all CRUD, history, auth, invites, admin, and media control-plane; **WebSocket (WSS)** for real-time only (new message / edit / delete, typing, presence). This split is mandated by `CLAUDE.md` conventions and TSD §5.
- **Base path:** all REST routes are under `/v1`; the WebSocket endpoint is `/v1/ws`.
- **Version:** `1.0.0`. The URI major version (`/v1`) is the compatibility boundary.

All request/response bodies use **snake_case** JSON (matches Python/Pydantic). All timestamps are **ISO-8601 UTC** (e.g. `2026-07-02T14:31:07.482Z`); clients render local/relative time. Password hashes, JWT signing material, refresh-token internals, invite tokens, and reset tokens are **never** returned in list/read responses and **never** logged.

## Conventions

- **Versioning:** URI major version `/v1`. Additive, backward-compatible changes (new endpoints, new optional fields, new enum values, new WS event types) ship within `/v1`. Any breaking change (removing/renaming a field, tightening a type/validation, changing a default, changing a status/close-code meaning) requires a new major version (`/v2`) **and** a human API-owner sign-off plus an announced deprecation window — see the backward-compatibility checklist. Enum-typed fields (`role`, `is_private`, media `kind`, WS `type`) are documented as open sets; clients MUST tolerate unknown values.
- **Auth:** `Authorization: Bearer <access_token>` (short-lived 15-min signed JWT with `sub`=user_id and `sid`=session_id, ADR-0006) on every protected route. The public (no-auth) routes are: `POST /v1/auth/register`, `POST /v1/auth/login`, `POST /v1/auth/refresh`, `POST /v1/auth/password-reset`, `POST /v1/auth/password-reset/confirm`, and `GET /v1/invites/{token}`. Every authenticated REST request re-runs the session-revocation check (Redis-cached, Postgres-backed): a logged-out, password-changed, reset, or deactivated `sid` fails with `401` near-immediately. Workspace-level authorization has two roles — `system_admin` (invite + deactivate/reactivate powers only; **no** channel/message access) and `user`. Per-channel authorization is the `member`/`admin` role on `ChannelMember`; DM authorization is a participant check (requester is `sender_id` or `recipient_id`, ADR-0002). Membership/participant checks are enforced **server-side on every message read/write and every media fetch** — a client-supplied `channel_id`/`user_id` is never trusted alone (F34, F59).
- **Errors:** RFC 7807 `application/problem+json` (F70, TSD §5). This supersedes the template's generic `{ "error": {...} }` envelope. Every error body has the shape:
  ```json
  {
    "type": "https://chatspace.example/problems/<slug>",
    "title": "Human-readable summary of the problem class",
    "status": 422,
    "detail": "Specific, non-sensitive explanation for this occurrence",
    "instance": "/v1/channels/{channel_id}/messages",
    "correlation_id": "01J...",
    "errors": [ { "field": "content", "detail": "must not be empty" } ]
  }
  ```
  `type`, `title`, `status`, `detail`, `instance`, and `correlation_id` are always present; `errors` (a field-level list) appears only on `400`/`422` validation failures. `correlation_id` is the non-PII request id also emitted on every log line (F68). Error bodies never contain message content, PII, tokens, or secrets. Non-enumerating endpoints (auth, password-reset, invite redemption) return a uniform response regardless of whether the identifier exists (F11, F15, F64). Below, "**problem+json**" in a Body column means a body of this shape.
- **Pagination:** two documented styles.
  - **Cursor (keyset)** for message and DM history (ADR-0003): query `?limit=&cursor=`; response `{ "items": [...], "next_cursor": "<opaque|null>" }`. The cursor is an **opaque base64url token** over `(created_at, id)`; clients MUST treat it as opaque and never construct it. `next_cursor` is `null` at the end of the stream. `items.length <= limit` is expected — soft-deleted rows are excluded by the query predicate (F44), so a page can be shorter than `limit` without meaning end-of-stream. Default `limit` 50, server maximum `limit` 100 (a larger request is clamped to 100). Reconnect catch-up (F55) reuses the same endpoint with `cursor` set from the last received message id.
  - **Offset** for the public-channel browse list only (F30, §5a): query `?limit=&offset=`; response `{ "items": [...], "total": <int>, "limit": <int>, "offset": <int> }`. Page size default and maximum are **50**.
- **Idempotency:** message-create (`POST /v1/channels/{channel_id}/messages` and `POST /v1/dms/{user_id}/messages`) accepts an `Idempotency-Key` header (client-generated UUID; F40, ADR-0004). The first request with a given `(sender_id, key)` creates exactly one row and returns `201`; any replay of the same key returns the original message with `200` and creates no duplicate. A malformed/absent key on message-create is rejected with `400` (the key is required so retried sends are always safe under at-least-once delivery). GET/DELETE/PATCH are idempotent by HTTP semantics and do not take the header.
- **Rate limits:** Redis token-bucket (F63, F64, F62). Message send: **10 / 10 s per user, burst 20**. Auth endpoints (login, register, refresh, password-reset request): **5 / 5 min per IP + attempted identifier**, keyed so it never reveals whether the identifier exists. Media upload: **20 / min per user**. Over-limit responses are `429 Too Many Requests` with a `Retry-After` header (seconds) and a problem+json body. Limits are documented per client and enforced server-side.

## Endpoints

### `POST /v1/auth/register`
- **Purpose:** Redeem a valid invite token and create the invited user (F5, F6). Email is locked to the invited address and auto-verified; no invite-less path exists.
- **Auth / scope:** Public. Requires a `pending`, unexpired invite `token`. Rate-limited as an auth endpoint.
- **Idempotent:** No (single-use — the token transitions to `used`).
- **Request:**
```json
{
  "invite_token": "<invite_token>",
  "username": "alice",
  "first_name": "Alice",
  "last_name": "Ng",
  "password": "<password>",
  "avatar_url": null
}
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 201 | User created; invite marked `used` | `user` object (id, username, email, first_name, last_name, avatar_url, role, created_at) — never a password hash |
  | 400 | Malformed body | problem+json |
  | 409 | Username or email already registered | problem+json |
  | 410 | Invite token expired / used / revoked (F7) | problem+json |
  | 422 | Password fails policy, or field validation | problem+json |
  | 429 | Rate limited | problem+json + `Retry-After` |

### `POST /v1/auth/login`
- **Purpose:** Authenticate email + password; issue a 15-min access token and a 30-day sliding refresh token, establishing a revocable session (F10, ADR-0006).
- **Auth / scope:** Public. Rate-limited as an auth endpoint.
- **Idempotent:** No (each call mints a new session).
- **Request:**
```json
{ "email": "alice@co.com", "password": "<password>" }
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 200 | Authenticated | `{ access_token, token_type: "Bearer", expires_in: 900, refresh_token, user }` (token values are opaque secrets; never logged) |
  | 400 | Malformed body | problem+json |
  | 401 | Invalid credentials — no field-level disclosure (F11) | problem+json (uniform) |
  | 403 | Account deactivated — clear "account deactivated" title (F11) | problem+json |
  | 429 | Rate limited | problem+json + `Retry-After` |

### `POST /v1/auth/refresh`
- **Purpose:** Exchange a valid refresh token for a new access token, sliding the session expiry (F12).
- **Auth / scope:** Public (the refresh token itself is the credential). Rate-limited as an auth endpoint.
- **Idempotent:** No (issues a fresh access token; refresh token may be rotated).
- **Request:**
```json
{ "refresh_token": "<refresh_token>" }
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 200 | New access token issued | `{ access_token, token_type: "Bearer", expires_in: 900, refresh_token }` |
  | 400 | Malformed body | problem+json |
  | 401 | Refresh token invalid / revoked / expired (F12) | problem+json |
  | 429 | Rate limited | problem+json + `Retry-After` |

### `POST /v1/auth/logout`
- **Purpose:** Revoke the **current** session; its access + refresh tokens can no longer authenticate. Other sessions are unaffected (F14).
- **Auth / scope:** Bearer; any authenticated user. Acts on the session in the token's `sid`.
- **Idempotent:** Yes (revoking an already-revoked session is a no-op → `204`).
- **Request:**
```json
{}
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 204 | Current session revoked | (empty) |
  | 401 | Missing/invalid/expired access token | problem+json |

### `GET /v1/auth/sessions`
- **Purpose:** List the caller's own active sessions for a "manage devices" view (ADR-0006 foundation).
- **Auth / scope:** Bearer; any authenticated user. Returns only the caller's sessions.
- **Idempotent:** Yes (safe read).
- **Request:** _(none; `GET`)_
```json
{}
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 200 | Session list | `{ items: [ { session_id, created_at, last_seen_at, device_label, current: bool } ] }` — never any token material |
  | 401 | Auth | problem+json |

### `DELETE /v1/auth/sessions/{session_id}`
- **Purpose:** Revoke one of the caller's own sessions by id (remote logout of another device).
- **Auth / scope:** Bearer; caller may revoke only their own sessions.
- **Idempotent:** Yes (revoking an already-revoked/absent session → `204`/`404` deterministically).
- **Request:** _(none; `DELETE`)_
```json
{}
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 204 | Session revoked | (empty) |
  | 401 | Auth | problem+json |
  | 403 | `session_id` belongs to another user | problem+json |
  | 404 | No such session for this user | problem+json |

### `POST /v1/auth/password/change`
- **Purpose:** Change password by confirming the current one; sets a policy-compliant new password and invalidates all of the caller's **other** sessions, keeping the initiating session alive (F22).
- **Auth / scope:** Bearer; any authenticated user.
- **Idempotent:** No (rotates password + revokes other sessions).
- **Request:**
```json
{ "current_password": "<current_password>", "new_password": "<new_password>" }
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 204 | Password changed; other sessions invalidated | (empty) |
  | 400 | Malformed body | problem+json |
  | 401 | Access token invalid, or current password incorrect (F22) | problem+json |
  | 422 | New password fails policy (F23) | problem+json |

### `POST /v1/auth/password-reset`
- **Purpose:** Request a password reset for an email; if it exists, email a single-use 1-hour token and invalidate any earlier reset token. Response is uniform regardless of existence — non-enumerating (F15, F17).
- **Auth / scope:** Public. Rate-limited as an auth endpoint.
- **Idempotent:** Effectively yes at the contract boundary — every call returns the same `202`; server-side only the latest issued token is valid (F17).
- **Request:**
```json
{ "email": "alice@co.com" }
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 202 | Uniform accepted response (identical whether or not the email exists) | `{ "message": "If an account exists for that email, a reset link has been sent." }` |
  | 400 | Malformed body | problem+json |
  | 429 | Rate limited (still non-enumerating) | problem+json + `Retry-After` |

### `POST /v1/auth/password-reset/confirm`
- **Purpose:** Set a new password using a valid, unused, unexpired reset token; invalidate all of the user's other active sessions (F16).
- **Auth / scope:** Public (the reset token is the credential).
- **Idempotent:** No (single-use token → `used`).
- **Request:**
```json
{ "reset_token": "<reset_token>", "new_password": "<new_password>" }
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 204 | Password set; user's other sessions invalidated | (empty) |
  | 400 | Malformed body | problem+json |
  | 410 | Reset token expired / already used / superseded (F17) | problem+json |
  | 422 | New password fails policy (F23) | problem+json |

### `POST /v1/invites`
- **Purpose:** System Admin issues a single-use, 7-day invite for a specific email; an invite email is dispatched (F1). Fails loudly if email delivery is unreachable.
- **Auth / scope:** Bearer; **`system_admin`** only.
- **Idempotent:** No (each call mints a distinct token; use resend to rotate).
- **Request:**
```json
{ "email": "bob@co.com" }
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 201 | Invite created and emailed | `{ id, email, status: "pending", expiry, issued_by, created_at }` — the raw token is **never** returned |
  | 400 | Malformed body | problem+json |
  | 401 | Auth | problem+json |
  | 403 | Caller is not a System Admin | problem+json |
  | 409 | Email is already a registered user (Flow A.1b) | problem+json |
  | 422 | Invalid email | problem+json |
  | 502 | Email delivery unreachable — fail loudly (F1, Flow A.1c) | problem+json |

### `GET /v1/invites/{token}`
- **Purpose:** Validate an invite token and return the locked email so the registration form can pre-fill (F4). Does not consume the token.
- **Auth / scope:** Public (the token is the credential).
- **Idempotent:** Yes (safe read; token stays `pending`).
- **Request:** _(none; `GET`)_
```json
{}
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 200 | Token valid | `{ email, expiry }` (email locked to this address) |
  | 410 | Token expired / used / revoked (F7) | problem+json |

### `POST /v1/invites/{id}/resend`
- **Purpose:** System Admin resends an invite, issuing a new token and invalidating the prior one (F3).
- **Auth / scope:** Bearer; **`system_admin`** only.
- **Idempotent:** No (mints a new token each call).
- **Request:**
```json
{}
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 200 | New token issued and emailed; prior token invalidated | `{ id, email, status: "pending", expiry }` |
  | 401 | Auth | problem+json |
  | 403 | Not a System Admin | problem+json |
  | 404 | No such invite | problem+json |
  | 409 | Invite is not in a resendable (`pending`) state | problem+json |
  | 502 | Email delivery unreachable | problem+json |

### `DELETE /v1/invites/{id}`
- **Purpose:** System Admin revokes an unused invite; its token can no longer redeem (F2).
- **Auth / scope:** Bearer; **`system_admin`** only.
- **Idempotent:** Yes (revoking an already-revoked invite → `204`).
- **Request:** _(none; `DELETE`)_
```json
{}
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 204 | Invite revoked | (empty) |
  | 401 | Auth | problem+json |
  | 403 | Not a System Admin | problem+json |
  | 404 | No such invite | problem+json |
  | 409 | Invite already `used` (cannot revoke a redeemed invite) | problem+json |

### `GET /v1/me`
- **Purpose:** Return the authenticated user's own profile (F18).
- **Auth / scope:** Bearer; any authenticated user.
- **Idempotent:** Yes (safe read).
- **Request:** _(none; `GET`)_
```json
{}
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 200 | Profile | `{ id, username, email, first_name, last_name, avatar_url, role, is_active, last_seen, created_at }` — password never included |
  | 401 | Auth | problem+json |

### `PATCH /v1/me`
- **Purpose:** Update the caller's own `first_name`, `last_name`, and/or `avatar_url`. `email` and `username` are immutable (F19, F20).
- **Auth / scope:** Bearer; any authenticated user (self only).
- **Idempotent:** Yes (same body yields the same resulting state).
- **Request:**
```json
{ "first_name": "Alice", "last_name": "Ng", "avatar_url": "https://cdn.example/av/opaque-key" }
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 200 | Profile updated | updated `user` object |
  | 400 | Malformed body, or attempt to change `email`/`username` (immutable, F20) | problem+json |
  | 401 | Auth | problem+json |
  | 422 | Field validation (e.g. empty name) | problem+json |

### `POST /v1/channels`
- **Purpose:** Any active user creates a public or private channel and is recorded as its first `admin` (F29).
- **Auth / scope:** Bearer; any active user (no System-Admin gate).
- **Idempotent:** No (each call creates a new channel; name uniqueness is enforced separately).
- **Request:**
```json
{ "name": "engineering", "is_private": false }
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 201 | Channel created; creator is admin | `{ id, name, is_private, created_by, created_at, member_count }` |
  | 400 | Malformed body | problem+json |
  | 401 | Auth | problem+json |
  | 409 | Channel name already exists in workspace (Flow E.1a) | problem+json |
  | 422 | Name invalid (length 1–80, allowed charset) | problem+json |

### `GET /v1/channels/public`
- **Purpose:** Offset-paginated browse of public channels the caller is **not** yet a member of, for direct join (F30). Page size 50.
- **Auth / scope:** Bearer; any active user.
- **Idempotent:** Yes (safe read).
- **Request:** _(query: `?limit=50&offset=0`)_
```json
{}
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 200 | Public-channel page | `{ items: [ { id, name, is_private: false, member_count } ], total, limit, offset }` |
  | 400 | Invalid pagination params | problem+json |
  | 401 | Auth | problem+json |

### `GET /v1/channels/{channel_id}`
- **Purpose:** Retrieve a single channel's metadata.
- **Auth / scope:** Bearer. A member may read any channel; for a **private** channel a non-member receives `404` (non-enumerating — does not disclose existence).
- **Idempotent:** Yes (safe read).
- **Request:** _(none; `GET`)_
```json
{}
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 200 | Channel | `{ id, name, is_private, created_by, created_at, member_count, my_role }` |
  | 401 | Auth | problem+json |
  | 404 | Not found, or private channel the caller cannot see (uniform) | problem+json |

### `POST /v1/channels/{channel_id}/join`
- **Purpose:** Join a **public** channel directly, becoming a `member` (F31).
- **Auth / scope:** Bearer; any active user. Private channels are join-by-admin only (see membership endpoints).
- **Idempotent:** Yes (already a member → `200` with current membership, no duplicate row).
- **Request:**
```json
{}
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 200 | Joined (or already a member) | `{ channel_id, user_id, role: "member", joined_at }` |
  | 401 | Auth | problem+json |
  | 403 | Channel is private — direct join not allowed (F32) | problem+json |
  | 404 | No such public channel (uniform for private) | problem+json |

### `POST /v1/channels/{channel_id}/leave`
- **Purpose:** Leave a channel the caller belongs to. If the caller is the sole admin and other members remain, the earliest-`joined_at` member is promoted to admin **before** removal (F35, F36); if none remain, the channel persists with zero admins (F37).
- **Auth / scope:** Bearer; caller must be a member.
- **Idempotent:** Yes (not a member → `204`; succession runs at most once).
- **Request:**
```json
{}
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 204 | Left; succession applied if caller was sole admin | (empty) |
  | 401 | Auth | problem+json |
  | 404 | Not a member / no such channel (uniform) | problem+json |

### `GET /v1/channels/{channel_id}/members`
- **Purpose:** List a channel's members and their per-channel roles.
- **Auth / scope:** Bearer; caller must be a member of the channel (server-side check, F34).
- **Idempotent:** Yes (safe read).
- **Request:** _(query: optional `?limit=&offset=`)_
```json
{}
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 200 | Member list | `{ items: [ { user_id, username, first_name, last_name, avatar_url, role, joined_at } ], total }` |
  | 401 | Auth | problem+json |
  | 403 | Caller is not a member | problem+json |
  | 404 | No such channel (uniform) | problem+json |

### `POST /v1/channels/{channel_id}/members`
- **Purpose:** A Channel Admin adds a user to the channel (the only way into a private channel; F32, F33).
- **Auth / scope:** Bearer; caller must be an `admin` of this channel and the channel must currently have ≥1 admin (F33).
- **Idempotent:** Yes (already a member → `200`, no duplicate).
- **Request:**
```json
{ "user_id": "01J...", "role": "member" }
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 200 | Member added (or already present) | `{ channel_id, user_id, role, joined_at }` |
  | 400 | Malformed body | problem+json |
  | 401 | Auth | problem+json |
  | 403 | Caller is not a channel admin (F32) | problem+json |
  | 404 | No such channel or target user | problem+json |
  | 409 | Channel is in a zero-admin frozen state — mutations blocked (F37) | problem+json |
  | 422 | Invalid `role` | problem+json |

### `PATCH /v1/channels/{channel_id}/members/{user_id}`
- **Purpose:** A Channel Admin changes a member's per-channel role (`member` ↔ `admin`) (F33).
- **Auth / scope:** Bearer; caller must be an `admin` of this channel.
- **Idempotent:** Yes (setting the role that is already set is a no-op → `200`).
- **Request:**
```json
{ "role": "admin" }
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 200 | Role updated | `{ channel_id, user_id, role, joined_at }` |
  | 400 | Malformed body | problem+json |
  | 401 | Auth | problem+json |
  | 403 | Caller is not a channel admin | problem+json |
  | 404 | No such channel or member | problem+json |
  | 409 | Zero-admin frozen channel — mutations blocked (F37) | problem+json |
  | 422 | Invalid `role` | problem+json |

### `DELETE /v1/channels/{channel_id}/members/{user_id}`
- **Purpose:** A Channel Admin removes a member from the channel (F33). Removing the sole admin triggers succession per F36.
- **Auth / scope:** Bearer; caller must be an `admin` of this channel.
- **Idempotent:** Yes (target not a member → `204`).
- **Request:** _(none; `DELETE`)_
```json
{}
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 204 | Member removed (succession applied if needed) | (empty) |
  | 401 | Auth | problem+json |
  | 403 | Caller is not a channel admin | problem+json |
  | 404 | No such channel or member | problem+json |
  | 409 | Zero-admin frozen channel — mutations blocked (F37) | problem+json |

### `POST /v1/channels/{channel_id}/messages`
- **Purpose:** Send a text message (optionally with media) to a channel; persisted with a server-generated UUIDv7 id and authoritative `created_at`, then published live (F38, F41, F45, F51).
- **Auth / scope:** Bearer; caller must be a member (server-side membership check, F34).
- **Idempotent:** **Yes — required** `Idempotency-Key` header (F40). Repeated key returns the original message, exactly one row.
- **Request:** _(header: `Idempotency-Key: <uuid>`)_
```json
{ "content": "shipping the release now 🚀", "media_ids": ["01J..."] }
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 201 | Message created | `message` object (id [UUIDv7], channel_id, sender_id, content, media, created_at, edited_at: null, deleted_at: null) |
  | 200 | Idempotent replay — original message returned, no new row (F40) | `message` object |
  | 400 | Malformed body or missing/invalid `Idempotency-Key` | problem+json |
  | 401 | Auth | problem+json |
  | 403 | Not a channel member (F34) | problem+json |
  | 404 | No such channel (uniform) | problem+json |
  | 422 | Body null/whitespace or > 4000 chars, or unknown `media_id` (F39) | problem+json |
  | 429 | Over send rate limit (10/10 s, burst 20) | problem+json + `Retry-After` |

### `GET /v1/channels/{channel_id}/messages`
- **Purpose:** Cursor-paginated channel history in chronological order, excluding soft-deleted messages (F44). Also serves reconnect catch-up (F55) via `cursor`.
- **Auth / scope:** Bearer; caller must be a member (F34).
- **Idempotent:** Yes (safe read).
- **Request:** _(query: `?limit=50&cursor=<opaque|null>`)_
```json
{}
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 200 | History page | `{ items: [ message... ], next_cursor }` (soft-deleted excluded; `items.length <= limit`) |
  | 400 | Invalid `limit`/`cursor` | problem+json |
  | 401 | Auth | problem+json |
  | 403 | Not a channel member (F34) | problem+json |
  | 404 | No such channel (uniform) | problem+json |

### `PATCH /v1/messages/{message_id}`
- **Purpose:** Author edits their own message; sets `edited_at`, leaves id/order unchanged, broadcasts a `message.edited` event (F42). Author-only, no admin override.
- **Auth / scope:** Bearer; caller must be the message's `sender_id`.
- **Idempotent:** Yes (re-sending the same content is a safe no-op that still returns the current message).
- **Request:**
```json
{ "content": "shipping the release now (edited)" }
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 200 | Edited; `edited_at` set; edit event broadcast | updated `message` object |
  | 400 | Malformed body | problem+json |
  | 401 | Auth | problem+json |
  | 403 | Caller is not the author — no admin override (F42) | problem+json |
  | 404 | No such message (or caller cannot see its conversation) | problem+json |
  | 409 | Message is already soft-deleted — edit rejected (F39) | problem+json |
  | 422 | Body null/whitespace or > 4000 chars | problem+json |

### `DELETE /v1/messages/{message_id}`
- **Purpose:** Author soft-deletes their own message; sets `deleted_at`, hides content, retains the row, broadcasts a `message.deleted` event (F43). Author-only, no admin override.
- **Auth / scope:** Bearer; caller must be the message's `sender_id`.
- **Idempotent:** Yes (already deleted → `204`).
- **Request:** _(none; `DELETE`)_
```json
{}
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 204 | Soft-deleted; delete event broadcast | (empty) |
  | 401 | Auth | problem+json |
  | 403 | Caller is not the author (F43) | problem+json |
  | 404 | No such message (uniform) | problem+json |

### `POST /v1/dms/{user_id}/messages`
- **Purpose:** Send a 1:1 DM to another distinct active user (`user_id` = the recipient). Modeled as a `Message` with `recipient_id` set and `channel_id` null (ADR-0002); persisted then delivered live (F46).
- **Auth / scope:** Bearer; any active user. Authorization is a participant check — recipient must be a distinct, active user. Self-DM is rejected.
- **Idempotent:** **Yes — required** `Idempotency-Key` header (F40), same semantics as channel send.
- **Request:** _(path `user_id` = recipient; header: `Idempotency-Key: <uuid>`)_
```json
{ "content": "hey, got a minute?", "media_ids": [] }
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 201 | DM created and delivered live | `message` object (id, recipient_id, sender_id, content, media, created_at, channel_id: null) |
  | 200 | Idempotent replay — original DM returned (F40) | `message` object |
  | 400 | Malformed body or missing/invalid `Idempotency-Key` | problem+json |
  | 401 | Auth | problem+json |
  | 404 | Recipient does not exist or is inactive | problem+json |
  | 422 | Self-DM (`user_id` == caller), body null/whitespace or > 4000 chars, unknown `media_id` (F47, F39) | problem+json |
  | 429 | Over send rate limit | problem+json + `Retry-After` |

### `GET /v1/dms/{user_id}/messages`
- **Purpose:** Cursor-paginated 1:1 DM history with `user_id`, chronological, keyed on the canonical user-pair (F48, ADR-0002). Serves reconnect catch-up too.
- **Auth / scope:** Bearer; caller must be one of the two participants (participant check).
- **Idempotent:** Yes (safe read).
- **Request:** _(query: `?limit=50&cursor=<opaque|null>`)_
```json
{}
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 200 | DM history page | `{ items: [ message... ], next_cursor }` (soft-deleted excluded) |
  | 400 | Invalid `limit`/`cursor` | problem+json |
  | 401 | Auth | problem+json |
  | 404 | Other participant does not exist (uniform) | problem+json |
  | 422 | `user_id` == caller (no self-conversation) | problem+json |

### `POST /v1/media`
- **Purpose:** Phase-1 of the two-phase media flow: upload bytes through the app for validation, content-sniffing, and EXIF-strip, storing the object and returning a `media_id` to attach on message-create (F57, F58, F61, ADR-0007).
- **Auth / scope:** Bearer; any active user. Upload rate-limited (20/min/user).
- **Idempotent:** No (each upload yields a distinct `media_id`; orphaned uploads are cleaned up if never associated, F62).
- **Request:** `multipart/form-data` — the request is NOT JSON. Parts:
```json
{
  "file": "<binary bytes>",
  "declared_content_type": "image/png",
  "kind": "image",
  "filename": "screenshot.png"
}
```
  Size caps per `kind`: image 10 MB, file 50 MB, video 200 MB. Image allowlist `image/png|jpeg|gif|webp` (SVG excluded); video allowlist `video/mp4|webm`. Sniffed bytes must match `declared_content_type`.
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 201 | Stored (EXIF stripped for images); pending association | `{ media_id, kind, content_type, filename, size, created_at }` |
  | 400 | Malformed multipart / missing parts | problem+json |
  | 401 | Auth | problem+json |
  | 413 | Over the per-type size cap (F58) | problem+json |
  | 415 | Disallowed type, `image/svg+xml`, sniff mismatch, or EXIF-strip failure on a malformed image (F58, F61) | problem+json |
  | 429 | Over upload rate limit (20/min) | problem+json + `Retry-After` |

### `GET /v1/media/{media_id}/url`
- **Purpose:** Phase-2 fetch: issue a 5-min presigned GET URL to the object's separate origin, authorized against the caller's **current** channel/DM membership (F59, ADR-0007). A removed member loses access within the TTL.
- **Auth / scope:** Bearer; caller must currently be a member of the media's parent channel, or a participant of its parent DM (checked at issuance, F34/F59).
- **Idempotent:** Yes (safe read; each call returns a fresh short-lived URL).
- **Request:** _(none; `GET`)_
```json
{}
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 200 | Signed URL issued | `{ url, expires_at, content_type, filename, size }` (URL is short-lived; never logged) |
  | 401 | Auth | problem+json |
  | 403 | Caller not a current member/participant of the parent conversation (F59) | problem+json |
  | 404 | No such media, or unassociated/orphaned (uniform) | problem+json |

### `POST /v1/admin/users/{user_id}/deactivate`
- **Purpose:** System Admin deactivates a user: blocks login, invalidates all of that user's sessions immediately, drops their WebSockets at next revalidation, runs channel succession where they were sole admin (F25, F36). Cannot deactivate the last active System Admin (F27).
- **Auth / scope:** Bearer; **`system_admin`** only.
- **Idempotent:** Yes (already inactive → `200`/`204`, no further effect).
- **Request:**
```json
{}
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 200 | User deactivated; sessions invalidated; succession applied | `{ id, is_active: false }` |
  | 401 | Auth | problem+json |
  | 403 | Caller is not a System Admin | problem+json |
  | 404 | No such user | problem+json |
  | 409 | Target is the last active System Admin — rejected (F27) | problem+json |

### `POST /v1/admin/users/{user_id}/reactivate`
- **Purpose:** System Admin reactivates a deactivated user; login restored with a fresh session (prior sessions not restored) (F26).
- **Auth / scope:** Bearer; **`system_admin`** only.
- **Idempotent:** Yes (already active → `200`, no further effect).
- **Request:**
```json
{}
```
- **Responses:**
  | Status | Meaning | Body |
  |--------|---------|------|
  | 200 | User reactivated | `{ id, is_active: true }` |
  | 401 | Auth | problem+json |
  | 403 | Caller is not a System Admin | problem+json |
  | 404 | No such user | problem+json |

### WebSocket `/v1/ws`

Real-time only (F51–F56). New-message / edit / delete events, typing, and presence are delivered here; **all mutations happen over REST** (the WS surface is receive-oriented plus lightweight `typing`/`join`/`heartbeat` client frames). Delivery is **at-least-once**; clients **dedup by message id** (F54) and recover missed events via history-since-last-id on reconnect (F55, Flow K).

**Connection & auth (auth-BEFORE-join, F52, ADR-0006):**
- Client connects to `wss://<host>/v1/ws` presenting the access token — as `?access_token=<jwt>` query param or a `Sec-WebSocket-Protocol` bearer sub-protocol. The server authenticates **before** the client may join any conversation. Missing/invalid/expired token → the socket is closed immediately with close code `4401` before any join.
- After auth, the client sends `join` frames for the channels/DMs it is authorized for; the server verifies channel membership / DM participation per frame (F34) and subscribes the connection to the corresponding Redis topic (`chan:{channel_id}` or `dm:{a}:{b}`, ADR-0004). An unauthorized join is refused with an `error` frame (the socket stays open for other joins).
- Presence ref-count increments on connect and decrements on close; a user is `online` while ≥1 connection exists across tabs/instances (F49). On the last disconnect, `last_seen` is persisted durably (F50).
- **Heartbeat & periodic revalidation:** the client sends `ping` frames on an interval; the server sends `pong` and, on each heartbeat, **re-runs the session-revocation check** (`sid` active + user `is_active`). A revoked/expired/deactivated session is dropped mid-connection at the next heartbeat with the appropriate close code below (F52). An ungraceful disconnect (missed heartbeats) expires via TTL and flips presence to `offline`.

**Close codes (documented scheme, F52/F70):**
| Code | Reason | Trigger |
|------|--------|---------|
| 1000 | normal closure | client closed cleanly |
| 1001 | going away | server shutdown / instance drain |
| 4401 | auth-failed | missing/invalid/expired token at connect |
| 4402 | token-expired | access token expired mid-connection (client should refresh + reconnect) |
| 4403 | token-revoked | session revoked via logout / password change / reset |
| 4404 | user-deactivated | target user deactivated by System Admin |
| 4408 | heartbeat-timeout | heartbeats stopped; connection reaped |
| 4429 | rate-limited | abusive frame rate |

**Client → server frames:**
```json
{ "type": "join",      "conversation": { "kind": "channel", "channel_id": "01J..." } }
{ "type": "join",      "conversation": { "kind": "dm", "user_id": "01J..." } }
{ "type": "leave",     "conversation": { "kind": "channel", "channel_id": "01J..." } }
{ "type": "typing",    "conversation": { "kind": "channel", "channel_id": "01J..." } }
{ "type": "ping" }
```

**Server → client event envelope** (every event carries the message id where applicable, for client dedup):
```json
{
  "type": "message.created",
  "conversation": { "kind": "channel", "channel_id": "01J..." },
  "data": {
    "id": "01J8...UUIDv7",
    "channel_id": "01J...",
    "recipient_id": null,
    "sender_id": "01J...",
    "content": "shipping the release now 🚀",
    "media": [ { "media_id": "01J...", "kind": "image", "filename": "screenshot.png", "size": 20481 } ],
    "created_at": "2026-07-02T14:31:07.482Z",
    "edited_at": null,
    "deleted_at": null
  }
}
```
- `message.edited` — same envelope; `data` includes the updated `content` and non-null `edited_at`; id/order unchanged (F42). Clients reconcile idempotently by id.
- `message.deleted` — `data` = `{ "id", "conversation", "deleted_at" }`; content omitted; clients hide by id (F43).
- `typing` — `data` = `{ "user_id", "conversation" }`; the client auto-expires the indicator **5 s** after the last received typing frame (F56); no explicit stop frame is required.
- `presence` — `data` = `{ "user_id", "state": "online" | "offline", "last_seen": "<iso8601|null>" }` (F49, F50).
- `error` — `data` = `{ "code", "detail" }` for a non-fatal per-frame failure (e.g. unauthorized join) that does not close the socket.

Events fan out across instances via Redis pub/sub (F53). Ordering across the fan-out is best-effort; clients order by the time-sortable message id (ADR-0005), not by arrival order.

## Backward-compatibility checklist
- [ ] No field removed/renamed without a version bump.
- [ ] New fields optional with safe defaults.
- [ ] Enum additions tolerated by clients.
- [ ] Consumers notified; clients regenerated.

## Open questions

1. **Avatar upload path.** `PATCH /v1/me` accepts `avatar_url`, and `POST /v1/media` handles image hygiene (EXIF-strip, sniff). It is not fixed whether an avatar must be uploaded via `POST /v1/media` first (then its served URL supplied) or whether an external URL is permitted. Recommendation: route avatars through `POST /v1/media` for consistent hygiene; confirm with backend-engineer/security-reviewer. Non-blocking; does not change the wire contract shape.
2. **Refresh-token transport.** This contract returns `refresh_token` in the login/refresh JSON body. A hardened alternative is an httpOnly, Secure, SameSite cookie to keep it out of JS reach. This is a security-owner decision (pair with `security-reviewer`); flagged because switching later is a client-visible change.
3. **`502` for email-delivery failure on invite issuance.** F1/ADR-0010 require failing loudly to the admin when SMTP is unreachable. `502 Bad Gateway` is used here to distinguish an upstream email-provider failure from a client error; confirm the status choice with the API owner (an alternative is `503`).
4. **Message-history `limit` maximum (100).** ADR-0003 defers the exact max page size to this contract; 100 is proposed. Confirm against load-test findings (`performance-engineer`) before GA.
