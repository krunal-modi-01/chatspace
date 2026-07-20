# chatspace v1 — Task Breakdown

> Ordered, dependency-aware decomposition of the [v1 technical spec](./chatspace-v1-technical-spec.md) into independently-buildable, PR-sized tasks. Honors the binding ADRs (`architecture/adr/0001`–`0012`) and the 1,000-user single-Postgres/single-Redis constraint from `CLAUDE.md`. No ADR is re-decided here.

## Summary

This decomposes the chatspace v1 TSD into 41 dependency-ordered, PR-sized tasks across six milestones, plus a small M7 addenda milestone for gaps found post-implementation: **M0 Foundation** (skeleton, config, DB/Redis wiring, the initial schema migration, shared id/pagination utilities), **M1 Auth & Onboarding** (security primitives, revocable sessions, email, non-skippable admin bootstrap, invites, registration, login/reset), **M2 Core Domain** (profile, channels, membership + succession, admin deactivate, messages, DMs), **M3 Realtime** (WS connection manager, Redis persist-then-publish fan-out, presence, typing), **M4 Cross-cutting** (rate limiting, media pipeline + association), **M5 Frontend** (auth/channel/messaging/WS/presence/media UI + WCAG AA), **M6 Ship** (docker-compose, CI, observability, Render deploy, load test + restore drill GA gate), **M7 Addenda** (T42: closes the `must_change_password` lockout discovered while exercising T30, per ADR-0011), and **M8 Admin surfaces** (T43–T47: the System Admin invite/user-management screens and their backing list endpoints, closing a frontend traceability gap where admin capabilities were specified only as backend behavior — PRD v2 §11, R54/R55, F71/F72; T44 also lands the T20 deactivate/reactivate endpoints), and **M9 My channels & live membership** (T48–T52: the caller-scoped `GET /v1/channels` list, the per-user WS topic with `channel.member_added`/`channel.member_removed` events per ADR-0012, the live-updating My Channels navigation UI, and an a11y pass — closing a traceability gap where a user added to a private channel could not see it anywhere; the public browse F30 excludes own memberships and no "list my channels" read was ever specified — PRD v3 R56/R57, F73–F75). The ordering honors persist-then-publish (T24 after message persistence), auth-before-join WS semantics, and the 1,000-user single-Postgres/single-Redis constraint. Backend and frontend tracks run largely in parallel against the frozen API contract. **M10 Design foundation & redesign** (T53–T84) then executes the 2026-07-20 UX/design review against a new design documentation set (`architecture/design-tokens.md` v3 + `docs/design/*`, governed by ADR-0013–0017): a token → component → IA → conversation-surface redesign, the previously-unbuilt **DM frontend surface** (ADR-0017), and the **R59/F76 user-directory read** (ADR-0016) that makes member-add and DM-start usable — off the critical path, behind a human design 🔒 gate.

## Milestone overview

| Milestone | Tasks | Owning agents | Ships |
|-----------|-------|---------------|-------|
| **M0 — Foundation** | T01–T08 | backend, database, infrastructure, frontend | Buildable skeleton, migrated schema, shared utils |
| **M1 — Auth & Onboarding** | T09–T16 | backend | Phase-0 prereqs + full auth/invite/reset loop |
| **M2 — Core Domain** | T17–T22 | backend | Profile, channels, membership, messages, DMs (REST) |
| **M3 — Realtime** | T23–T26 | backend | WS delivery, cross-instance fan-out, presence, typing |
| **M4 — Cross-cutting** | T27–T29 | backend | Rate limiting, media pipeline |
| **M5 — Frontend** | T30–T36 | frontend, accessibility | Full SPA + WCAG 2.2 AA |
| **M6 — Ship** | T37–T41 | infrastructure, devops, performance | Docker, CI, observability, deploy, GA validation |
| **M7 — Addenda** | T42 | backend, frontend | Closes the `must_change_password` login lockout (ADR-0011) |
| **M8 — Admin surfaces** | T43–T47 | backend, frontend, accessibility | System Admin screens (invite + user management) + their backing list endpoints; closes the frontend traceability gap (PRD v2 §11, R54/R55, F71/F72) |
| **M9 — My channels & live membership** | T48–T52 | backend, frontend, accessibility | Caller-scoped channel list + per-user WS membership events + live-updating nav UI; closes the added-to-private-channel visibility gap (PRD v3 R56/R57, F73–F75, ADR-0012) |
| **M10 — Design foundation & redesign** | T53–T84 | frontend, backend, accessibility, architecture (design) | Token/component/IA/conversation redesign per ADR-0013–0017 + `docs/design/`; adds the DM frontend surface (ADR-0017) and the R59/F76 user-directory read (ADR-0016); off the critical path, behind a design 🔒 gate |

Standard gate shorthand used below (from `CLAUDE.md` commands): **LINT** = `ruff check` / `npm run lint`; **TYPE** = `mypy app` / `npm run typecheck`; **TEST** = `pytest` / `npm run test`; **SEC** = secret-scan hook passes + security-reviewer sign-off (invoked wherever auth/PII/secrets/tokens are touched).

---

## M0 — Foundation

### T01 — Backend app skeleton + settings + health
- **Phase / owner:** Foundation / `backend-engineer` (+ `infrastructure-engineer` for `uv`)
- **Depends on:** —
- **Scope (in):** FastAPI app entrypoint (`app/main.py`), the `api/ws/models/schemas/services/db/core` package layout from `CLAUDE.md` REPOSITORY STRUCTURE, `pydantic-settings` config loading all secrets from env (DB URL, Redis URL, JWT key, SMTP, S3, bootstrap admin), `/v1/healthz` liveness + `/v1/readyz` readiness endpoints, `uv` project (`pyproject.toml`), `/v1` base-path router mount.
- **Scope (out):** No business routes, no DB models, no auth.
- **Acceptance criteria:**
  - [ ] `uv sync` installs; app boots via `docker-compose up` skeleton or `uvicorn`.
  - [ ] Settings fail fast with a clear error when a required env var is missing; no secret has a hardcoded default.
  - [ ] `GET /v1/healthz` returns 200; `GET /v1/readyz` reflects DB+Redis reachability (stubbed until T03/T05).
  - [ ] LINT, TYPE, TEST pass; SEC (no secrets committed).
- **Refs:** TSD §2–§3; `CLAUDE.md` REPOSITORY STRUCTURE, boundaries.secrets_location.

### T02 — Structured logging + correlation id + RFC 7807 error handler
- **Phase / owner:** Foundation / `backend-engineer`
- **Depends on:** T01
- **Scope (in):** JSON structured logging; per-request correlation-id middleware (generated or propagated), attached to every log line and every response body; global exception handler emitting `application/problem+json` with `type/title/status/detail/instance/correlation_id` and the `errors[]` list on 400/422; a redaction guard that keeps message content, tokens, secrets, and PII out of logs.
- **Scope (out):** Metrics/Sentry (T39); per-endpoint problem slugs (added by owning tasks).
- **Acceptance criteria:**
  - [ ] Every response carries `correlation_id`; same id appears on the request's log lines.
  - [ ] Errors serialize as problem+json with the exact shape in the API contract "Conventions → Errors".
  - [ ] Unit test asserts a log emitted while logging a message body/JWT contains no raw content/token (F68/R24).
  - [ ] LINT, TYPE, TEST, SEC pass.
- **Refs:** API contract Conventions (Errors); TSD §8 Logging, §9; FS F68/F70.

### T03 — Async DB layer + Alembic scaffolding
- **Phase / owner:** Foundation / `backend-engineer` (+ `database-engineer` review)
- **Depends on:** T01
- **Scope (in):** Async SQLAlchemy engine over `asyncpg` with a per-instance pool and bounded statement timeout; `AsyncSession` FastAPI dependency; Alembic initialized and wired to settings; `readyz` DB probe. **No tables yet.**
- **Scope (out):** Schema DDL (T04); PgBouncer (explicitly deferred per TSD §4).
- **Acceptance criteria:**
  - [ ] `alembic upgrade head` runs against an empty DB (no-op baseline).
  - [ ] Session dependency yields/closes cleanly; pool size + statement timeout are config-driven.
  - [ ] `readyz` turns unhealthy when Postgres is unreachable (fast error, no hang) — supports TSD §7 "Postgres down".
  - [ ] LINT, TYPE, TEST pass.
- **Refs:** TSD §4 (asyncpg pool), §7; `CLAUDE.md` commands.migrate_*.

### T04 — Initial schema migration (all tables, enums, indexes, constraints)
- **Phase / owner:** Foundation / `database-engineer`
- **Depends on:** T03
- **Scope (in):** One Alembic migration authoring the exact DDL in the DB design doc: enums (`channel_member_role`, `invite_status`, `attachment_kind`); tables `users, channels, channel_members, messages, attachments, invites, password_reset_tokens, sessions` in FK order; all functional/partial indexes; XOR + no-self-DM CHECK, content/name/size CHECKs; a total, tested downgrade.
- **Scope (out):** Seed data (bootstrap is T12); any table not in the design; SQLAlchemy ORM model classes may be authored here or in owning tasks (author them here to unblock).
- **Acceptance criteria:**
  - [ ] `alembic upgrade head` then `downgrade base` round-trips cleanly on a scratch DB (verified in CI, T38).
  - [ ] All indexes/constraints from DB design "Indexing strategy" and "Integrity & invariants" present, including `ix_messages_dm_history` on `least/greatest(sender_id,recipient_id)`.
  - [ ] `id` columns have **no** DB default (app-generated UUIDv7 per T06); `created_at` defaults `now()`.
  - [ ] No Postgres extension required; token columns are `*_token_hash` only.
  - [ ] Migration is additive-only and never edits a prior file; `schema-change-guard` checklist satisfied; LINT/TYPE/TEST pass.
