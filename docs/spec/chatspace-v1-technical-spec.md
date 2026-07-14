# Technical Specification (TSD) — chatspace v1

> Owner: `architect` agent (+ human architecture 🔒 gate). Input: [`docs/spec/chatspace-v1-functional-spec.md`](chatspace-v1-functional-spec.md). Output consumed by: build agents (`backend-engineer`, `frontend-engineer`, `infrastructure-engineer`), `api-reviewer`, `database-engineer`, `security-reviewer`, `performance-engineer`.
> Status: **Draft** · ADRs: [ADR-0001](../../architecture/adr/0001-modular-monolith-fastapi.md) · [ADR-0002](../../architecture/adr/0002-dm-data-model.md) · [ADR-0003](../../architecture/adr/0003-cursor-pagination.md) · [ADR-0004](../../architecture/adr/0004-realtime-delivery-fanout.md) · [ADR-0005](../../architecture/adr/0005-message-id-scheme.md) · [ADR-0006](../../architecture/adr/0006-revocable-sessions.md) · [ADR-0007](../../architecture/adr/0007-media-object-storage.md) · [ADR-0008](../../architecture/adr/0008-deployment-target.md) · [ADR-0009](../../architecture/adr/0009-system-admin-bootstrap.md) · [ADR-0010](../../architecture/adr/0010-transactional-email.md) · [ADR-0012](../../architecture/adr/0012-per-user-websocket-topic.md) · [ADR index](../../architecture/adr/README.md) · Traces to spec: [`chatspace-v1-functional-spec.md`](chatspace-v1-functional-spec.md)

## 1. Summary & approach

chatspace v1 is built as the **simplest proven design that meets the functional spec (F1–F75) and the non-functional ceiling of ~1,000 concurrent users at p95 < 500 ms** — not hyperscale. The backend is a **modular monolith FastAPI application** serving both REST (CRUD, history, auth, invites, admin) and WebSocket (real-time delivery, typing, presence) in one process, deployed as **1–2 stateless instances** behind the platform load balancer ([ADR-0001](../../architecture/adr/0001-modular-monolith-fastapi.md)). State lives in **one managed PostgreSQL** (durable: users, channels, memberships, messages, invites, reset tokens, sessions, durable `last_seen`) and **one Redis** (ephemeral: WebSocket pub/sub fan-out, presence ref-counting, token-bucket rate limiting, session-revocation cache). Media lives in an **S3-compatible object store** ([ADR-0007](../../architecture/adr/0007-media-object-storage.md)). The frontend is a **React/TypeScript SPA**.

Real-time delivery is **persist-then-publish** over **Redis pub/sub**, at-least-once with **client-side dedup by message id**, and reconnect catch-up via history — no message queue ([ADR-0004](../../architecture/adr/0004-realtime-delivery-fanout.md)). Messages carry **time-sortable UUIDv7 ids** that drive ordering, cursor pagination, dedup, and catch-up ([ADR-0005](../../architecture/adr/0005-message-id-scheme.md), [ADR-0003](../../architecture/adr/0003-cursor-pagination.md)). Sessions are **revocable** via a server-side session store plus a Redis revocation check, so logout, password change/reset, and deactivation take effect near-immediately for REST and within the heartbeat window for WebSockets ([ADR-0006](../../architecture/adr/0006-revocable-sessions.md)). DMs are modelled as `Message` rows with `recipient_id` set (no synthetic channel) ([ADR-0002](../../architecture/adr/0002-dm-data-model.md)). Transactional email (invites, resets) is a **provider-agnostic SMTP abstraction** that fails loudly and is a hard first-run prerequisite ([ADR-0010](../../architecture/adr/0010-transactional-email.md)), alongside an **env-seeded, non-skippable System Admin bootstrap** ([ADR-0009](../../architecture/adr/0009-system-admin-bootstrap.md)). Deployment targets a **managed PaaS (recommended: Render)** ([ADR-0008](../../architecture/adr/0008-deployment-target.md)).

This TSD is at design altitude. Detailed API contracts and the physical data model are deliberately deferred to the follow-up instances of [`templates/api-contract.md`](../../templates/api-contract.md) (owned by `api-reviewer`) and [`templates/database-design.md`](../../templates/database-design.md) (owned by `database-engineer`), and the threat model to [`templates/threat-model.md`](../../templates/threat-model.md) (paired with `security-reviewer`).

## 2. Architecture

C4 container view. The two FastAPI instances are identical and stateless; any client WebSocket may land on either instance, and cross-instance broadcast is mediated entirely by Redis pub/sub.

```
                          ┌───────────────────────────────────────────────┐
                          │                Browser (client)                │
                          │   React/TypeScript SPA                         │
                          │   - REST calls: Authorization: Bearer <access> │
                          │   - 1 WebSocket per tab (access token at connect)│
                          │   - client-side dedup by message id            │
                          └───────────────┬───────────────┬───────────────┘
                                REST (HTTPS/JSON)      WebSocket (WSS)
                                          │               │
                                          ▼               ▼
                          ┌───────────────────────────────────────────────┐
                          │          Load Balancer (PaaS-managed)          │
                          │          TLS termination · CORS allowlist      │
                          └───────────────┬───────────────┬───────────────┘
                                          │               │
                          ┌───────────────▼───┐   ┌───────▼───────────────┐
                          │  FastAPI instance 1 │  │  FastAPI instance 2   │
                          │  (modular monolith) │  │  (identical, stateless)│
                          │  REST routers +     │  │  REST routers +        │
                          │  WS connection mgr  │  │  WS connection mgr     │
                          │  service layer      │  │  service layer         │
                          └───┬────────┬───────┘   └───┬────────┬──────────┘
                              │        │               │        │
              persist/query   │        │  pub/sub       │        │  persist/query
              (asyncpg pool)   │        │  presence      │        │
                              │        │  rate-limit     │        │
                              │        │  session cache  │        │
                              ▼        ▼                 ▼        ▼
                 ┌────────────────────┐   ┌───────────────────────────────┐
                 │   PostgreSQL (1)   │   │            Redis (1)          │
                 │  durable state:    │   │  (a) pub/sub fan-out ─────────┼──┐
                 │  users, channels,  │   │      chan:{id} / dm:{a}:{b}   │  │  cross-instance
                 │  members, messages │   │  (b) presence ref-count + TTL │  │  broadcast:
                 │  invites, reset    │   │  (c) token-bucket rate limits │  │  publish on
                 │  tokens, sessions, │   │  (d) session-revocation cache │  │  instance 1 →
                 │  durable last_seen │   └───────────────────────────────┘  │  delivered to
                 │  daily backups     │                    ▲                 │  subscribers on
                 └────────────────────┘                    └─────────────────┘  instance 2
                              ▲
                media bytes    │ presigned 5-min GET (separate origin)
              (upload via app: │
               validate+sniff+ │        ┌───────────────────────────────┐
               EXIF-strip)     └───────▶│   S3-compatible object store  │
                                        │   (MinIO local / R2·S3·Spaces)│
                                        │   separate serving origin     │
                                        └───────────────────────────────┘

        External (first-run prerequisites):
          ┌──────────────────────┐        ┌──────────────────────────────┐
          │  SMTP / email provider│◀──────│  EmailService (invites/resets)│  (inline send,
          │  (fail-loud)          │        │  provider-agnostic SMTP       │   bounded retry)
          └──────────────────────┘        └──────────────────────────────┘
```