- **Refs:** DB design (full); TSD §4; ADR-0002/0003/0005/0006/0007; `CLAUDE.md` do_not_touch (alembic/versions).

### T05 — Redis client wiring
- **Phase / owner:** Foundation / `backend-engineer`
- **Depends on:** T01
- **Scope (in):** Async Redis client from settings; connection lifecycle + `readyz` probe; namespaced key helpers/prefixes for the four Redis roles (pub/sub `chan:{id}`/`dm:{a}:{b}`, presence, rate-limit buckets, session-revocation cache); documented fail-mode wrappers (callers decide fail-open vs fail-closed).
- **Scope (out):** Pub/sub logic (T24), presence (T25), rate limiter (T27), revocation cache population (T10) — this is the shared client only.
- **Acceptance criteria:**
  - [ ] Client connects; `readyz` degrades (not crashes) when Redis is down — matches TSD §7 "Redis down".
  - [ ] Key-builder unit tests produce canonical DM topic `dm:{least}:{greatest}`.
  - [ ] LINT, TYPE, TEST pass.
- **Refs:** TSD §2 (Redis roles), §7; `CLAUDE.md` ARCHITECTURE NOTES.

### T06 — UUIDv7 id generation utility
- **Phase / owner:** Foundation / `backend-engineer`
- **Depends on:** T01
- **Scope (in):** App-side UUIDv7 generator (vetted library, e.g. `uuid-utils`/`uuid6`) exposed as a single helper used by all id assignment; the id must be obtainable before persist so it can accompany the fan-out payload.
- **Scope (out):** DB defaults (excluded by design).
- **Acceptance criteria:**
  - [ ] Generated ids are valid UUIDv7 and monotonically time-sortable within a process (property test over a batch).
  - [ ] New dependency passes the `dependency-update` vetting checklist (recorded).
  - [ ] LINT, TYPE, TEST pass.
- **Refs:** ADR-0005; DB design cross-cutting decision #1.

### T07 — Cursor pagination utility
- **Phase / owner:** Foundation / `backend-engineer`
- **Depends on:** T06
- **Scope (in):** Opaque base64url cursor encode/decode over `(created_at, id)`; a reusable keyset-query helper (DESC, `limit` default 50 / clamp 100); `{ items, next_cursor }` envelope; `next_cursor=null` at stream end; malformed cursor → 400.
- **Scope (out):** Offset pagination (implemented inline in T18 public browse); the actual message queries (T21/T22).
- **Acceptance criteria:**
  - [ ] Round-trip encode→decode is stable; clients cannot need to construct it (opaque).
  - [ ] `limit>100` clamps to 100; invalid cursor raises the 400 problem+json.
  - [ ] Unit tests cover end-of-stream and short-page-≠-end (soft-deleted exclusion) semantics.
  - [ ] LINT, TYPE, TEST pass.
- **Refs:** ADR-0003; API contract Conventions → Pagination.

### T08 — Frontend app skeleton
- **Phase / owner:** Foundation / `frontend-engineer`
- **Depends on:** —
- **Scope (in):** React/TS SPA (Vite), Tailwind, routing, typed REST client with `Authorization: Bearer` injection + 401→refresh handling, a store for access/refresh tokens and current user, base problem+json error surfacing, env-based API base URL.
- **Scope (out):** Feature screens (T30–T36); WS client (T33).
- **Acceptance criteria:**
  - [ ] `npm run build` succeeds; app renders a shell with protected/public route split.
  - [ ] API client attaches Bearer, parses problem+json, and shows `correlation_id` in dev error UI.
  - [ ] Functional components only, one per file, no inline business logic (extracted to hooks/services) per `CLAUDE.md` React conventions.
  - [ ] LINT, TYPE, TEST (frontend) pass.
- **Refs:** `CLAUDE.md` Conventions (React); API contract Conventions (Auth).

---

## M1 — Auth & Onboarding

### T09 — Security primitives (password hashing, policy, JWT)
- **Phase / owner:** Auth / `backend-engineer`
- **Depends on:** T01
- **Scope (in):** bcrypt/argon2 hash+verify; password policy validator (min 6 + basic strength) reused by register/change/reset; JWT sign/verify with 15-min TTL carrying `sub`=user_id and `sid`=session_id; signing key from settings.
- **Scope (out):** Session persistence/revocation (T10); endpoints.
- **Acceptance criteria:**
  - [ ] Hashes never reversible/logged; verify constant-time; policy rejects non-compliant with 422 detail (F23).
  - [ ] JWT encodes/decodes `sub`+`sid`; expired token rejected; signing key never logged.
  - [ ] LINT, TYPE, TEST, SEC (secrets, hashing) pass.
- **Refs:** TSD §8 AuthN; FS F23; API contract Auth; `CLAUDE.md` SECURITY REQUIREMENTS.

### T10 — Session store + Redis revocation cache + auth dependency
- **Phase / owner:** Auth / `backend-engineer`
- **Depends on:** T04, T05, T06, T09
- **Scope (in):** `sessions` CRUD (create with hashed refresh token, 30-day sliding expiry, revoke, list-by-user); Redis revocation cache (hot path) with Postgres fallback when cold; a `require_auth` FastAPI dependency that validates the JWT and re-runs the revocation check (sid active + user active) on every protected request → near-immediate 401 on revoke/deactivate.
- **Scope (out):** Login/logout endpoints (T15); WS revalidation (T23).
- **Acceptance criteria:**
  - [ ] Revoked/expired/logged-out `sid` fails auth within one request; Redis-down falls back to Postgres (correctness preserved, latency up) per TSD §7.
  - [ ] Refresh tokens stored only as `refresh_token_hash`; raw never returned/logged.
  - [ ] Tests cover: valid, revoked, expired, deactivated-user, cold-cache fallback.
  - [ ] LINT, TYPE, TEST, SEC pass; `api-change-guard` satisfied for the auth dependency contract.
- **Refs:** ADR-0006; DB design `sessions`, `ix_sessions_user_active`; API contract Conventions (Auth), `/v1/auth/sessions`.

### T11 — EmailService (SMTP abstraction, fail-loud)
- **Phase / owner:** Auth / `backend-engineer`
- **Depends on:** T01
- **Scope (in):** Provider-agnostic async SMTP sender; invite + reset templates; inline send with bounded retry; **fail-loud** (raises so callers surface 502/alert); startup check that email config is present (Phase-0 prerequisite); no token/PII in logs.
- **Scope (out):** Invite/reset business logic (T13/T16).
- **Acceptance criteria:**
  - [ ] Missing email config fails the app at startup (non-skippable prerequisite).
  - [ ] Send failure raises a typed error (no silent queue-and-forget); retry is bounded.
  - [ ] Templates never log the raw token/link; SEC passes.
  - [ ] LINT, TYPE, TEST pass.
- **Refs:** ADR-0010; TSD §10 Phase 0, §7 (Email down); FS F1/F15, §9 hard deps.

### T12 — System Admin bootstrap (env-seed, non-skippable)
- **Phase / owner:** Auth / `backend-engineer`
- **Depends on:** T04, T06, T09
- **Scope (in):** Startup routine that, when zero users exist, creates exactly one active `is_system_admin` user from env-seeded credentials (hashed); idempotent on restart; app refuses to serve if bootstrap cannot complete and no admin exists.
- **Scope (out):** Admin endpoints (T20); invites (T13).
- **Acceptance criteria:**
  - [ ] Fresh DB → exactly one System Admin created without any invite (F8); re-run creates no duplicate.
  - [ ] Bootstrap credentials read only from env; never logged; SEC passes.
  - [ ] Workspace can never reach a zero-admin state at startup (F8/R46).
  - [ ] LINT, TYPE, TEST pass.
- **Refs:** ADR-0009; TSD §10 Phase 0; FS F8/F9.

### T13 — Invite service + endpoints
- **Phase / owner:** Auth / `backend-engineer`
- **Depends on:** T10, T11, T12, T06
- **Scope (in):** `POST /v1/invites` (system_admin only, single-use 7-day token, email dispatched, 409 if already registered, 502 on email-unreachable), `GET /v1/invites/{token}` (validate, return locked email, 410 on non-pending), `POST /v1/invites/{id}/resend` (rotate token, invalidate prior), `DELETE /v1/invites/{id}` (revoke); store `token_hash` only; content-free audit events for issuance/revocation.
- **Scope (out):** Registration redemption (T14); rate limiting (T27).
- **Acceptance criteria:**
  - [ ] Non-admin caller → 403; already-registered email → 409; SMTP unreachable → 502 fail-loud.
  - [ ] Raw invite token never returned in any response or log; only `token_hash` persisted.
  - [ ] Resend invalidates the prior token (410 on old); revoke → 410; used invite → 409 on revoke.
  - [ ] Audit event logged without the token; LINT, TYPE, TEST, SEC pass; `api-change-guard` satisfied.
- **Refs:** API contract `/v1/invites*`; FS F1–F7; DB design `invites`.

### T14 — Registration (invite redemption)
- **Phase / owner:** Auth / `backend-engineer`
- **Depends on:** T13, T09
- **Scope (in):** `POST /v1/auth/register` — redeem a pending/unexpired invite, create active user with email locked to the invite, hash password (policy-checked), enforce case-insensitive unique username/email, mark invite `accepted`; no invite-less path.
- **Scope (out):** Login (T15).
- **Acceptance criteria:**
  - [ ] Valid invite + compliant password → 201 user (no hash in body), invite → accepted (F5).
  - [ ] Expired/used/revoked token → 410; duplicate username/email → 409; bad password → 422; missing token → rejected (F6/F7).
  - [ ] LINT, TYPE, TEST, SEC pass; `api-change-guard` satisfied.
- **Refs:** API contract `/v1/auth/register`; FS F5/F6/F7; DB design `users`.

### T15 — Login / refresh / logout + session management endpoints
- **Phase / owner:** Auth / `backend-engineer`
- **Depends on:** T10
- **Scope (in):** `POST /v1/auth/login` (200 with access+refresh+user; 401 uniform on bad creds; 403 on deactivated), `POST /v1/auth/refresh` (rotate/slide), `POST /v1/auth/logout` (revoke current sid, 204), `GET /v1/auth/sessions`, `DELETE /v1/auth/sessions/{id}` (own-only, 403/404).
- **Scope (out):** Rate limiting (T27); reset (T16).
- **Acceptance criteria:**
  - [ ] Login issues 15-min access + 30-day refresh session; deactivated → 403 with clear title; invalid creds → 401 non-field-revealing (F11).
  - [ ] Logout revokes only the current session; other sessions unaffected (F14); revoked refresh → 401 (F12).
  - [ ] Session list never returns token material; cross-user session delete → 403.
  - [ ] LINT, TYPE, TEST, SEC pass; `api-change-guard` satisfied.
- **Refs:** API contract `/v1/auth/login|refresh|logout|sessions`; FS F10–F14; ADR-0006.

### T16 — Password reset + password change
- **Phase / owner:** Auth / `backend-engineer`
- **Depends on:** T10, T11
- **Scope (in):** `POST /v1/auth/password-reset` (uniform 202, latest-token-only, email single-use 1-hour token via T11), `POST /v1/auth/password-reset/confirm` (410 on stale/used, invalidate other sessions), `POST /v1/auth/password/change` (verify current, keep initiating session, revoke others). `token_hash` only; content-free reset-request audit event; reset send failure preserves uniform response but alerts server-side.
- **Scope (out):** Rate limiting (T27).
- **Acceptance criteria:**
  - [ ] Reset response identical whether or not the email exists (F15, non-enumerating).
  - [ ] Only the most recently issued reset token validates; earlier → 410 (F17); confirm/change invalidate other sessions (F16/F22); wrong current password → 401, password unchanged.
  - [ ] Raw reset token never returned/logged; LINT, TYPE, TEST, SEC pass; `api-change-guard` satisfied.
- **Refs:** API contract `/v1/auth/password-*`; FS F15–F17, F22; DB design `password_reset_tokens`, `ix_prt_user_active`.

---

## M2 — Core Domain