**Data-flow highlights**
- **Send message (F38, F45, F51, F53):** client → REST `POST` (or WS) → membership check (F34) → persist to Postgres with UUIDv7 id → **publish** `message.created` to `chan:{id}` / `dm:{a}:{b}` on Redis → every instance subscribed for that conversation relays to its local WS connections → clients render and dedup by id.
- **Cross-instance fan-out (F53):** because publish/subscribe goes through Redis, a message sent by a client on instance 1 reaches a member connected to instance 2 without session affinity.
- **Media (F57–F60):** upload flows **through the app** (validate + sniff + EXIF-strip) then to the bucket; download is a **membership-checked 5-min presigned GET** to the bucket's separate origin.
- **Presence (F49–F50):** Redis ref-count per user across tabs/instances with heartbeat TTL; durable `last_seen` written to Postgres on last disconnect.
- **Membership change (F74–F75, ADR-0012):** commit the membership mutation (join/leave/admin add/remove) → **publish** `channel.member_added`/`channel.member_removed` to the affected user's per-user topic `user:{id}` → every instance relays to that user's local connections only (auto-subscribed at connect — no join frame). Reconnect catch-up is a REST refetch of the my-channels list (no event replay).

## 3. Components & responsibilities

| Component | Responsibility | New/changed | Owner agent |
|-----------|----------------|-------------|-------------|
| Auth / session service | Login, refresh, logout; issue short-lived access JWT (`sid` claim) + opaque refresh token; server-side session store + Redis revocation cache; enforce revocation on REST + WS revalidation (F10–F14, F52, ADR-0006) | New | `backend-engineer` |
| User / profile service | View/edit own profile (first/last name, avatar); immutable email/username; initials-badge fallback data; password change with policy + other-session invalidation (F18–F24, F22) | New | `backend-engineer` |
| Channel + membership service | Create public/private channel (creator = admin); browse public channels (paginated); **my-channels list (caller's own memberships, cursor-paginated, F73)**; join/leave; admin-gated membership + role management; last-admin succession; zero-admin frozen state; **publish membership lifecycle events after commit (F74/F75, ADR-0012)** (F29–F37, F73–F75) | New | `backend-engineer` |
| Message service | Validate + persist channel/DM messages with UUIDv7 id; idempotency by `Idempotency-Key`; edit/soft-delete (author-only); cursor history excluding soft-deleted; persist-then-publish (F38–F45, F51, ADR-0003/0004/0005) | New | `backend-engineer` |
| DM service | 1:1 DM send/history via `Message.recipient_id` + canonical user-pair key; self-DM rejection; participant-check authz (F46–F48, ADR-0002) | New | `backend-engineer` |
| WebSocket connection manager | Authenticate token before join; per-conversation subscribe/relay; **auto-subscribe each connection to its per-user topic `user:{id}` at connect and relay membership lifecycle events (F74/F75, ADR-0012)**; heartbeat + periodic revalidation; documented close codes; edit/delete/typing/presence event relay across instances (F51–F53, F56, F70) | New | `backend-engineer` |
| Presence service | Redis ref-counted online/offline across tabs/instances; heartbeat TTL expiry; durable `last_seen` write on last disconnect (F49–F50) | New | `backend-engineer` |
| Media / upload service | Size + allowlist validation; content sniffing; SVG exclusion; EXIF-strip-or-reject (images); filename sanitisation; boto3 put to bucket; membership-checked 5-min presigned GET; orphan cleanup job (F57–F62, ADR-0007) | New | `backend-engineer` |
| Rate limiter | Redis token-bucket: per-user message send (10/10s, burst 20); per-IP+identifier auth (5/5min, non-enumerating); per-user upload (20/min); `429` + `Retry-After` (F63–F64, F62) | New | `backend-engineer` |
| Invite service | System-Admin issue/revoke/resend/**list** single-use 7-day invites; email-locked registration; `410` on non-pending redemption; **paginated, status-filterable invite list (admin-only, no raw token, F71)**; audit events (F1–F7, F71, ADR-0010) | New | `backend-engineer` |
| Admin / bootstrap service | System-Admin deactivate/reactivate (session + WS invalidation, last-admin guard); **paginated, searchable user list (admin-only, no password material, F72)**; env-seeded non-skippable first-run System Admin (F8–F9, F25–F28, F72, ADR-0009) | New | `backend-engineer` |
| EmailService | Provider-agnostic async SMTP; invite + reset templates; inline send + bounded retry; fail-loud; non-enumerating reset failure handling (F1, F15, ADR-0010) | New | `backend-engineer` |
| React SPA | Auth flows, channels/DMs UI, **My Channels navigation list with live membership updates (F73–F75)**, optimistic send, live event rendering + client dedup, reconnect/catch-up banner, media render/download, **role-gated System Admin screens (Invite Management + User Management, F71/F72, PRD §11)**, WCAG 2.1 AA states (PRD §11) | New | `frontend-engineer` |
| Platform / infra | PaaS services (app ×1–2, Postgres, Redis), object-store + SMTP wiring, TLS, CORS, env secrets, backups + restore drill (ADR-0008) | New | `infrastructure-engineer` / `devops-engineer` |

## 4. Data model (design altitude)

Durable entities live in PostgreSQL; ephemeral presence lives in Redis. This section is at design altitude — **columns, types, constraints, and indexes are specified by `database-engineer` in the follow-up [`templates/database-design.md`](../../templates/database-design.md) instance**. Entities and relationships derive from the `CLAUDE.md` DOMAIN MODEL and the functional-spec §7 data dictionary.

**Entities & relationships**
- **User** (F5, F18–F28) — identity + profile; `role` (`system_admin` | `user`), `is_active`, durable `last_seen`, hashed password. Email + username **unique and immutable**. 1→N Channels (created_by), 1→N ChannelMember, 1→N Message (sender), 1→N Session, 1→N Invite (issued_by), 1→N PasswordResetToken.
- **Channel** (F29) — `name` (1–80 chars, workspace-unique), `is_private`, `created_by`. 1→N ChannelMember, 1→N Message.
- **ChannelMember** (F31–F36) — composite (channel_id, user_id); `role` (`member` | `admin`); `joined_at` drives earliest-join succession (F36).
- **Message** (F38–F45) — **UUIDv7 PK** (ADR-0005); exactly one of `channel_id` / `recipient_id` set (`CHECK`, ADR-0002); `sender_id`, `content`, authoritative `created_at`, `edited_at?`, `deleted_at?` (soft delete). Ordered by `(created_at, id)` for history + cursors (ADR-0003).
- **DM representation** (F46–F48, ADR-0002) — **no separate table**: a DM is a Message with `recipient_id` set and `channel_id` NULL; conversation identity = canonical unordered pair `(least, greatest)` of the two user ids; authz = participant check.
- **Invite** (F1–F7) — `email`, cryptographically-random single-use `token` (never returned/logged), `status` (`pending`/`used`/`revoked`/expired-by-TTL), `expiry` (7 days), `issued_by`.
- **PasswordResetToken** (F15–F17) — `user_id`, random single-use `token`, `expiry` (1 hour), `used`; only the latest issued token is valid.
- **Session** (ADR-0006) — `session_id`, `user_id`, **hashed** refresh token, issued/expiry (30-day sliding), `revoked_at?`, device/agent metadata; source of truth for revocation. Access JWTs carry `sid`.
- **Presence (Redis, ephemeral)** (F49–F50) — per-user ref-count + state with heartbeat TTL; **not** in Postgres. Durable `last_seen` lives on `User`.

**Migration strategy** — Greenfield: an initial Alembic migration creates the schema; there is no data migration (PRD §10). All future changes use **expand/contract**: (1) *expand* — add nullable columns / new tables / backfill in a non-breaking migration; (2) migrate reads/writes; (3) *contract* — drop the old shape in a later migration. Shipped migrations are **never edited** (`CLAUDE.md` boundaries) — only new migrations are added. Each migration must have a tested downgrade where feasible; irreversible operations (e.g. destructive drops) are called out for a human 🔒 review. `asyncpg` connection pooling per instance; PgBouncer only if connection counts warrant it (not expected at 1,000 users).

## 5. API contracts (design altitude)

Full request/response schemas, status-code matrices, cursor encoding, and the WebSocket event/close-code catalogue are owned by `api-reviewer` in the follow-up [`templates/api-contract.md`](../../templates/api-contract.md) instance. At design altitude:

**Transport & conventions (PRD §5b)**
- **REST (JSON)** for auth, invites, admin, profile, channels, membership, message CRUD/history, DM history, media upload/fetch. `Authorization: Bearer <access_token>` on protected routes.
- **WebSocket (WSS)** for real-time only: `message.created` / `message.edited` / `message.deleted`, **`channel.member_added` / `channel.member_removed` (per-user topic, F74/F75, ADR-0012)**, `typing`, `presence`. Token presented at connect; join only after auth (F52); the per-user topic is auto-subscribed server-side at connect.
- **Errors:** RFC 7807 `application/problem+json` with standard statuses (400/401/403/404/409/410/413/415/422/429), `Retry-After` on 429 (F70, F63–F64). WebSocket uses a **documented close-code/reason scheme** (F52, F70) — e.g. auth-failed, token-revoked, deactivated, going-away — catalogued in the API contract.
- **Idempotency:** `Idempotency-Key` header on message-create; a repeated key returns the original message, exactly one row (F40).
- **Pagination:** cursor-based `?limit=&cursor=` → `{ items, next_cursor }`; `next_cursor` null at end; opaque base64url cursor over `(created_at, id)` (F44, F48, F73, ADR-0003).
- **Timestamps:** ISO-8601 UTC; client renders local time. **Correlation id** on every response/log line, never PII (F68).

**Endpoint surface (indicative, not exhaustive)** — auth (`/auth/login|refresh|logout`), password reset (`/auth/password-reset` request + submit), invites (`/invites` issue/revoke/resend; **`GET /invites` list, admin-only, status-filterable, no raw token, F71**; `/register` via token), admin (`/admin/users/{id}/deactivate|reactivate`; **`GET /admin/users` list/search, admin-only, no password material, F72**), profile (`/me`, password change), channels (`/channels` create; **`GET /channels` my-channels list, caller-scoped, F73**; `/channels/public` browse; join/leave; membership + roles), messages (`/channels/{id}/messages` send/history; edit/delete), DMs (`/dms/{userId}/messages` send/history), media (`/media` upload; `/media/{id}/url` presigned fetch). Membership/participant authorization is enforced **server-side on every message read/write and media fetch** (F34, F59) — a client-supplied `channel_id` is never trusted alone.

## 6. Non-functional targets

| Attribute | Target |
|-----------|--------|
| Latency (p95) | **< 500 ms** send→visible real-time delivery at ~1,000 concurrent users (F65, PRD §7); REST reads (history, profile, channel list) p95 < 300 ms under the same load. Validated by load test before GA. |
| Throughput | **~1,000 concurrent users / WebSocket connections** on 1–2 FastAPI instances + 1 Postgres + 1 Redis; message send within the per-user rate limit (10 msg/10 s, burst 20). Not designed for hyperscale (constitution #7). |
| Availability | **≥ 99.5% monthly** (PRD §7). Single-instance-class datastores (1 Postgres, 1 Redis) with ≥2 stateless app instances behind the LB for app-tier redundancy; datastore failure is a degradation/outage event, not masked. |
| RTO / RPO | **RPO up to 24 h** (daily Postgres backups — accepted risk, spec §9); Redis loss has no durability requirement (ephemeral; `last_seen` is durable in Postgres). **RTO** bounded by PaaS restore + redeploy (target < 1 h); a **restore drill is mandatory before GA**. |
| Cost envelope | Small managed PaaS: 1–2 small app instances + one managed Postgres + one managed Redis + object storage + SMTP. Video egress (200 MB cap) is the main variable cost — **monitored**, revisited via ADR if usage grows (PRD §9). |

## 7. Failure modes & resilience

For each dependency: behaviour when slow/down, plus timeouts, retries, and idempotency.

- **PostgreSQL down/slow.** Postgres is the durable source of truth; if unavailable, writes (send/edit/delete, register, invite, membership) and history reads fail with `503`/RFC 7807 — no silent data loss (persist-then-publish means no live event is emitted for an uncommitted write, F45). Bounded statement timeouts on the `asyncpg` pool prevent request pile-up; the app returns fast errors rather than hanging. Session revocation checks fall back to Postgres if the Redis cache is cold, so a slow Postgres slows auth — mitigated by the Redis cache being the hot path (ADR-0006). No automatic failover in v1; recovery is via PaaS restore (RTO < 1 h target).
- **Redis down/slow (single-Redis SPOF, accepted §9).** Loses three functions at once: (a) **pub/sub fan-out** → live delivery stops, but messages still persist to Postgres and clients recover via reconnect catch-up from history (F55); (b) **presence** → presence goes stale/unavailable, but **no user falsely shows online** and durable `last_seen` in Postgres is unaffected (F50); (c) **rate limiting** → the limiter fails; policy is **fail-closed on abuse-sensitive endpoints** where feasible (reject/`429`) to avoid opening a brute-force window, degrading gracefully otherwise. The **session-revocation cache** falls back to Postgres (correctness preserved, latency up). REST/history remain available throughout. No Redis failover in v1.
- **Object store down/slow.** Uploads fail with a clear error (`503`); the message-create either is not attempted or leaves an orphan the cleanup job later removes (F62) — no partial "message with broken media" is presented as complete. Presigned-URL issuance fails → media shows as unavailable while text messaging continues unaffected. Bounded boto3 timeouts + limited retries; no retry storms.
- **One app instance down.** ≥2 stateless instances behind the LB; the LB routes around a failed instance. WebSocket clients on the dead instance are disconnected, auto-reconnect to a healthy instance (Flow K), re-subscribe via Redis, and catch up via history — at-least-once + client dedup makes reconnection safe (F54–F55). No session affinity is required because fan-out is Redis-mediated (ADR-0001/0004).
- **Email/SMTP down.** Invite send fails loudly to the admin (F1); reset send failure preserves the uniform response to the requester but raises a server-side audit/alert (F15, ADR-0010). Inline send with bounded retry — no silent queue-and-forget.
- **Cross-cutting guarantees.** **Persist-then-publish** (F45) ensures durability precedes broadcast; **at-least-once + client dedup by message id** (F54) tolerates duplicate delivery; **Idempotency-Key** (F40) makes retried sends produce exactly one row; **reconnect catch-up** (F55) is the universal recovery path for any missed live event.

## 8. Security & privacy

Threat surface is enumerated in the follow-up [`templates/threat-model.md`](../../templates/threat-model.md) instance, paired with `security-reviewer`.

- **AuthN.** Email+password login → short-lived access JWT (15 min, `sid` claim) + opaque refresh token (30-day sliding); JWT signing key from env via `pydantic-settings`, never committed/logged (R2/R24). Passwords hashed with bcrypt/argon2, never returned/logged (F5, F23). Registration only via valid invite (F6). Non-enumerating uniform responses on reset/invite/private-resource paths (F15, F64).
- **AuthZ.** Per-channel membership + role model; **server-side membership check on every channel message read/write and every media fetch** — a client `channel_id` is never trusted alone (F34, F59). DM authz is a participant check (ADR-0002). System Admin has invite + deactivate powers only, **no** channel/message access (F9). Message edit/delete is **author-only, no admin override** (F42–F43).
- **WebSocket.** Authenticate token **before joining any channel**; **periodic revalidation** drops revoked/expired/deactivated connections mid-connection at the next heartbeat with a documented close code (F52, ADR-0006).
- **Data classification.** Message content, DM content, media, and user PII (email, username, names, avatar, `last_seen`, presence) are **sensitive**. Invite/reset tokens, refresh tokens, JWTs, and password hashes are **secret**.
- **Secrets handling.** All secrets (JWT key, DB URL, Redis URL, SMTP creds, S3 creds, bootstrap admin credentials) via env / `pydantic-settings`, never committed (`CLAUDE.md` boundaries). Media hygiene: allowlist + size caps + content sniffing + SVG exclusion + EXIF-strip-or-reject + filename sanitisation + separate serving origin (F58–F62); **no AV scanning** (accepted risk).
- **Logging.** **No** raw message/DM content, JWTs, invite tokens, reset tokens, refresh tokens, secrets, or PII in logs (F68/R24). Security-relevant **audit events** (invite issuance/redemption, deactivation/reactivation, reset requests) are logged **without** sensitive payloads (F69). Correlation id on every line.
- **Transport.** TLS everywhere in production (terminated at the PaaS LB, F67); CORS restricted to known frontend origin(s), no wildcard in prod (F66).

## 9. Observability

- **Structured logging.** JSON logs with a correlation/request id on every line; **never** content/tokens/secrets/PII (F68). Audit events for invite issuance/redemption, deactivation/reactivation, and reset requests, content-free (F69).
- **Key metrics.** Active WebSocket connections (per instance + total); message send throughput and error rate; **real-time delivery lag** (send→publish→relay) as the primary latency SLI (F65); rate-limit rejections (`429` counts by endpoint class); presence gauge; media upload success/reject counts; email send success/failure; DB pool saturation; Redis availability.
- **SLIs / SLOs.** SLI: p95 delivery latency → SLO < 500 ms at ~1,000 users. SLI: message send success (excl. rate-limit) → SLO ≥ 99.9%. SLI: uptime → SLO ≥ 99.5% monthly. SLI: unauthenticated WS join attempts rejected → 100%.
- **Alerts (symptom-based).** Error-rate spike; uptime-probe failure; delivery-latency SLO breach; Redis unreachable (degrades live delivery/presence/rate-limit); DB pool exhaustion; email send-failure rate; backup job failure.
- **Error monitor.** A Sentry-class error/uptime monitor (PRD §11) — no full metrics stack at this scale unless usage grows materially (constitution).

## 10. Rollout & migration

- **Greenfield initial deploy.** No data migration; an initial Alembic migration creates the schema (PRD §10). **Phase 0 hard prerequisites** (non-skippable): transactional email configured (ADR-0010) + env-seeded System Admin bootstrapped (ADR-0009) — the app **fails loud at startup** if either is missing.
- **Phased delivery** (PRD §10): (1) invite auth + accounts/profile → (2) channels + membership + succession → (3) messaging + history → (4) media (post ADR-0007) → (5) real-time delivery + presence + live edit/delete → (6) DMs + typing → (7) rate limiting + hardening → GA behind 🔒 gates.
- **Feature flags.** Gate typing indicators (F56), DMs (F46–F48), media (F57–F62), and live edit/delete propagation (F42–F43) behind flags so the core loop ships first if an ADR/hardening lags. **Invite-based registration and System Admin bootstrap are NOT flaggable** — they are prerequisites for any user to exist.
- **Future migrations.** Expand/contract Alembic pattern (see §4); shipped migrations never edited; irreversible steps flagged for human 🔒 review.
- **Rollback.** App tier: redeploy the previous container image (stateless instances make this clean). Schema: expand/contract means a new deploy is backward-compatible with the prior app version during the expand phase, so an app rollback does not require a schema rollback. Destructive contract migrations are gated behind human approval and only applied once the prior app version is retired.

## 11. Alternatives considered

Summarised here; full reasoning in the ADRs.
- **Architecture style** — microservices / split WS tier vs modular monolith → chose the monolith at 1,000-user scale ([ADR-0001](../../architecture/adr/0001-modular-monolith-fastapi.md)).
- **DM model** — reuse `channels` as 2-member private channel vs dedicated `recipient_id` → chose the dedicated model matching the domain model ([ADR-0002](../../architecture/adr/0002-dm-data-model.md)).
- **Pagination** — offset vs keyset/cursor → chose cursor for stability + performance ([ADR-0003](../../architecture/adr/0003-cursor-pagination.md)).
- **Delivery correctness** — transactional outbox / message queue vs plain persist-then-publish → chose plain persist-then-publish + reconnect catch-up, outbox deferred to load-test findings ([ADR-0004](../../architecture/adr/0004-realtime-delivery-fanout.md)).
- **Message id** — bigint / UUIDv4 / ULID vs UUIDv7 → chose UUIDv7 (time-sortable, native pg `uuid`) ([ADR-0005](../../architecture/adr/0005-message-id-scheme.md)).
- **Sessions** — per-user token-version / short-TTL-only vs session store + Redis revocation → chose the session store for per-session revocation ([ADR-0006](../../architecture/adr/0006-revocable-sessions.md)).
- **Media** — direct-to-bucket / Postgres bytea vs validate-through-app S3-compatible + signed URLs → chose validate-through-app ([ADR-0007](../../architecture/adr/0007-media-object-storage.md)).
- **Deployment** — single Docker host / Fly / Railway vs Render → recommend Render ([ADR-0008](../../architecture/adr/0008-deployment-target.md)).
- **Bootstrap** — web wizard / CLI vs env-seed at startup → chose env-seed ([ADR-0009](../../architecture/adr/0009-system-admin-bootstrap.md)).
- **Email** — provider-API SDK / queue-and-forget vs SMTP abstraction + inline fail-loud → chose SMTP abstraction ([ADR-0010](../../architecture/adr/0010-transactional-email.md)).

## 12. Risks

| Risk | Likelihood | Impact | Mitigation | Owner |
|------|-----------|--------|------------|-------|
| Single-Redis SPOF — loses pub/sub fan-out, presence, and rate-limit simultaneously | Medium | High | Accepted for v1 (§9); REST/history survive from Postgres; reconnect catch-up recovers missed live events; session-revocation cache falls back to Postgres; revisit failover via ADR on real usage | architect / devops |
| Backup RPO up to 24 h; untested restore | Medium | High | Daily backups accepted; **mandatory restore drill before GA**; consider PITR tier on Render | devops / infrastructure |
| No AV/malware scanning on uploads | Medium | Medium-High | Accepted risk; mitigations = allowlist + content sniff + SVG exclusion + EXIF-strip + filename sanitise + separate origin (F58–F62); revisit if abuse observed | security-reviewer / product |
| Zero-admin frozen channel (sole admin leaves, no members) is a permanent terminal state | Low-Medium | Low-Medium | Accepted for v1 (§9); channel persists frozen (no membership/role change) until a future moderation feature; documented so operators are aware | product / architect |
| Media revocation lag — access persists up to the 5-min signed-URL TTL after membership ends | Medium | Medium | Bounded to 5 min by short TTL (F59); membership checked at issuance against **current** membership; documented privacy boundary | security-reviewer / backend |
| Mid-connection revocation lag — WS drop on logout/revoke/deactivation occurs at next heartbeat, not instantly | Medium | Medium | Bounded by heartbeat/revalidation interval (F52, ADR-0006); interval chosen small enough to keep the window short; REST revocation is near-immediate via Redis check | backend / security-reviewer |
| Dual-write gap — Postgres commit succeeds but Redis publish fails → missed live event | Medium | Medium | Persist-then-publish + at-least-once + client dedup + reconnect/periodic-resync catch-up (F45/F54/F55); promote to transactional outbox (ADR-0004) if load tests show loss | architect / backend |
| Combined REST+WS on one instance — WS connection storm pressures REST latency | Medium | Medium | ≥2 instances behind LB; per-user rate limits (F63); load-test the combined envelope before GA; module seams allow WS-tier extraction later (ADR-0001) | performance-engineer / backend |
| Transactional email is a hard first-run dependency with no fallback if misconfigured | Medium | High | Fail-loud at startup (ADR-0009/0010); documented as a first-run prerequisite; inline send + bounded retry; reset failures alert operator without breaking non-enumeration | devops / architect |
| Video storage/egress cost growth (200 MB cap) | Medium | Medium | Size caps; no transcoding; monitor egress metric; ADR if usage grows | performance / architect |
| ~1,000-user target unvalidated | Medium | Medium | Load/stress test the full REST+WS+fan-out path across 2 instances before GA (F65) | performance-engineer |
| Rate-limit tuning (auth keying, thresholds) mis-set — false blocks or weak protection | Medium | Medium | Token-bucket params per §5a validated under load; non-enumerating auth keying (per-IP + identifier) reviewed | backend / performance |

---
🔒 **Approval gate:** human architecture sign-off before implementation.