### T17 — Profile endpoints (`/v1/me`)
- **Phase / owner:** Core / `backend-engineer`
- **Depends on:** T10
- **Scope (in):** `GET /v1/me`; `PATCH /v1/me` for `first_name/last_name/avatar_url`; email/username immutable (400 on change attempt); initials-fallback data available; never return hash.
- **Scope (out):** Avatar upload path (open question #1 — accept URL for now; revisit with T28).
- **Acceptance criteria:**
  - [ ] GET returns profile without password (F18); PATCH persists name/avatar; attempt to change email/username → 400 (F20).
  - [ ] Empty name → 422; LINT, TYPE, TEST, SEC pass; `api-change-guard` satisfied.
- **Refs:** API contract `/v1/me`; FS F18–F21.

### T18 — Channel create / get / public browse
- **Phase / owner:** Core / `backend-engineer`
- **Depends on:** T10
- **Scope (in):** `POST /v1/channels` (any active user; creator recorded as `admin` member; name 1–80 charset, case-insensitive unique → 409/422), `GET /v1/channels/{id}` (member sees; private non-member → uniform 404), `GET /v1/channels/public` (offset pagination, page size 50, excludes channels caller already belongs to).
- **Scope (out):** Membership mutation (T19); messages (T21).
- **Acceptance criteria:**
  - [ ] Create → 201 with creator as admin member (F29); duplicate name → 409; invalid name → 422.
  - [ ] Private channel invisible to non-members via uniform 404; public browse returns `{items,total,limit,offset}` excluding own memberships (F30).
  - [ ] LINT, TYPE, TEST pass; `api-change-guard` satisfied.
- **Refs:** API contract `/v1/channels`, `/channels/public`, `/channels/{id}`; FS F29–F31; DB design `channels`.

### T19 — Membership + last-admin succession + zero-admin frozen state
- **Phase / owner:** Core / `backend-engineer`
- **Depends on:** T18
- **Scope (in):** `POST /join` (public only, idempotent), `POST /leave` (sole-admin succession runs first), `GET/POST/PATCH/DELETE /members` (admin-gated add/remove/role), earliest-`joined_at` succession (F36) in a transaction, zero-admin terminal state blocks membership/role mutation (409, F37), server-side membership check reused everywhere.
- **Scope (out):** Deactivation-triggered succession call site (T20).
- **Acceptance criteria:**
  - [ ] Sole admin leaving with members present → earliest-joined member promoted before removal (F36); no members → channel persists zero-admin (F37).
  - [ ] Mutations on a zero-admin channel → 409 (F33/F37); private join by non-admin → 403; non-admin member mgmt → 403.
  - [ ] Join/leave idempotent; concurrency test asserts succession runs at most once.
  - [ ] LINT, TYPE, TEST pass; `api-change-guard` satisfied.
- **Refs:** API contract `/channels/{id}/join|leave|members*`; FS F31–F37, Flows E/F; DB design `ix_channel_members_admin_succession`.

### T20 — Admin deactivate / reactivate
- **Phase / owner:** Core / `backend-engineer`
- **Depends on:** T15, T19
- **Scope (in):** `POST /v1/admin/users/{id}/deactivate` (system_admin only; set `is_active=false`; revoke all target sessions immediately via T10; run channel succession where target is sole admin via T19; last-active-admin guard → 409), `POST .../reactivate` (fresh session only). Content-free audit events.
- **Scope (out):** WS mid-connection drop (delivered by T23 revalidation; this task just invalidates sessions).
- **Acceptance criteria:**
  - [ ] Deactivate invalidates all target sessions and runs succession for each sole-admin channel (F25/F36); last System Admin → 409 (F27).
  - [ ] Reactivate restores login with a new session; prior sessions stay invalid (F26); prior messages/memberships intact (F28).
  - [ ] LINT, TYPE, TEST, SEC pass; `api-change-guard` satisfied.
- **Refs:** API contract `/v1/admin/users/*`; FS F25–F28, Flow D; ADR-0009.

### T21 — Message send / edit / delete / history (channels)
- **Phase / owner:** Core / `backend-engineer`
- **Depends on:** T19, T07, T10
- **Scope (in):** `POST /channels/{id}/messages` (required `Idempotency-Key`; membership check; app-generated UUIDv7; validate content ≤4000 non-whitespace; validate supplied `media_id`s belong to sender + unbound), `GET /channels/{id}/messages` (cursor history, soft-deleted excluded), `PATCH /messages/{id}` + `DELETE /messages/{id}` (author-only, edit rejected if deleted). Persist only (publish added in T24).
- **Scope (out):** Fan-out/live events (T24); DMs (T22); rate limiting (T27); media bytes (T28).
- **Acceptance criteria:**
  - [ ] Valid send → 201 with UUIDv7 id + authoritative `created_at`; replay of same `Idempotency-Key` → 200 same row, exactly one row (F40); missing key → 400.
  - [ ] Non-member → 403; empty/whitespace/>4000 → 422; edit by non-author → 403; edit of deleted → 409; delete → 204 soft-delete retains row (F42/F43).
  - [ ] History chronological, soft-deleted excluded, `next_cursor` correct; serves catch-up via `cursor` (F44/F55).
  - [ ] LINT, TYPE, TEST pass; `api-change-guard` satisfied.
- **Refs:** API contract `/channels/{id}/messages`, `/messages/{id}`; FS F38–F45; ADR-0003/0004/0005.

### T22 — DM send / history
- **Phase / owner:** Core / `backend-engineer`
- **Depends on:** T21, T07
- **Scope (in):** `POST /dms/{user_id}/messages` (participant model: `recipient_id` set, `channel_id` null; required `Idempotency-Key`; recipient must be distinct + active; self-DM → 422), `GET /dms/{user_id}/messages` (cursor history keyed on canonical `least/greatest` pair). Persist only.
- **Scope (out):** Live delivery (T24).
- **Acceptance criteria:**
  - [ ] DM to distinct active user → 201; self-DM → 422 (F47); inactive/nonexistent recipient → 404.
  - [ ] History uses identical `least/greatest(sender_id,recipient_id)` expressions to hit `ix_messages_dm_history`; participant-check enforced.
  - [ ] Idempotency semantics match channel send; LINT, TYPE, TEST pass; `api-change-guard` satisfied.
- **Refs:** API contract `/dms/{user_id}/messages`; FS F46–F48; ADR-0002; DB design DM index.

---

## M3 — Realtime

### T23 — WebSocket connection manager (auth-before-join, heartbeat, revalidation, close codes)
- **Phase / owner:** Realtime / `backend-engineer`
- **Depends on:** T10, T05
- **Scope (in):** `/v1/ws` endpoint; authenticate token **before** any join (missing/invalid → close `4401`); `join`/`leave` frames with per-frame membership/participant re-check; ping/pong heartbeat; periodic revalidation re-running the session/user-active check and dropping with documented close codes (`4402/4403/4404/4408/4429`, `1001` on drain); per-connection subscription bookkeeping.
- **Scope (out):** Redis fan-out payloads (T24); presence (T25); typing (T26).
- **Acceptance criteria:**
  - [ ] Connect without valid token → `4401` before any join; unauthorized `join` → non-fatal `error` frame, socket stays open (F52).
  - [ ] Revoked/expired/deactivated session dropped at next heartbeat with the correct close code; missed heartbeats reaped (`4408`).
  - [ ] Close-code catalogue matches the API contract table exactly.
  - [ ] LINT, TYPE, TEST, SEC pass; `api-change-guard` satisfied.
- **Refs:** API contract WebSocket `/v1/ws` (auth, close codes, frames); FS F51/F52; ADR-0006.

### T24 — Redis pub/sub fan-out + persist-then-publish wiring
- **Phase / owner:** Realtime / `backend-engineer`
- **Depends on:** T23, T21, T22
- **Scope (in):** Per-instance Redis subscriber relaying `chan:{id}`/`dm:{a}:{b}` events to local sockets; publish `message.created/edited/deleted` **after** commit in T21/T22 service paths, carrying the id for client dedup; cross-instance delivery with no session affinity; graceful behavior when Redis publish fails (event lost → recovered via catch-up).
- **Scope (out):** Presence/typing (T25/T26); media in payload (T29).
- **Acceptance criteria:**
  - [ ] A message sent on instance A is received by a subscriber on instance B (F53), verified with two app instances.
  - [ ] Event is emitted only after DB commit (persist-then-publish, F45); Redis-down leaves REST/history working, live delivery stops (TSD §7).
  - [ ] Server→client envelope matches the API contract shape; edit/delete events carry id (F42/F43/F54).
  - [ ] LINT, TYPE, TEST pass; `api-change-guard` satisfied.
- **Refs:** ADR-0004; API contract WebSocket events; FS F45/F51/F53/F54.

### T25 — Presence service
- **Phase / owner:** Realtime / `backend-engineer`
- **Depends on:** T23, T05
- **Scope (in):** Redis ref-count per user across tabs/instances with heartbeat TTL; `presence` online/offline events; durable `last_seen` write to Postgres on last disconnect; no false-online after Redis restart.
- **Scope (out):** Typing (T26).
- **Acceptance criteria:**
  - [ ] User `online` while ≥1 connection; one of many tabs closing keeps `online` (F49); last close/timeout → `offline` + durable `last_seen` (F50).
  - [ ] Redis restart → no user falsely online; `last_seen` still available from Postgres.
  - [ ] LINT, TYPE, TEST pass.
- **Refs:** FS F49/F50; TSD §2/§7 presence; DB design `users.last_seen`.

### T26 — Typing indicator relay
- **Phase / owner:** Realtime / `backend-engineer`
- **Depends on:** T23, T24
- **Scope (in):** `typing` client frame → fan-out `typing` event to other conversation participants; server relays only (no persistence); client-side 5-s auto-expire semantics documented (no stop frame).
- **Scope (out):** UI expiry logic (T34).
- **Acceptance criteria:**
  - [ ] Typing in a channel/DM relays a `typing` event to other participants only, across instances (F56).
  - [ ] No DB write; abusive frame rate can trigger `4429` via T27 hook point.
  - [ ] LINT, TYPE, TEST pass; `api-change-guard` satisfied.
- **Refs:** API contract `typing` frame/event; FS F56.

---

## M4 — Cross-cutting

### T27 — Rate limiter (token bucket)
- **Phase / owner:** Cross-cutting / `backend-engineer`
- **Depends on:** T05, T15, T21
- **Scope (in):** Redis token-bucket middleware/dependency: message send 10/10s burst 20 (per user), auth endpoints 5/5min per IP+identifier (non-enumerating), media upload 20/min (per user), abusive WS frames → `4429`; `429` + `Retry-After`; **fail-closed** on abuse-sensitive endpoints when Redis is unavailable.
- **Scope (out):** Media endpoints exist in T28 — wire the upload limit there.
- **Acceptance criteria:**
  - [ ] Over-limit send/auth/upload → 429 + `Retry-After`; auth keying reveals nothing about identifier existence (F64).
  - [ ] Redis-down → abuse-sensitive endpoints fail-closed (reject), others degrade gracefully (TSD §7).
  - [ ] LINT, TYPE, TEST, SEC pass; `api-change-guard` satisfied.
- **Refs:** API contract Conventions → Rate limits; FS F62–F64; TSD §3 rate limiter.

### T28 — Media upload / validate / sniff / EXIF-strip / store + presigned GET + orphan cleanup
- **Phase / owner:** Cross-cutting / `backend-engineer` (+ `security-reviewer`)
- **Depends on:** T10, T04
- **Scope (in):** `POST /v1/media` (multipart; per-kind size caps → 413; allowlist + SVG exclusion + sniff mismatch → 415; EXIF-strip-or-reject for images; filename sanitize; boto3 put to S3-compatible bucket; store metadata + `storage_key`), `GET /v1/media/{id}/url` (5-min presigned GET authorized against **current** membership/participation → 403), orphan-sweep job for unbound attachments (F62).
- **Scope (out):** Binding to messages (T29).
- **Acceptance criteria:**
  - [ ] Oversize → 413; disallowed/SVG/sniff-mismatch/EXIF-fail → 415; nothing stored on rejection (F58/F61).
  - [ ] Presigned URL issued only to a current member/participant (F59); removed member loses access within TTL; URL never logged.
  - [ ] Orphan sweep removes unbound rows past TTL via `ix_attachments_orphans` and purges object bytes; SEC (content-type/PII/secrets) passes.
  - [ ] LINT, TYPE, TEST pass; `api-change-guard` + upload-rate-limit (T27) wired.
- **Refs:** API contract `/v1/media*`; FS F57–F62, Flow H; ADR-0007; DB design `attachments`.

### T29 — Media association on message-create + `media[]` hydration
- **Phase / owner:** Cross-cutting / `backend-engineer`
- **Depends on:** T28, T21, T24
- **Scope (in):** On channel/DM send, bind supplied `media_ids` (verify uploader==sender + still unbound), set `message_id`; batch-hydrate `media[]` on history reads (`WHERE message_id = ANY(:ids)`, no N+1) and on WS event payloads.
- **Scope (out):** Frontend rendering (T35).
- **Acceptance criteria:**
  - [ ] Unknown/other-user/already-bound `media_id` → 422; bound attachment appears in message `media[]` and in the WS `message.created` payload.
  - [ ] History media hydration is a single batch fetch per page (no N+1); LINT, TYPE, TEST pass; `api-change-guard` satisfied.
- **Refs:** API contract message-create + WS envelope `media`; DB design `ix_attachments_message`, "Message media hydration".

---

## M5 — Frontend (builds against the frozen API contract; parallel with M2–M4)

### T30 — Auth flows UI
- **Owner:** `frontend-engineer` · **Depends on:** T08, T14, T15, T16
- **Scope (in):** Login, invite-redemption registration (email locked/pre-filled from `GET /invites/{token}`), password-reset request+confirm, password change, logout, "manage devices" session list/revoke; problem+json surfacing; refresh-on-401.
- **Scope (out):** Channels/messaging.
- **Acceptance:** All auth screens work end-to-end against backend; deactivated/invalid-cred/expired-invite states render correct messaging; no token stored in a way that logs it; LINT/TYPE/TEST(frontend) + SEC pass.
- **Refs:** API contract auth/invite/reset; FS Flows A/B/C.

### T31 — Channels + membership UI
- **Owner:** `frontend-engineer` · **Depends on:** T08, T18, T19
- **Scope:** Channel create, public browse+join (offset paging), channel view, member list + admin membership/role management, leave with succession messaging, zero-admin frozen affordance. (Out: messages.)
- **Acceptance:** Create/browse/join/leave and admin member mgmt work; private-channel 404 handled; 409 zero-admin surfaced; LINT/TYPE/TEST pass.
- **Refs:** API contract channels/members; FS F29–F37.

### T32 — Messaging UI
- **Owner:** `frontend-engineer` · **Depends on:** T08, T21
- **Scope:** Message list with cursor history/infinite scroll, optimistic send with client-generated `Idempotency-Key`, author edit/delete, other-user identity + initials badge (F21/F24). (Out: live WS — T33.)
- **Acceptance:** Send/edit/delete/history render; soft-deleted hidden; optimistic send reconciles by id; LINT/TYPE/TEST pass.
- **Refs:** API contract messages; FS F38–F44.

### T33 — WebSocket client (connect / join / dedup / reconnect catch-up)
- **Owner:** `frontend-engineer` · **Depends on:** T08, T23, T24
- **Scope:** WS connect with access token, `join` authorized conversations, render live `message.created/edited/deleted`, **client dedup by message id**, reconnecting banner + catch-up via history-since-last-id, close-code handling (refresh+reconnect on 4402). (Out: presence/typing UI.)
- **Acceptance:** Live events render without refresh; duplicates deduped (F54); reconnect fetches missed messages and merges (F55); LINT/TYPE/TEST pass.
- **Refs:** API contract WebSocket; FS F51–F55, Flows J/K.

### T34 — Presence + typing UI
- **Owner:** `frontend-engineer` · **Depends on:** T33, T25, T26
- **Scope:** Online/offline + last_seen rendering; typing indicator with 5-s auto-expire; heartbeat pings.
- **Acceptance:** Presence reflects ref-counted state; typing auto-clears 5 s after last frame (F56); LINT/TYPE/TEST pass.
- **Refs:** FS F49/F50/F56.

### T35 — Media UI
- **Owner:** `frontend-engineer` · **Depends on:** T31, T28
- **Scope:** Upload (progress, size/type errors), attach `media_id` on send, inline render for decodable images/video, download affordance with filename/size otherwise (no transcoding), fetch via presigned URL.
- **Acceptance:** Upload+attach+render/download work; 413/415/429 surfaced; presigned URL used at fetch time; LINT/TYPE/TEST pass.
- **Refs:** API contract media; FS F57–F62.

### T36 — Accessibility pass (WCAG 2.2 AA)
- **Owner:** `accessibility-auditor` (+ `frontend-engineer`) · **Depends on:** T30–T35
- **Scope:** ARIA live regions for incoming messages/typing/edits/deletes, keyboard nav, focus management on live updates, contrast, alt text, initials-badge semantics.
- **Acceptance:** Automated a11y checks pass; keyboard-only flows for auth/channel/message verified; live-region announcements verified; LINT/TYPE/TEST pass.
- **Refs:** FS §9 (WCAG 2.2 AA); TSD §3 React SPA.

---

## M6 — Ship

### T37 — Dockerfiles + docker-compose (local full stack)
- **Owner:** `infrastructure-engineer` · **Depends on:** T01, T05
- **Scope:** Backend/frontend images; `docker-compose.yml` with app, Postgres, Redis, MinIO (S3-compatible), and a local SMTP catcher; `docker-compose up --build` boots the stack and runs migrations. (Out: prod deploy — T40.)
- **Acceptance:** `docker-compose up --build` yields a working local env with all dependencies; migrations applied on boot; no secrets baked into images; SEC passes.
- **Refs:** `CLAUDE.md` commands.run; ADR-0007 (MinIO local); ADR-0010.

### T38 — CI pipeline
- **Owner:** `devops-engineer` · **Depends on:** T04, T37
- **Scope:** Pipeline running install, LINT, TYPE, TEST (backend+frontend), secret-scan hook, and migration `upgrade head`→`downgrade base` round-trip on a scratch DB; PR gate = 1 approval, squash to `main`.
- **Acceptance:** CI runs all `CLAUDE.md` command gates and blocks merge on failure; migration round-trip verified; secret-scan enforced (not disable-able).
- **Refs:** `CLAUDE.md` DEFINITION OF DONE, conventions.pr_target; DB design reversibility.

### T39 — Observability
- **Owner:** `devops-engineer` (+ `backend-engineer`) · **Depends on:** T02, T24
- **Scope:** Sentry-class error/uptime monitor; key metrics (active WS conns, send throughput/error rate, delivery lag SLI, 429 counts, presence gauge, media/email success, DB pool saturation, Redis availability); content-free audit events; symptom-based alerts.
- **Acceptance:** Delivery-lag SLI emitted; audit events (invite/deactivation/reset) recorded without payloads (F69); alerts defined for the TSD §9 list; no PII/tokens in any signal (SEC).
- **Refs:** TSD §9; FS F68/F69.

### T40 — Render deployment + CORS/TLS/secrets/object-store/SMTP wiring
- **Owner:** `infrastructure-engineer` (+ `devops-engineer`) · **Depends on:** T37
- **Scope:** Render services (app ×1–2 behind LB, managed Postgres w/ daily backups, managed Redis), object-store + SMTP env wiring, TLS at LB, CORS allowlist (no wildcard in prod), all secrets via env; Phase-0 startup prerequisites enforced.
- **Acceptance:** Deploy runs ≥2 stateless app instances; TLS enforced; CORS blocks unlisted origins (F66/F67); app fails loud at startup if email/admin bootstrap missing; daily backups configured; SEC passes. **🔒 human sign-off** (irreversible/prod config).
- **Refs:** ADR-0008; TSD §10; FS F66/F67; `CLAUDE.md` SECURITY REQUIREMENTS.

### T41 — Load test + backup/restore drill (GA gate)
- **Owner:** `performance-engineer` (+ `devops-engineer`) · **Depends on:** T29, T33, T38, T39, T40
- **Scope:** Full REST+WS+fan-out load test at ~1,000 concurrent users across 2 instances validating p95 <500 ms delivery / <300 ms reads; mandatory Postgres restore drill; confirm history `limit` max (open question #4).
- **Acceptance:** Latency SLOs met at target load (F65); restore drill completes within RTO target and is documented; findings recorded (promote to outbox only if loss observed, ADR-0004). **🔒 GA sign-off gate.**
- **Refs:** TSD §6/§7/§12; FS F65, §9 accepted risks; ADR-0003/0004.

---

## M7 — Addenda (gaps found post-implementation)

### T42 — Forced password-change unblock (must_change_password has no exit path)
- **Phase / owner:** Addendum / `backend-engineer` (+ `frontend-engineer`, `security-reviewer`) · **Depends on:** T16, T30
- **Context:** Discovered while exercising the shipped T30 login UI: a `must_change_password`-flagged account (today, only the env-seeded bootstrap admin, ADR-0009) is rejected at `POST /v1/auth/login` with `403 must-change-password` **before any session is issued**, and every password-setting endpoint except self-service reset requires a session. The account has no way to ever change its password. Root cause and decision recorded in **[ADR-0011](../../architecture/adr/0011-forced-password-change-unblock.md)** — this task implements that decision. Not a new capability; closes a gap in already-shipped T15/T16.
- **Scope (in):**
  - `backend/app/api/password.py::confirm_password_reset` — after `mark_reset_token_used`/setting `hashed_password`, also set `user.must_change_password = False` in the same transaction/commit.
  - `backend/app/api/password.py::change_password` — same clear, for the (currently unreachable but foreseeable) case of an authenticated session hitting this endpoint while the flag is set.
  - Frontend: when a `POST /v1/auth/login` response is a `403` with `type` ending in `/problems/must-change-password`, render a specific message + a CTA linking to `/password-reset` (the existing T30 `PasswordResetRequestPage`) instead of the generic 403 handling. No new page — reuses T30's reset flow end-to-end.
- **Scope (out):** No new endpoint, no new JWT claim/scope, no change to `POST /v1/auth/login`'s blocking behavior (it must continue to issue zero session while the flag is set — that property is intentional, see ADR-0011 Option B/C rejection).
- **Acceptance criteria:**
  - [ ] A `must_change_password=true` user who completes `POST /v1/auth/password-reset` → `POST /v1/auth/password-reset/confirm` successfully can then log in normally (flag is `false` after confirm).
  - [ ] `GET` on the user row after `password/change` succeeds while the flag was set (test seed) shows `must_change_password=false`.
  - [ ] Login still returns `403 must-change-password` with **no** `access_token`/`refresh_token`/session row created, for a flagged account that has not yet reset — this must not regress.
  - [ ] Frontend: hitting login with a flagged account shows a "reset your password to continue" message with a working link into the existing reset-request page; no dead end.
  - [ ] LINT, TYPE, TEST (backend + frontend) pass; SEC re-review confirms clearing the flag on reset-confirm does not reopen the ADR-0009 threat model.
  - [ ] Memory note `t15-must-enforce-must-change-password.md` updated to mark both open follow-ups resolved once merged.
- **Refs:** ADR-0009, ADR-0011; `backend/app/services/auth.py` (`MustChangePasswordError`); `backend/app/core/errors.py` (`must_change_password_error_handler`); `backend/app/api/password.py`; T30 `PasswordResetRequestPage`/`usePasswordResetRequestForm`.

---

## M8 — Admin surfaces (gap found post-implementation)

> **Context.** The System Admin's *capabilities* (invite issue/revoke/resend R45, deactivate/reactivate R47) shipped as backend endpoints (T13, and T20 as-specced), but the **screens** an admin uses to perform them were never scoped: PRD v1 §11 enumerated no admin screen inventory, so M5 (T30–T36) built none, and T30 only consumed the *invitee's* `GET /invites/{token}` redemption read. Two backing **reads** were also never specified — an admin cannot list outstanding invites or enumerate users. This milestone closes both, per **PRD v2 §11 / R54 / R55 / FS F71 / F72**. No ADR or DB schema change is required (listing uses existing `invites`/`users` tables; deactivation flips existing `users.is_active`).

### T43 — List invites endpoint (`GET /v1/invites`, admin-only)
- **Phase / owner:** Admin / `backend-engineer` (+ `security-reviewer`)
- **Depends on:** T13
- **Scope (in):** `GET /v1/invites` behind `require_system_admin`; optional `?status=pending|accepted|revoked|expired` filter; pagination (cursor over `(created_at, id)` reusing the T07 utility, for consistency with ADR-0003); returns `{ items: [{ id, email, status, expiry, issued_at }], next_cursor }`. New `list_invites` service in `app/services/invites.py`. Content-free logging (never the raw token — R24).
- **Scope (out):** Any invite mutation (already T13); UI (T45).
- **Acceptance criteria:**
  - [ ] Admin caller → 200 with paginated invites; `status` filter narrows correctly; non-admin → 403.
  - [ ] **Raw invite token never appears** in the response or logs; only `token_hash` persisted (unchanged from T13).
  - [ ] Empty result → `{ items: [], next_cursor: null }` (not an error).
  - [ ] LINT, TYPE, TEST, SEC pass; `api-change-guard` satisfied.
- **Refs:** PRD R54; FS F71; API contract `/v1/invites`; ADR-0003.

### T44 — Admin router: list users + deactivate/reactivate (`/v1/admin/*`)
- **Phase / owner:** Admin / `backend-engineer` (+ `security-reviewer`)
- **Depends on:** T15, T19, T10
- **Scope (in):** New `app/api/admin.py` router (prefix `/admin`), mounted in `app/api/router.py`, all endpoints behind `require_system_admin`:
  - `GET /v1/admin/users?q=&status=&limit=&cursor=` — paginated, searchable (name/username/email, case-insensitive), includes active + deactivated; returns `{ items: [{ id, first_name, last_name, username, email, role, is_active, last_seen }], next_cursor }`; **never** returns `hashed_password` (R55/F72).
  - `POST /v1/admin/users/{id}/deactivate` — **this is where the never-built T20 lands**: set `is_active=false`, revoke all target sessions immediately (reuse T10 session store), run sole-admin channel succession where the target is a channel's only admin (reuse T19), reject deactivating the **last active System Admin** with `409` (F27), content-free audit event.
  - `POST /v1/admin/users/{id}/reactivate` — set `is_active=true`; no prior sessions restored (F26); audit event.
- **Scope (out):** WS mid-connection drop (delivered by T23 revalidation once sessions are revoked); UI (T46).
- **Acceptance criteria:**
  - [ ] `GET /admin/users` → 200 paginated; `q` matches name/username/email; deactivated users included; non-admin → 403; **no password material** in any row.
  - [ ] Deactivate invalidates all target sessions + runs succession for each sole-admin channel (F25/F36); last System Admin → 409 (F27); reactivate restores login with a fresh session, prior sessions stay invalid (F26); prior messages/memberships intact (F28).
  - [ ] LINT, TYPE, TEST, SEC pass; `api-change-guard` satisfied.
- **Refs:** PRD R47/R55; FS F25–F28, F72, Flow D; ADR-0009; API contract `/v1/admin/users*`.

### T45 — Frontend: admin route guard + nav + Invite Management screen
- **Owner:** `frontend-engineer` · **Depends on:** T08, T43, T13
- **Scope (in):** An `AdminRoute` guard (mirrors `ProtectedRoute`, additionally requiring `user.role === "system_admin"`, redirecting others); an admin route branch in `App.tsx` (`/admin/invites`); a conditional "Admin" nav entry in `UserMenu` shown only to System Admins; `adminApi` client methods `issueInvite`/`listInvites`/`resendInvite`/`revokeInvite` (+ types in `src/api/types.ts`); `pages/admin/InvitesPage.tsx` + `hooks/useInvites.ts` — issue form (inline email-format validation, pending state), list filterable by status, resend/revoke actions; surface `409` (already-registered) and `502` (email-unreachable) problem+json inline. Reuse existing `ui/` primitives + `httpClient` problem+json handling.
- **Scope (out):** User management (T46); a11y finishing sweep (T47).
- **Acceptance:** Admin sees the nav + screen and can issue/list/resend/revoke end-to-end; a non-admin is redirected from `/admin/*` and sees no nav entry; 409/502/410 states render clearly; no raw token rendered/logged; LINT/TYPE/TEST(frontend) + SEC pass.
- **Refs:** PRD §11 (Invite Management), R45/R54; FS F1–F7, F71; API contract `/v1/invites*`.

### T46 — Frontend: User Management screen
- **Owner:** `frontend-engineer` · **Depends on:** T45, T44
- **Scope (in):** `pages/admin/UsersPage.tsx` + `hooks/useAdminUsers.ts` at `/admin/users`; `adminApi` methods `listUsers`/`deactivateUser`/`reactivateUser` (+ types); searchable user list (name/username/email) showing role/active/last-seen; deactivate (with an explicit confirmation affordance) and reactivate actions; render the **last-active-admin `409`** as a clear inline message, not a generic failure. Reuses the T45 `AdminRoute`/nav.
- **Scope (out):** a11y finishing sweep (T47).
- **Acceptance:** Admin can list/search users and deactivate/reactivate; deactivation asks for confirmation; last-active-admin 409 renders the specific message; deactivated users remain visible in the list; LINT/TYPE/TEST pass.
- **Refs:** PRD §11 (User Management), R47/R55; FS F25–F28, F72, Flow D; API contract `/v1/admin/users*`.

### T47 — Accessibility pass over the admin screens (WCAG 2.2 AA)
- **Owner:** `accessibility-auditor` (+ `frontend-engineer`) · **Depends on:** T45, T46
- **Scope (in):** Keyboard nav across both admin screens; focus management on the invite-issue form and the deactivate-confirm affordance; ARIA on the invite/user lists (table semantics) and confirmation dialog; status/error announcements via a live region; contrast on status badges (pending/revoked, active/inactive).
- **Acceptance:** Automated a11y checks pass; keyboard-only issue/resend/revoke and deactivate/reactivate flows verified; confirm-dialog focus trap + return-focus verified; LINT/TYPE/TEST pass.
- **Refs:** FS §9 (WCAG 2.2 AA); PRD §11; mirrors T36.

---

## M9 — My channels & live membership (gap found post-implementation)

> **Context.** A user *added* to a private channel had no way to *see* it: the only channel list ever specified is the public browse (F30/R49), which **excludes** channels the caller already belongs to, and no "list my channels" read was ever scoped — the same traceability-gap class M8 closed for the admin surfaces. The write side (T19 membership endpoints, T31 admin member-management UI) shipped correctly; the read surface and its live propagation were never specified anywhere (the PRD §11 "no channels joined" empty state and the DB design's `ix_channel_members_user` "My channels" index both assumed it). This milestone closes both, per **PRD v3 §11 / R56 / R57, FS F73–F75**. **No DB schema change** — `ix_channel_members_user` was designed for exactly this read. The new per-user WS topic and membership events are governed by **[ADR-0012](../../architecture/adr/0012-per-user-websocket-topic.md)** (extends ADR-0004's per-conversation keying).

### T48 — My-channels list endpoint (`GET /v1/channels`)
- **Phase / owner:** Channel visibility / `backend-engineer`
- **Depends on:** T18, T07, T10
- **Scope (in):** `GET ""` collection route on the existing channels router (collision-free beside `POST ""`, `GET /public`, `GET /{channel_id}`); a `list_my_channels` service reusing the T18 `ChannelView(channel, member_count, my_role)` projection; cursor pagination over channel `(created_at, id)` DESC reusing the T07 utility unchanged (the T43 invites list is the reference implementation); `{ items, next_cursor }` envelope with items `{ id, name, is_private, created_by, created_at, member_count, my_role }`; query served by the existing `ix_channel_members_user` index.
- **Scope (out):** WS membership events (T49); UI (T50); any schema change (none needed).
- **Acceptance criteria:**
  - [ ] A member sees every channel they belong to — public **and** private — each with `my_role`; channels they do not belong to never appear (F73).
  - [ ] Empty membership → `{ items: [], next_cursor: null }` (non-error); malformed `cursor`/`limit` → 400 problem+json.
  - [ ] Pagination follows ADR-0003 (default 50 / clamp 100; opaque cursor round-trips; stable under concurrent membership changes).
  - [ ] LINT, TYPE, TEST, SEC pass; `api-change-guard` satisfied.
- **Refs:** PRD R56; FS F73, Flow E; API contract `GET /v1/channels`; ADR-0003; DB design `ix_channel_members_user`.

### T49 — Per-user WS topic + membership lifecycle events
- **Phase / owner:** Channel visibility / `backend-engineer` (+ `security-reviewer`)
- **Depends on:** T23, T24, T19
- **Scope (in):** Four touch-points per ADR-0012: (1) `user:{user_id}` topic helper in `app/core/redis_keys.py`; (2) server-side auto-subscribe of every authenticated connection to its own per-user topic at connect in `app/ws/router.py` (no join frame; no other user's topic subscribable); (3) `user:*` pattern-subscription in the `app/ws/fanout.py` relay (mirrors the existing `presence:*` pattern); (4) publish `channel.member_added` (full channel summary) / `channel.member_removed` (channel id) **after commit** in the four membership mutation paths — self join, self leave, admin add, admin remove — using the contract envelope and ADR-0004's fail-open publish helper.
- **Scope (out):** Deactivation-triggered removal (WS drop covers it, F25/F52); role-change events (explicit non-goal — API contract open question #5); frontend consumption (T51).
- **Acceptance criteria:**
  - [ ] An added user's *other* connection receives `channel.member_added` with the full channel summary, verified **cross-instance** (two app instances); a removed user's connections receive `channel.member_removed` (F74/F75).
  - [ ] **Privacy assertion: no other user's connection receives either event** (per-user delivery isolation — the property that justifies ADR-0012 Option A over D).
  - [ ] Events are emitted only after DB commit (persist-then-publish); Redis-down → the membership mutation still succeeds and the event is lost (fail-open), recovered by the T51 reconnect refetch.
  - [ ] LINT, TYPE, TEST, SEC pass; `api-change-guard` satisfied.
- **Refs:** PRD R57; FS F74/F75, Flow L; ADR-0012 (+ ADR-0004 persist-then-publish); API contract WS section.

### T50 — Frontend: My Channels navigation list
- **Owner:** `frontend-engineer` · **Depends on:** T08, T31, T48
- **Scope (in):** `listMyChannels` client method + types (`CursorPage`-based, mirroring `adminApi.listInvites`); a `useMyChannels` hook following the `useChannelBrowse` template; the My Channels list as the primary logged-in navigation surface — placement decision owned here (the current shell is top-bar nav with no sidebar); rows navigate to the existing `/channels/:channelId` view; visibility (public/private) and own-role affordances; the "no channels joined" empty state (PRD §11) plus loading/error states.
- **Scope (out):** Live updates (T51); a11y finishing sweep (T52).
- **Acceptance:** List renders all memberships including private channels with role; navigation into a channel works; empty/loading/error states per PRD §11; LINT/TYPE/TEST (frontend) pass.
- **Refs:** PRD R56, §11; FS F73; API contract `GET /v1/channels`.

### T51 — Frontend: live channel-list updates
- **Owner:** `frontend-engineer` · **Depends on:** T50, T49, T33
- **Scope (in):** **App-level** (global) handling of `channel.member_added`/`channel.member_removed` — `useConversationSocket` is per-open-conversation, so membership events need a separate app-level listener path; idempotent insert/remove by channel id; graceful exit with a clear "you were removed from this channel" message when the removed channel is currently open (PRD §11 error state); my-channels refetch on WS reconnect (reusing the REST catch-up pattern — membership events have no replay).
- **Scope (out):** a11y finishing sweep (T52).
- **Acceptance:** A channel the user is added to (by an admin, or from another tab) appears live without refresh; a removed channel disappears live and an open view of it exits with the specific message; reconnect after missed events yields a correct list; unknown WS event types remain tolerated; LINT/TYPE/TEST pass.
- **Refs:** PRD R57, §11; FS F74/F75, Flow L; API contract WS events; ADR-0012.

### T52 — Accessibility pass (My Channels, WCAG 2.2 AA)
- **Owner:** `accessibility-auditor` (+ `frontend-engineer`) · **Depends on:** T50, T51
- **Scope (in):** Navigation/list semantics for the My Channels surface; keyboard nav; ARIA live-region announcements for channels appearing/disappearing (extends the existing live-region inventory); focus management when the currently-viewed channel is removed; contrast on visibility/role badges.
- **Acceptance:** Automated a11y checks pass; keyboard-only navigation into/out of channels verified; live announcements for add/remove verified; focus behavior on removal verified; LINT/TYPE/TEST pass.
- **Refs:** FS §9 (WCAG 2.2 AA); PRD §11; mirrors T36/T47.

---

## M10 — Design foundation & redesign (from the 2026-07-20 UX/design review)

> **Context.** The review found the app reads as generic and disconnected: the token layer is sound but there was no design layer above the task list, the conversation was subordinate to channel administration, the navigation graph had orphaned/unreachable screens, DMs were v1-scoped with a working backend (T22) but had **no frontend surface** in M0–M9, and the design system was defined yet unadopted (six badge implementations, a mis-defaulted `Button`, raw palette classes, no font, no skeletons). This milestone executes the redesign against the now-authoritative design documentation — `architecture/design-tokens.md` v3 and `docs/design/{DESIGN_SYSTEM,INFORMATION_ARCHITECTURE,UX_GUIDELINES,ACCESSIBILITY_GUIDELINES}.md`, governed by **ADR-0013–0017**. It also adds the **R59/F76 user-directory read** (ADR-0016) that makes member-add and DM-start usable. Sequenced **foundations-first** (tokens → primitives → shell → surface → workflows → responsive/a11y/polish) so no component is redesigned twice. **Off the critical path.** A human **design 🔒 gate** (ADR-0013–0017 sign-off) precedes phase D2+; the conversation-surface refactor ships behind a route-level feature flag with the old page retained until acceptance.

### D1 — Token foundation (`design-tokens.md` v3; no visual regression intended)
**T53 — Typography foundation.** frontend · deps T08 · Self-host a variable sans; add `--font-sans`/`--font-mono`, a tabular-nums utility, heading tracking; apply on `body`. *Accept:* app renders in the bundled font (no OS default), no external CDN (CSP), visual diff shows only the font change. *Refs:* design-tokens §4.
**T54 — Density / z-index / breakpoint tokens.** frontend · deps T53 · Add control/row-height, `--z-*`, `--bp-*` tokens to `index.css`. *Accept:* tokens present + documented; no consumer required yet. *Refs:* §6/§8/§9.
**T55 — Semantic recipes + motion.** frontend · deps T54 · Badge-tint `color-mix` recipe, `--focus-ring-*`, `--motion-*`, reduced-motion guard. *Refs:* §11/§12.
**T56 — Reconcile feedback/badges to tokens + lint guard.** frontend · deps T55 · Move `AlertBanner` colors to §12 recipes; add a CI lint/grep banning raw `gray-*|amber-*|emerald-*|red-*|indigo-*` in components. *Accept:* 0 raw-palette classes; banners theme-correct both themes. *Refs:* §12.

### D2 — Component system (`DESIGN_SYSTEM.md`)
**T57 — `Button` overhaul + migrate call sites.** frontend · deps T55 · Intrinsic width + `fullWidth`; sizes `sm`/`md`; `ghost`/`link` variants; link rendering; migrate all sites off `w-auto` and bespoke table buttons. *Accept:* no `w-auto` overrides; table actions use `size="sm"`; all states per tokens §13. *Refs:* DS §3.1.
**T58 — `Badge` primitive + de-dup.** frontend · deps T55 · New `Badge`; delete `RoleBadge` (×2), `VisibilityBadge`, `StatusBadge`, inline pills. *Accept:* one implementation; grep shows 0 duplicate pill impls. *Refs:* DS §3.2.
**T59 — `Textarea` primitive.** frontend · deps T55 · Extract from composer / message-edit / add-member. *Refs:* DS §3.3.
**T60 — `Skeleton` primitive.** frontend · deps T55 · Shape-matching; reduced-motion aware. *Refs:* DS §3.6.
**T61 — `EmptyState` primitive.** frontend · deps T57 · Icon + line + primary action. *Refs:* DS §3.6.
**T62 — `Confirm` + `Dialog` + `Drawer`.** frontend · deps T57, T64 · Inline confirm + modal dialog + right slide-over; focus trap/return; `--z-*`. *Refs:* DS §3.7/3.8.
**T63 — `Toast` layer.** frontend · deps T55 · Live-region-backed; `--z-toast`. *Refs:* DS §3.5.
**T64 — Icon set + `IconButton`.** frontend · deps T57 · Self-hosted stroke set; `IconButton` with `aria-label`. *Refs:* DS §3.9.
**T65 — `Avatar` presence + shell adoption.** frontend · deps T58 · Presence-dot slot; replace `UserMenu`'s bare initial with `Avatar`. *Refs:* DS §3.4.

### D3 — IA & navigation (`INFORMATION_ARCHITECTURE.md`, ADR-0014)
**T66 — App-shell redesign.** frontend · deps T57, T64, T65 · Persistent sidebar (mark→home · search/⌘K · Channels · Direct messages [empty until T75] · footer: Settings/Admin[role-gated]/account+theme), contextual top bar, single content region. *Refs:* IA §2/§4, ADR-0014.
**T67 — Nav-graph repair.** frontend · deps T66 · Admin group linking invites+users; resolve `/` (redirect to last/first channel, no dead landing); `NotFoundPage` on-system + in-shell. *Accept:* no orphan routes; `/admin/users` reachable; R58 test passes. *Refs:* IA §3.
**T68 — Mobile drawer.** frontend · deps T66 · Sidebar → drawer `< md`; content never stacked below nav. *Refs:* IA §2, DS §6.
**T69 — Quick switcher (⌘K).** frontend · deps T66 · Channels now; DMs/users later; keyboard-driven. *Refs:* UX §5.

### D4 — Conversation surface (ADR-0015; behind a feature flag)
**T70 — `ChannelPage` layout refactor.** frontend · deps T62, T66 · Full-height header / flexing timeline / pinned composer; members/roles/add-member/leave/frozen → **Channel details `Drawer`**; flag-gated, old page retained. *Refs:* ADR-0015, DS §5.3/4.5.
**T71 — `MessageTimeline` redesign.** frontend · deps T70 · Flat left-aligned grouped rows, date separators, hover/focus actions, drop right-alignment, real timestamps; preserve `role="log"`/live region. *Refs:* ADR-0015, DS §4.3.
**T72 — Composer refinement.** frontend · deps T70, T59, T64 · `IconButton` attach, counter near-limit only, `Textarea`; keep optimistic/retry/rate-limit behavior. *Refs:* DS §4.4.

### D5 — User directory, pickers, DMs & workflow polish
**T73 — Backend: user-directory search (`GET /v1/users/search`).** backend (+security-reviewer) · deps T10, T07 · Scoped authenticated read; minimal public fields (`id,username,first_name,last_name,avatar_url`); cursor paginated; excludes deactivated by default; rate-limited; **never** returns `email`/`is_active`/`last_seen`/`role`. *Accept:* field-minimization is a SEC criterion; non-admin caller allowed; `api-change-guard` satisfied. *Refs:* R59/F76, ADR-0016, API `/v1/users/search`.
**T74 — Member picker (replaces add-by-UUID).** frontend · deps T62, T73 · Channel-details add-member uses directory-search typeahead; add stays admin-gated. *Accept:* a private channel can be populated by name search, no UUID. *Refs:* F32/F33/F76, ADR-0016.
**T75 — DM surface.** frontend · deps T70, T73, T66 · Sidebar "Direct messages" section (recent conversations + presence), "New message" picker (T73), route `/dms/:userId` reusing the conversation surface (`ConversationTarget={kind:'dm'}`), empty state. *Accept:* start + read + send a DM end-to-end reusing the shared timeline/composer. *Refs:* ADR-0017/0015, R12/R13/F46–F48.
**T76 — Admin screens polish.** frontend · deps T57, T58, T63 · Relative/short timestamps, `Badge` migration, debounced search + result count, `size="sm"` actions, `Dialog` confirm for deactivate. *Refs:* DS, UX §3.
**T77 — `ChannelsPage` hierarchy.** frontend · deps T61, T57 · Browse-first; create behind a disclosure/button; empty-state cross-link. *Refs:* IA §5.
**T78 — Auth + profile refinements.** frontend · deps T57, T59 · Show-password toggle; inline password-rule validation; a profile screen with **avatar upload via the media pipeline** (retires the raw-URL field; resolves API open-Q#1). *Refs:* UX §3.5, PRD §11 v4.

### D6 — Responsive
**T79 — Responsive tables → cards.** frontend · deps T66, T58 · Members/invites/users/sessions stack to label:value cards `< md`; no horizontal scroll dependency. *Refs:* DS §6.

### D7 — Accessibility hardening (extends T36/T47/T52)
**T80 — A11y pass over the new component library.** accessibility-auditor (+ frontend) · deps T57–T69, T70–T75 · Menu keyboard pattern (`UserMenu`, ⌘K), `Dialog`/`Drawer` focus trap+return, `Toast` live region, `Badge` contrast both themes, focus-not-obscured, live announcements for sidebar add/remove. *Accept:* axe 0 serious/critical both themes; keyboard-only walkthrough of all primary flows. *Refs:* ACCESSIBILITY_GUIDELINES §4/§5.
**T81 — WCAG 2.2 AA deltas.** accessibility-auditor · deps T80 · Apply the 2.2-over-2.1 deltas (now the adopted standard): target-size ≥24px on row actions; focus-not-obscured for the sticky header, pinned composer, drawer scrim, and toasts. *Refs:* ACCESSIBILITY_GUIDELINES §1.

### D8 — Visual polish & motion
**T82 — Skeletons + empty states everywhere.** frontend · deps T60, T61 · Sidebar/tables/timeline skeletons; designed empty states on every async surface. *Refs:* UX §3.2/3.3.
**T83 — Motion pass.** frontend · deps T55 · Token-driven transitions; verify reduced-motion; new-message divider + scroll-to-bottom affordance. *Refs:* UX §4.
**T84 — Auto-load older history.** frontend · deps T71 · IntersectionObserver replaces the manual "load older" button. *Refs:* UX §3.2.

---

## Parallelizable tracks

- **Wave M0** — T01→T02→T03→T04 is a serial spine; **T05, T06, T07 run in parallel** once T01 lands; **T08 (frontend skeleton) is fully independent** and can start on day 1.
- **Wave M1** — T09, T11 parallel after T01; T12 after T04/T06/T09; then T13→T14 serial. **T15 and T16 run in parallel** once T10 lands.
- **Wave M2** — After T10: **T17, T18 parallel**; T19 after T18; T20 after T15+T19; **T21 then T22** (T22 reuses T21's send/idempotency helper). T17 can run alongside the channel track.
- **Wave M3** — T23 first; then **T24, T25 parallel**; T26 after T24.
- **Wave M4** — **T27 and T28 are independent** (different subsystems) and parallel; T29 joins them after both.
- **Frontend (M5)** runs as a **continuous parallel track** against the frozen API contract: T30 tracks M1, T31/T32 track M2, T33/T34 track M3, T35 tracks M4; T36 is a finishing sweep.
- **Ship (M6)** — T37 can be built early (right after M0); T38 follows T37; **T39 and T40 parallel**; T41 is the final serial GA gate depending on the whole system.
- **Wave M8** — **T43 and T44 run in parallel** (invite-list vs admin-users, different modules) once their deps (T13; T15/T19/T10) are met; frontend **T45 then T46** (T46 reuses T45's `AdminRoute`/nav/`adminApi`); T47 is a finishing a11y sweep after both screens. The whole milestone is off the critical path.
- **Wave M9** — **T48 and T49 run in parallel** (REST read vs WS plumbing, different modules) once their deps (T18/T07/T10; T23/T24/T19) are met; frontend **T50 then T51** (T51 consumes T49's events through T50's list); T52 is a finishing a11y sweep after both. The whole milestone is off the critical path.
- **Wave M10 (redesign)** — **foundations-first** so nothing is redesigned twice: **D1 (T53–T56)** tokens land before **D2 (T57–T65)** components; **D3 (T66–T69)** shell/nav and the *authoring* of **D5 (T74–T78)** workflows proceed once D2 lands; **T73 (backend user-search) is independent** and can start right after T10; **D4 (T70–T72)** conversation surface waits on D2+D3 and ships behind a feature flag; **T74** waits on T73, **T75 (DMs)** on T70+T73; **D6 (T79)**, **D7 (T80–T81)**, **D8 (T82–T84)** trail as continuous checks/polish. Off the critical path.

**Critical path:** T01→T03→T04→T10→(T18→T19)→T21→T23→T24→T29→T41

**Human 🔒 gates:** architecture sign-off already covers the design (TSD footer); additional 🔒 gates land at **T40** (prod/irreversible deploy config) and **T41** (GA go/no-go after load + restore drill). Every task touching auth/PII/secrets (T09, T10, T11, T12, T13, T14, T15, T16, T20, T27, T28, T42, T43, T44, T48, T49) routes through the security-reviewer/secret-scan gate — T48/T49 because they expose private-channel metadata over a new caller-scoped read and a new push surface.

**M7 addenda note:** T42 is not on the critical path and has no downstream dependents — it's a standalone fix for a gap found post-implementation (ADR-0011), safe to schedule whenever convenient once T16 and T30 are both merged.

**M8 addenda note:** T43–T47 close a frontend traceability gap found post-implementation (admin capabilities were specified only as backend behavior; the screens and their backing reads were never scoped — PRD v2 §11, R54/R55, F71/F72). Off the critical path, no downstream dependents. T44 also lands the deactivate/reactivate endpoints originally scoped as T20 (in `app/api/admin.py`). Schedulable once T13/T15/T19 are merged.

**M9 addenda note:** T48–T52 close a traceability gap found post-implementation: a user added to a private channel had no way to see it — the public browse (F30) excludes own memberships, and no "list my channels" read or membership-change propagation was ever specified (PRD v3 R56/R57, FS F73–F75, ADR-0012). Off the critical path, no downstream dependents, **no schema change** (`ix_channel_members_user` already serves the read). Schedulable once T18/T19/T23/T24 are merged.

**M10 addenda note:** T53–T84 execute the 2026-07-20 UX/design redesign against the design documentation (`architecture/design-tokens.md` v3, `docs/design/*`, ADR-0013–0017). A human **design 🔒 gate** (ADR sign-off) precedes phase D2+; the conversation-surface refactor (T70–T72) ships **behind a route-level feature flag** with the old page retained until acceptance. **T73** (new `GET /v1/users/search`) routes through the security-reviewer/secret-scan gate — a new authenticated read exposing the workspace directory, field-minimized per ADR-0016 — and `api-change-guard`. **T81** applies the WCAG 2.2 AA deltas — the adopted accessibility standard. Closes the DM-frontend build gap (DMs were v1-scoped with a working backend, T22, but had no UI in M0–M9). Off the critical path.
