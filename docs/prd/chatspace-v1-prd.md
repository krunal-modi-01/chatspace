# PRD — chatspace v1 (Final)

> Owner: `product-manager` agent (+ human PM approval). Downstream: `business-analyst`, `architect`.
> Status: Approved · Ticket: <link> · Last updated: 2026-07-02 · Version: 1

---

## 0. Terminology (normative)

- **Workspace** — the single logical tenant served by one deployment. **Confirmed: single workspace per deployment** (no multi-tenancy in v1).
- **User** — a registered, authenticated identity within the workspace.
- **System Admin** — a workspace-level role (not per-channel) that can invite new users and deactivate/reactivate user accounts. At least one always exists.
- **Channel** — a public or private conversation space with a membership list.
- **Channel Member** — a user in a channel's membership list; may read/write that channel.
- **Channel Admin** — a channel member with the `admin` role for that channel; per-channel only; distinct from System Admin.
- **Message Author** — the user who created a given message.
- **Workspace Operator** — the human who self-hosts/runs the deployment infrastructure (not necessarily the same person as a System Admin, though the bootstrap System Admin is typically created by the operator).
- **Invite** — a single-use, time-limited token tied to a specific email address, created by a System Admin, that permits registration.
- **DM** — a 1:1 direct message between exactly two distinct users.
- **Presence** — a user's live availability state: `online` / `offline`, plus `last_seen`.
- **Soft delete** — marking a row `deleted_at` and hiding its content while retaining the row.

"Must / Should / May" follow RFC 2119. "Media" = images, non-media files, and video collectively.

---

## 1. Problem & context

Small and mid-size teams need a real-time place to talk that they control, without
adopting a heavyweight commercial suite. Email is too slow for back-and-forth
conversation, and general-purpose tools scatter discussion across DMs, threads, and
inboxes with no shared, channel-based history.

**chatspace** is a self-hostable, Slack-style team-chat product: authenticated users
organize conversation into public and private **channels**, exchange **direct
messages**, see who is **online**, and get **messages delivered in real time**. v1
establishes the core communication loop — auth, channels, messaging, DMs, presence,
real-time delivery, and abuse rate limiting — as the foundation everything later
builds on.

**Why now.** The project has an operating constitution (`CLAUDE.md`), a defined domain
model, security requirements, and a full delivery pipeline, but no product-level PRD.
Before any technical design or ADR work begins, we need one authoritative, testable
statement of what v1 must do so downstream roles (`business-analyst`, `architect`,
`qa-engineer`) execute against intent rather than guessing it.

**Evidence framing.** Demand is assumed from the product thesis (teams want a
controllable Slack alternative), not yet from field data. v1 is explicitly scoped to
**~1,000 concurrent users** — a single well-run deployment, not hyperscale — so we can
ship the core loop, then let real usage data drive further investment (recorded as
ADRs, not guesses).

**Tenancy.** One deployment serves exactly one workspace. All entities are
workspace-global; there is no `workspace_id` column and no cross-workspace concept in v1.

## 2. Goals / non-goals

**Goals (measurable outcomes this must achieve):**

- Deliver the complete core communication loop for v1: invite-based registration and
  authentication, user profiles, channels, messaging (including media attachments),
  direct messages, presence, real-time delivery + typing indicators, and rate limiting.
- Give every user a profile they own: view/edit display name and avatar, change their
  password (self-service, including forgot-password recovery), and log out.
- Let any authenticated user create channels (public or private) and become that
  channel's admin — no System Admin gatekeeping on channel creation.
- Give a System Admin the ability to invite new users and deactivate/reactivate an
  account, so the workspace has a controlled entry point and a basic abuse lever.
- Sustain **~1,000 concurrent users** on a single deployment (1–2 FastAPI instances +
  one Postgres + one Redis) with real-time message delivery.
- Enforce the chat-specific security bar (§8, §6): authenticated access only,
  server-side membership checks on every channel/media read-write, no secrets/PII/
  message content in logs, revocable sessions, verified-email invite-based entry.
- Produce requirements that are individually testable (every requirement has
  Given/When/Then acceptance criteria the `qa-engineer` can verify).

**Non-goals (explicitly out of scope for v1 — prevents scope creep):**

- Server-side media *processing*: video transcoding, image resizing/thumbnail
  generation, and format conversion. Media content is stored and served **as-is**.
  *(EXIF metadata stripping on images is treated as security hygiene, not "processing," and IS in v1 — see R42.)*
- Anti-malware / antivirus scanning of uploaded media — **explicitly deferred**, accepted
  risk for v1 (see §9 Risks).
- Editing **email or username** after registration (display name and avatar are
  editable; email/username are fixed in v1).
- Open, un-invited self-registration — **all registration requires a System-Admin-issued
  invite** (see R1/R45).
- Message threads, emoji reactions, message pinning, and full-text search. *(Browsing a
  list of public channels is NOT full-text search and IS in v1 — see R49.)*
- Channel archiving or deletion (a channel, once created, persists indefinitely; it may
  become admin-less per R51 but is never auto-removed).
- DM blocking and a dedicated moderation console/audit-log UI — deferred beyond
  System-Admin account deactivation and author-only message deletion.
- Channel-admin or System-Admin authority to delete **other users'** messages —
  deferred to a future version; v1 message deletion is **author-only, no override**.
- Native or cross-platform **mobile client** (web-only for v1; responsive behavior on
  mobile browsers is in scope, see §11).
- Group DMs (>2 participants); v1 DMs are 1:1 only.
- Horizontal-scaling complexity: sharding, message-queue cluster (Kafka/RabbitMQ),
  multi-region, exactly-once delivery guarantees.
- Kubernetes / AWS / Terraform deployment tooling.
- SSO / OAuth / third-party identity providers (v1 is email + password only).
- Multi-workspace / multi-tenancy.

## 3. Target users & personas

**Primary — Team Member ("Maya").** A member of a workspace who lives in channels and
DMs all day. Wants to send/read messages instantly, fix typos, know who's around, and
recover her own account via self-service password reset if she forgets her password.
Non-technical; expects it to "just work."

**Primary — Channel Creator/Admin ("Devin").** Any team member can spin up a channel
for a topic or an ad-hoc group; whoever creates it becomes its admin. As an admin,
Devin decides public vs private and manages who's in the channel and their roles.
Admin rights are **per-channel** (owned by the creator), not a global privilege. If
Devin is the only admin of a channel and leaves or is deactivated, the longest-standing
remaining member is automatically promoted (R51).

**New — System Admin ("Priya").** A workspace-level role, not tied to any one channel.
Priya invites new teammates by email (the only way into the workspace) and can
deactivate an account if someone leaves the company or misbehaves — and reactivate it
later if needed. Priya does **not** have any special power over channels or messages;
she cannot read private channels she's not a member of or delete other users' messages.
A default System Admin account is created automatically at first deployment ("bootstrap
admin") so the workspace is never in a state with zero admins and no way to invite anyone.

**Secondary — Workspace Operator ("Sam").** Self-hosts and runs the deployment (often
also the bootstrap System Admin, but not necessarily the same person going forward).
Cares that it stays up for ~1,000 concurrent users, that secrets and message content
never leak into logs, and that abuse (spam, brute-force login) is throttled. Interacts
with the product mostly through its operational and security guarantees.

## 4. User stories

**Registration & invites**
- As a System Admin, I want to **invite a new user by email** so that only people I
  choose can join the workspace.
- As an invited person, I want to **open my invite link and register** (name, username,
  password, optional avatar) so that I get an account without a separate email-verification step.
- As a System Admin, I want to **revoke or resend an unused invite** so that I can
  correct a mistake or handle an expired invite.
- As the operator, I want a **default System Admin account created automatically** at
  first deployment so I'm never locked out of inviting the first real users.

**Authentication & session**
- As a returning user, I want to **log in and receive an access token (JWT) plus a
  refresh token** so that I can use the app securely without a very long-lived token.
- As a user, I want to **log out** so that my session can no longer be used.
- As a user who forgot my password, I want to **request a password-reset email and set
  a new password** so that I am not permanently locked out.

**User profile**
- As a team member, I want to **view my profile** (name, username, email, avatar) so
  that I can see how I appear to others.
- As a team member, I want to **edit my display name and profile picture** so that I
  keep my identity current.
- As a team member, I want an **initials badge** shown automatically when I haven't set
  a profile picture so that I still have a visual identity.
- As a team member, I want to **change my password** (confirming my current one) and
  expect **other sessions to be logged out**, so I can keep my account secure.
- As a team member, I want to **see other users' names and avatars** next to their
  messages so that I know who said what.

**System Admin — account management**
- As a System Admin, I want to **deactivate a user's account** so that they can no
  longer log in or use active sessions.
- As a System Admin, I want to **reactivate a previously deactivated account** so that
  a returning teammate can regain access.

**Channels**
- As a team member, I want to **create a public or private channel** so that my team
  (or an ad-hoc group) has a dedicated space — and I become its admin.
- As a team member, I want to **browse a list of public channels** so I can find one to join.
- As a team member, I want to **join a public channel** so that I can participate.
- As a team member, I want to **leave a channel** I no longer need.
- As a channel admin, I want to **add/remove members of my channel and assign
  member/admin roles** so that access is controlled.
- As a channel member, I expect that **if my channel's only admin leaves or is
  deactivated**, the longest-standing remaining member is automatically promoted to
  admin, so the channel is never stuck without one.
- As a team member, I want to be **prevented from reading or posting to channels I'm
  not a member of** so that private conversations stay private.

**Messaging**
- As a team member, I want to **send a message to a channel** so that my team sees it.
- As a team member, I want to **attach an image, file, or video to a message** (in a
  channel or DM) so that I can share media, not just text.
- As a team member, I want **images and videos to render inline when the browser can
  play them, and other files to appear as downloadable attachments**.
- As a team member, I want to **edit my own message**, and have that edit **appear live**
  for everyone currently viewing it, so that corrections are visible immediately.
- As a team member, I want to **delete my own message (soft delete)**, and have that
  deletion **appear live** for everyone currently viewing it.
- As a team member, I want to **load a channel's message history** so that I can catch
  up on what I missed.
- As a team member returning after a disconnect, I want to **catch up on messages I
  missed while offline**.

**Direct messages**
- As a team member, I want to **send a 1:1 direct message to another user**.
- As a team member, I want to **see my DM history with a person**.

**Presence**
- As a team member, I want to **see whether others are online, offline, or their
  last-seen time**.

**Real-time delivery & typing indicators**
- As a team member, I want **new messages, edits, and deletions to appear in real time
  without refreshing** so that conversation feels live and never stale.
- As a team member, I want to **see when someone is typing** in a channel or DM.

**Rate limiting & abuse**
- As a workspace operator, I want **rate limits on message sending and auth endpoints**
  so that spam and brute-force attempts are throttled.

## 5. Requirements

| ID | Requirement | Priority (MoSCoW) | Notes |
|----|-------------|-------------------|-------|
| R1 | User registration with email (pre-filled from a valid invite, not freely entered), username, password, **first & last name (required)**, optional avatar; password hashed (bcrypt/argon2); passwords never returned/logged | Must | Registration is **only** reachable via a valid, unused, unexpired invite (R45). Email is auto-verified via the invite. Email/username **unique** (DB constraint). |
| R2 | User login issuing a short-lived **access token (JWT)** + a **refresh token** | Must | JWT signing key from env via `pydantic-settings`, never committed/logged. TTLs per §5a. |
| R3 | Authenticated REST access — protected endpoints reject missing/invalid/expired tokens | Must | Applies to all non-auth REST routes. |
| R4 | Any authenticated, active user can create a channel (public or private); creator becomes that channel's admin | Must | No System-Admin gate on channel creation. |
| R5 | Join a public channel directly; join/add to a private channel is admin-gated | Must | Discovery via R49; leave via R50. |
| R6 | Per-channel membership with roles (member/admin); a channel's admins manage that channel's membership and roles | Must | Per-channel, not global. Succession: R51. |
| R7 | Server validates channel membership on every message read/write and every media fetch — never trust client-supplied channel_id alone | Must | Security-critical. |
| R8 | Send a message to a channel | Must | Validation: R36. |
| R9 | Edit own message; records edited_at; only the author may edit; **edit is broadcast live** to connected clients | Must | Author-only. Live propagation: R52. |
| R10 | Soft-delete own message via deleted_at; **deletion is broadcast live**; deleted messages are hidden but retained | Must | **Author-only — no Channel Admin or System Admin override in v1** (deferred; see non-goals). Live propagation: R52. |
| R11 | Retrieve channel message history (chronological, excludes soft-deleted content), cursor-based pagination | Must | Cursor on message id (R39); ADR confirms encoding — §12. |
| R12 | Send a 1:1 direct message between two distinct users (self-DM rejected) | Must | DM data model — ADR, §12. |
| R13 | Retrieve 1:1 DM history, cursor-based pagination | Must | Same mechanics as R11. |
| R14 | Presence: live online/offline in Redis (ephemeral); `last_seen` persisted durably (Postgres) | Must | See R43/R44. |
| R15 | Real-time delivery of new messages, edits, and deletions over WebSocket without refresh | Must | Extended in this revision to include edits/deletes (was new-message-only in v2). |
| R16 | WebSocket authenticates via access token before joining any channel; re-validated periodically so revoked/expired/deactivated-user tokens are dropped mid-connection | Must | Ties to R35, R47 (deactivation). |
| R17 | Real-time broadcast works across >1 app instance via Redis pub/sub fan-out | Must | Includes edit/delete events (R52). |
| R18 | At-least-once **delivery** with client-side dedup by message id | Must | Duplicate *creation* handled by R38. |
| R19 | Typing indicators for channels and DMs over WebSocket | Should | Ephemeral, auto-expiring. |
| R20 | Token-bucket rate limiting: per-user on message send; **per-IP + per-attempted-identifier** on auth endpoints (login, register-via-invite, password-reset request, refresh) | Must | Must not enable user enumeration. Defaults §5a. |
| R21 | Support ~1,000 concurrent users on 1–2 FastAPI instances + single Postgres + single Redis | Must | NFR: scale ceiling. |
| R22 | CORS restricted to known frontend origin(s); no wildcard in production | Must | NFR: security. |
| R23 | All production traffic over TLS | Must | NFR: security. |
| R24 | Never log raw message content, JWTs, invite tokens, or reset tokens; no secrets/PII in logs (secret-scan hook enforced) | Must | NFR: security/privacy. |
| R25 | Structured JSON logging + uptime/error monitoring + lightweight latency instrumentation for the §7 delivery metric | Should | NFR: observability. |
| R26 | View own profile: first/last name, username, email, avatar | Must | |
| R27 | Edit own profile: first name, last name, avatar; email/username immutable | Must | |
| R28 | Avatar fallback: initials badge (first + last initial) when no avatar set | Must | Applies everywhere a user is rendered. |
| R29 | Change password: require current password; hash new password; **invalidate the user's other active sessions** | Must | Depends on R35. |
| R30 | Attach media to messages (channels and DMs): images, files, video | Must | Storage backend — ADR, §12. |
| R31 | Media validation: max file size + content-type allowlist per media type; sniffed content must match declared type; **SVG excluded** from image allowlist | Must | Defaults §5a. |
| R32 | Media served from a **separate origin/bucket** via short-TTL signed URLs, authorized against **current** channel/DM membership; access revoked within the signed-URL TTL after membership ends | Must | |
| R33 | Images/video render inline/playable when the browser can decode the format; otherwise (and for all other files) a downloadable attachment with filename and size; **no server-side transcoding** | Should | |
| R34 | Logout — invalidate the current session's access + refresh tokens server-side | Must | Depends on R35. |
| R35 | **Revocable sessions** — short-lived access token + refresh token; server can invalidate a session (logout, password change/reset, System-Admin deactivation). Mechanism is an architect ADR | Must | §12 Open Decision #5. |
| R36 | Input validation: message body non-null/non-whitespace/≤ max length; channel name length + character rules; edit only while not deleted; edit never changes id/ordering | Must | Defaults §5a. |
| R37 | Password policy: minimum length + basic strength rule; enforced on registration, password change, and password reset | Must | Defaults §5a. |
| R38 | Send idempotency via client-supplied `Idempotency-Key` on message-create; a repeated key returns the original message, no duplicate row | Must | |
| R39 | Message identity & ordering: server-assigned, globally-unique, time-sortable id (ULID/UUIDv7 recommended); server `created_at` authoritative; ties broken by id | Must | |
| R40 | Delivery ordering: **persist-then-publish**; reconnecting clients catch up via history using the last received message id; transactional outbox is an acceptable ADR choice | Must | Resolves dual-write pitfall. |
| R41 | Standard error responses: RFC 7807 `application/problem+json` for REST; documented WebSocket close-code/reason scheme | Must | §5b. |
| R42 | Media hygiene: filename sanitization (no path traversal/active-content extensions served inline); **strip EXIF metadata from uploaded images**; per-user upload rate limit; orphaned-media cleanup | Must | AV/malware scanning explicitly **deferred** — accepted risk (§9). |
| R43 | Presence connection model: `online` if ≥1 live WebSocket exists, ref-counted across tabs/instances via Redis; heartbeat + TTL expires stale connections | Must | |
| R44 | `last_seen` durability: written to Postgres on disconnect so it survives Redis restart | Must | |
| R45 | **Invite issuance** — a System Admin creates an invite tied to a specific email address; the system emails an invite link containing a single-use, time-limited token | Must (new) | Default expiry/reuse rules: §5a. A System Admin may **revoke** an unused invite or **resend** it (issuing a new token, invalidating the old one). |
| R46 | **System Admin role & bootstrap** — a workspace-level role, separate from Channel Admin, granted only R45 (invite) and R47 (deactivate/reactivate) powers; **no** special channel/message access. Exactly one default System Admin account is created automatically at first deployment (bootstrap), so an invite-issuer always exists | Must (new) | Bootstrap mechanism (env var / first-run CLI / setup wizard) is an architect decision; must not be skippable, to avoid a zero-admin deployment. |
| R47 | **User deactivation/reactivation** — a System Admin can deactivate an active user (blocks login, invalidates all of that user's active sessions immediately, drops open WebSocket connections) and reactivate a deactivated user (restores login ability; does not restore old sessions) | Must (new) | A deactivated user's prior messages/channel memberships are **retained as-is** (not deleted, not anonymized) — Assumption, confirm with PM if different retention is wanted. |
| R48 | **Self-service password reset** — a user requests a reset via their registered (verified) email; the system emails a single-use, time-limited reset link; submitting a new password via a valid link sets it and **invalidates all of the user's other active sessions** (same effect as R29) | Must (new) | Must not reveal whether an email exists in the system (uniform response). Default token expiry §5a. |
| R49 | **Browse public channels** — an authenticated, active user can retrieve a list of public channels (name; member count optional) they are not yet a member of, and join directly from it | Must (new) | Not full-text search — a plain list, pagination per §5b if the list is large. |
| R50 | **Leave a channel** — any member (including an admin) may leave a channel they belong to | Must (new) | If the leaving member is the channel's only admin, R51 applies before membership is removed. |
| R51 | **Last-admin succession** — when a channel's only admin leaves (R50) or is deactivated (R47), the system automatically promotes the **longest-standing remaining member** (earliest `joined_at`) to admin. If no other members remain, the channel persists with **zero admins** (not archived, not deleted) | Must (new) | A channel with zero admins cannot have its membership/roles changed until it regains an admin via this rule or via a future moderation feature. |
| R52 | **Live propagation of edits/deletes** — when a message is edited or soft-deleted, all clients with an open WebSocket to that channel/DM receive an update event (not just new-message events) and update their view without a refresh | Must (new) | Same transport/fan-out as R15/R17; extends R9/R10. |
| R53 | **EXIF metadata stripping** — uploaded images have EXIF metadata (including GPS location) stripped server-side before storage; the visual image content itself is not otherwise altered (not "processing" per the non-goals) | Must (new) | Applies to the image allowlist only (R31); does not apply to video or file attachments. |

### §5a — Configurable limits (defaults; confirm/tune during design — not open product questions)

| Setting | Default | Notes |
|---|---|---|
| Password minimum length | 6 chars | R37. |
| Message body max length | 4,000 chars | R36. |
| Channel name | 1–80 chars; letters, digits, spaces, `-`, `_`; unique within workspace | R36. |
| Message edit window | Unlimited (author only, until deleted) | R9/R36. |
| Access-token TTL | 15 min | R35. |
| Refresh-token TTL | 30 days (sliding) | R35. |
| Invite token TTL | **7 days**, single-use | R45. |
| Password-reset token TTL | **1 hour**, single-use | R48. |
| Message send rate limit | 10 msg / 10 s / user (burst 20) | R20. |
| Auth endpoint rate limit | 5 attempts / 5 min per IP + identifier | R20; `429`, no enumeration. |
| Media max size — image | 10 MB | R31. |
| Media max size — file | 50 MB | R31. |
| Media max size — video | 200 MB | R31; cost-monitored (§9). |
| Image content-type allowlist | `image/png`, `image/jpeg`, `image/gif`, `image/webp` (**no `image/svg+xml`**) | R31. |
| Video content-type allowlist | `video/mp4`, `video/webm` | R31/R33. |
| Signed media URL TTL | 5 min | R32; defines media revocation-lag bound. |
| Per-user upload rate limit | 20 uploads / min | R42. |
| Typing-indicator auto-expire | 5 s after last keystroke | R19. |
| Public-channel list page size | 50 (paginated per §5b if more) | R49. |

### §5b — API & error-format expectations (normative baseline)

- **Transport.** REST (JSON) for CRUD/history/auth/invites/admin actions; WebSocket for real-time only.
- **Auth header.** `Authorization: Bearer <access_token>` on protected REST routes; WebSocket presents the access token at connect per R16.
- **Errors.** RFC 7807 `application/problem+json` (R41). Standard statuses: `400` validation, `401` unauthenticated, `403` unauthorized, `404` not-found/not-authorized-to-know (uniform, §7), `409` conflict (duplicate email/username, idempotency mismatch, invite already used), `410` gone (expired/revoked invite or reset token), `413` payload too large, `415` unsupported media type, `422` semantic validation, `429` rate-limited (`Retry-After`).
- **Pagination.** Cursor-based: `?limit=&cursor=` → `{ items, next_cursor }`.
- **Idempotency.** `Idempotency-Key` header on message-create (R38).
- **Timestamps.** ISO-8601 UTC; client renders local timezone.
- **Correlation id.** Every response/log line carries a request id (never PII).

### §5c — Permission matrix

| Action | Unauth | Invited (pre-registration) | Auth user (non-member) | Channel Member | Channel Admin | Message Author | System Admin |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| Register (via valid invite only) | ❌ | ✅ | — | — | — | — | — |
| Issue / revoke / resend an invite | ❌ | ❌ | ❌ | ❌ | ❌ | — | ✅ |
| Login / logout / password reset | — | — | ✅ | ✅ | ✅ | ✅ | ✅ |
| View/edit own profile, change password | — | — | ✅ | ✅ | ✅ | ✅ | ✅ |
| Deactivate / reactivate a user | ❌ | ❌ | ❌ | ❌ | ❌ | — | ✅ |
| Create a channel | — | — | ✅ | ✅ | ✅ | — | ✅ |
| Browse / join a public channel | — | — | ✅ | ✅ | ✅ | — | ✅ |
| Leave a channel | — | — | — | ✅ | ✅¹ | — | — |
| Read/post in a channel | ❌ | — | ❌ | ✅ | ✅ | — | — |
| Add/remove members, set roles (own channel) | — | — | ❌ | ❌ | ✅ | — | — |
| Edit a message | — | — | ❌ | ❌ | ❌ | ✅ (own) | ❌ |
| Soft-delete a message | — | — | ❌ | ❌ | ❌ | ✅ (own only) | ❌ |
| Send/read DM with a user | — | — | ✅² | ✅² | ✅² | — | ✅² |

¹ Leaving as the sole admin triggers auto-succession (R51) before membership is removed.
² Any two distinct active users; no DM blocking in v1.

## 6. Acceptance criteria

**R1 / R45 — Invite-based registration**
- Given a System Admin issues an invite for `alice@co.com`, When the invite is created, Then a single-use token is generated, tied to that email, with a 7-day expiry, and an email is sent to that address.
- Given a valid, unused, unexpired invite link, When opened, Then the registration form pre-fills/locks the email to the invited address and allows registration.
- Given an invite token that is expired, already used, or revoked, When registration is attempted, Then it is rejected with `410 Gone`.
- Given successful registration via a valid invite, Then the account's email is marked verified with no separate verification step, and the invite token is marked used (cannot be reused).
- Given a System Admin revokes an unused invite, When the original link is later opened, Then it is rejected (`410`); Given a System Admin resends an invite, Then a new token is issued and the old one is invalidated.
- Given no invite / an invalid token, When a registration request is made directly to the API, Then it is rejected — there is no invite-less registration path.

**R46 — System Admin bootstrap**
- Given a fresh deployment with no users, When the app starts for the first time, Then exactly one default System Admin account is created automatically, without requiring any prior invite.
- Given the bootstrap System Admin exists, Then they can immediately issue invites (R45).

**R47 — Deactivation/reactivation**
- Given a System Admin deactivates an active user, Then that user's active sessions (access + refresh tokens) are invalidated immediately, any open WebSocket connections are dropped within the R16 re-validation window, and subsequent login attempts are rejected.
- Given a System Admin reactivates a deactivated user, Then that user can log in again (fresh session; prior sessions are not restored).
- Given a deactivated user's prior messages and channel memberships, Then they remain visible/intact (not deleted or anonymized).
- Given a System Admin attempts to deactivate the **last remaining active System Admin**, Then the action is rejected with a clear error (the workspace must always retain ≥1 active System Admin).

**R2 / R3 / R35 — Login, tokens, authenticated access**
- Given valid credentials for an **active** account, When a user logs in, Then a short-lived access token and a refresh token are returned.
- Given valid credentials for a **deactivated** account, When login is attempted, Then it is rejected.
- Given invalid credentials, Then the request is rejected without revealing which field was wrong.
- Given a protected endpoint called with a missing/invalid/expired token, Then `401` and no protected data returned.
- Given a valid refresh token, When exchanged, Then a new access token is issued; an invalidated refresh token fails with `401`.

**R34 — Logout**
- Given a logged-in user, When they log out, Then the current session's tokens can no longer authenticate any request.

**R48 — Password reset**
- Given a user requests a reset for an email that exists, Then a single-use, 1-hour-expiry reset link is emailed; Given the email does not exist, Then the same generic response is returned (no enumeration).
- Given a valid, unused, unexpired reset link, When a new (policy-compliant) password is submitted, Then it is set and **all of the user's other active sessions are invalidated**.
- Given an expired or already-used reset link, When submission is attempted, Then it is rejected with `410`.
- Given multiple reset requests in quick succession, Then only the most recently issued token is valid; earlier ones are invalidated.

**R4 / R5 / R6 / R49 / R50 / R51 — Channels & membership**
- Given any active authenticated user, When they create a channel, Then it's stored with creator, visibility, created_at, and the creator is recorded as admin.
- Given the public-channel list, When requested, Then it returns public channels the requester is not yet a member of, paginated.
- Given a public channel, When a member requests to join, Then they become a member.
- Given a private channel, When a non-admin attempts to add themselves/others, Then rejected (`403`); When a channel admin adds/removes/changes roles, Then applied.
- Given a member, When they leave a channel, Then their membership is removed; Given they were the sole admin, Then the longest-standing remaining member is promoted to admin **before** their membership is removed; Given no other members remain, Then the channel persists with zero admins.
- Given a deactivated user who was a channel's sole admin, Then the same succession rule (R51) applies.

**R7 — Membership authorization**
- Given a non-member, When they attempt to read/post to a channel (even with a valid channel_id), Then rejected based on server-side membership.

**R8 / R9 / R10 / R11 / R36 / R38 / R39 / R52 — Messaging**
- Given a channel member, When they send a valid message, Then it is persisted (R40), assigned a sortable id, and delivered in real time (R15).
- Given an empty/whitespace/over-length body, Then rejected `422`, nothing persisted.
- Given a retried send with the same `Idempotency-Key`, Then exactly one message row exists.
- Given a message the user authored, When edited, Then content updates, edited_at is set, id/order unchanged, **and all clients with an open connection to that channel/DM receive a live update event**; When a non-author attempts to edit, Then `403`.
- Given a message the user authored, When deleted, Then deleted_at is set, content hidden, row retained, **and a live delete event is broadcast to connected clients**.
- Given history requested with `limit`/`cursor`, Then chronological order, soft-deleted excluded, `next_cursor` returned.

**R12 / R13 — DMs**
- Given two distinct users, When one sends a DM, Then persisted and delivered live.
- Given a user attempts to DM themselves, Then rejected `422`.
- Given DM history requested, Then chronological, cursor-paginated.

**R14 / R43 / R44 — Presence**
- Given a user with ≥1 live WebSocket, Then `online`; Given their last connection closes/times out, Then `offline` and `last_seen` updated durably.
- Given multiple open tabs, When one closes, Then still `online` while any connection remains.
- Given Redis restart, Then no user falsely shows `online`, and `last_seen` is still available.

**R15 / R16 / R17 / R18 / R40 / R52 — Real-time delivery**
- Given an open WebSocket, When a new message/edit/delete occurs in that channel/DM, Then it appears live without refresh.
- Given a missing/invalid token at connect, Then rejected before joining; given a token that expires/is revoked (including via R47 deactivation) mid-connection, Then the connection is closed at the next validation/heartbeat.
- Given two app instances, When an event occurs on instance A, Then a member on instance B receives it via Redis pub/sub.
- Given duplicate delivery, Then client dedups by message id.
- Given a client reconnecting after a gap, Then it fetches missed messages via history and dedups.

**R19 — Typing indicators**
- Given a member typing, Then others see an indicator that auto-clears per §5a.

**R20 — Rate limiting**
- Given a user over the per-user send limit, Then `429` + `Retry-After` until refill.
- Given repeated failed auth/reset/invite-registration attempts over the per-IP+identifier limit, Then `429`, regardless of whether the identifier exists.

**R21 — Scale**
- Given ~1,000 concurrent users, Then real-time delivery stays within the §7 latency target.

**R22 / R23 / R24 — Security NFRs**
- Given production config, unlisted-origin requests are CORS-blocked (no wildcard).
- Given production, all traffic is TLS.
- Given any log output, it contains no raw message content, JWTs, invite/reset tokens, secrets, or PII.

**R26 / R27 / R28 / R29 — Profile & password**
- Given registration, first/last name required, avatar optional.
- Given profile view, first/last name, username, email, avatar shown.
- Given a name/avatar update, changes persist and propagate; email/username change is unavailable.
- Given no avatar, an initials badge is shown.
- Given a correct-current-password change with a policy-compliant new password, Then hashed/stored and all other sessions invalidated; Given an incorrect current password, Then rejected, password unchanged.

**R30 / R31 / R32 / R33 / R42 / R53 — Media**
- Given media attached within limits/allowlist, Then delivered and accessible to authorized recipients.
- Given oversize (`413`), disallowed-type, or sniff-mismatched (`415`) upload, Then rejected, nothing stored.
- Given an `image/svg+xml` upload, Then rejected.
- Given an image upload, When stored, Then EXIF metadata (including GPS) is stripped before persistence; the visible image content is otherwise unchanged; Given EXIF stripping fails on a malformed image, Then the upload is rejected rather than stored unstripped.
- Given stored media, When fetched, Then served from a separate origin via short-TTL signed URL, authorized against current membership; a removed member loses access within the TTL.
- Given media rendering, Then browser-decodable images/video are inline/playable, else downloadable with filename/size; no transcoding.
- Given an orphaned upload (parent message-create never completed), Then cleaned up by the cleanup job.

## 7. Success metrics

| Metric | Type | Baseline → Target | How measured |
|--------|------|-------------------|--------------|
| Real-time message delivery latency (send → visible), p95 | Leading | none → < 500 ms at ~1,000 concurrent users | Load test + production latency instrumentation (R25) |
| Message send success rate (excl. rate-limit rejections) | Lagging | none → ≥ 99.9% | Server error-rate monitoring |
| Service uptime | Lagging | none → ≥ 99.5% monthly | Uptime/error monitor |
| WebSocket auth-failure handling | Leading | n/a → 100% unauthenticated joins rejected | Security test suite |
| Sensitive-data-in-logs incidents | Lagging | n/a → 0 | secret-scan hook + log audit |
| Concurrent users before degradation | Leading | none → ≥ 1,000 | Load/stress test |
| Invite → completed-registration conversion | Lagging | none → establish baseline in first 30 days | Product analytics |
| Registration → first-message conversion (activation) | Lagging | none → establish baseline in first 30 days | Product analytics |

> **Enumeration note.** Private channels, non-visible resources, password-reset requests, and invite-registration attempts all return uniform responses regardless of whether the target exists, so existence cannot be probed.

## 8. Constraints & dependencies

**Scale constraint.** Design for **~1,000 concurrent users, not 1,000,000**. Prefer a
single well-run Postgres + Redis + 1–2 app instances over premature horizontal-scaling
complexity. Re-evaluate via ADR when real usage data warrants it.

**Architecture dependencies (per `CLAUDE.md`).**
- App: 1–2 FastAPI instances behind a load balancer; Redis pub/sub for cross-instance WebSocket broadcast (now including edit/delete events, R52).
- Database: single managed PostgreSQL with daily backups; `asyncpg` pooling.
- Redis: single instance for (a) pub/sub fan-out, (b) live presence, (c) rate limiting. No cluster.
- Delivery: persist-then-publish (R40), at-least-once + client dedup; no message queue.
- Email: outbound transactional email required for invites (R45) and password resets (R48) — a new infrastructure dependency not present in v2 (see below).
- Observability: structured JSON logging + uptime/error monitor + latency instrumentation.

> **New dependency — transactional email.** Invite-based registration and self-service
> password reset both require the deployment to send email (SMTP relay or a transactional
> email API). This is a **new operational dependency for the Workspace Operator** that
> didn't exist when registration was open/unauthenticated. It must be configured before
> the workspace is usable at all (no invite can be delivered without it). Flagging this
> explicitly since it changes the deployment prerequisites — **architect should treat
> "email delivery configured" as a hard first-run requirement, not an optional integration.**

> **Single-point-of-failure note (accepted for v1).** One Redis carries pub/sub, live
> presence, and rate limiting; if it fails, real-time delivery, presence, and throttling
> degrade simultaneously (REST/history remain available from Postgres). No Redis
> failover in v1 — accepted risk against the 99.5% target.

> **Backup/RPO note (accepted for v1).** Daily Postgres backups imply an RPO of up to
> 24 h; restore procedure must be tested at least once before GA.

**Security & compliance constraints.**
- Passwords hashed (bcrypt/argon2), never logged or returned.
- JWT secret from env via `pydantic-settings`, never committed.
- Sessions are revocable (R35): logout, password change/reset, and System-Admin deactivation all invalidate tokens.
- WebSocket authenticates before joining and re-validates periodically (R16).
- Server validates channel membership on every read/write and every media fetch.
- CORS restricted; TLS everywhere in production.
- No secrets/PII/message content/invite-tokens/reset-tokens in logs.
- Media uploads are untrusted: allowlist + size caps + content sniffing + filename sanitization + SVG exclusion + EXIF stripping + separate serving origin. **AV/malware scanning is explicitly deferred — see §9 Risks.**
- Invite and password-reset tokens are single-use, time-limited, and unguessable (cryptographically random).

**Tech/process constraints.** Python (FastAPI) + TypeScript (React); `uv` and `npm`. REST for CRUD/history/admin, WebSocket only for real-time. Conventional Commits; PR to `main` with 1 approval; feature branches. Shipped Alembic migrations never edited.

**Domain-model extensions.** `User` gains `first_name`, `last_name`, `is_active` (R47), durable `last_seen` (R44), and a `role` distinguishing System Admin from regular user (R46). New entities: `Invite` (email, token, status, expiry, issued_by) and `PasswordResetToken` (user, token, expiry, used). Flagged to `architect`/`database-engineer`; schema not defined here.

**Media footprint.** Unchanged from v2: size caps, no transcoding, separate origin, upload rate limit, orphan cleanup — plus EXIF stripping (R53) as new processing overhead on image upload.

**Open ADR dependencies** — see §12.

## 9. Risks & open questions

| Risk / question | Impact | Owner | Resolution |
|-----------------|--------|-------|------------|
| WebSocket fan-out correctness across 2 instances (now incl. edit/delete events) | High | architect / backend | Redis pub/sub + persist-then-publish (R40) + dedup (R17/R18/R52); load test |
| Dual-write: event delivered but not persisted (or vice-versa) | High | architect / backend | Persist-then-publish; reconnect catch-up; outbox ADR |
| Session revocation mechanism undecided | High — security | architect / security | ADR (§12); required for R16/R29/R34/R47 |
| Authorization gaps — client-supplied channel_id trusted | High — privacy | security-reviewer | Server-side membership check (R7); security gate |
| Sensitive data (incl. invite/reset tokens) leaking into logs | High | security-reviewer | Logging policy + secret-scan hook (R24); log audit |
| Email delivery is a hard dependency; no fallback if misconfigured at first run | High — blocks onboarding | devops / architect | Fail loudly at startup if email isn't configured; document as a first-run requirement (§8) |
| Invite/reset token leakage (e.g. via referrer headers, logs, or link forwarding) | Medium — security | security-reviewer | Single-use tokens, short TTLs, no token in logs (R24) |
| No AV/malware scanning of uploads | Medium-High — accepted risk | security / product | Deferred to a future version; content-type allowlist + sniffing + EXIF strip are the v1 mitigations (R31/R42/R53) |
| Zero-admin channel after last-member-departure is a permanent state with no recovery path in v1 | Low-Medium | product | Accepted for v1; revisit if it proves disruptive in practice |
| Presence accuracy on ungraceful disconnect | Medium | backend | Heartbeat/TTL + ref-counting (R43); durable last_seen (R44) |
| Rate-limit tuning (auth keying, thresholds) | Medium | backend / performance | Token-bucket params (§5a) validated under load |
| ~1,000-user target unvalidated | Medium | performance-engineer | Load/stress test before GA |
| Malicious/oversized uploads; SVG stored-XSS | High | security / backend | Allowlist + size caps + sniffing + SVG exclusion + filename sanitize |
| Unauthorized media access via direct URL / after removal | High — privacy | security-reviewer | Signed short-TTL URLs authorized against current membership |
| Video storage/bandwidth cost | Medium | performance / architect | Size caps; no transcoding; monitor egress; ADR if usage grows |
| Redis SPOF | Medium | architect / devops | Accepted for v1; revisit via ADR |
| Backup RPO up to 24h; untested restore | Medium | devops | Test restore before GA |
| DM data model / deployment target / media backend / bootstrap mechanism undecided | Medium | architect | ADRs (§12) |

## 10. Rollout

- **Phasing.** (0) **email delivery configured + bootstrap System Admin** (hard prerequisite, §8) → (1) invite-based auth + accounts + profile (name, avatar, change password, logout, self-service reset) → (2) channels + membership (open creation, browse, leave, succession) → (3) messaging + history → (4) media attachments (after storage ADR; includes EXIF stripping) → (5) real-time delivery + presence (including live edit/delete) → (6) DMs + typing indicators → (7) rate limiting + security hardening → GA behind 🔒 gates.
- **Feature flags.** Gate typing indicators (R19), DMs (R12/R13), media attachments (R30–R33), and live edit/delete propagation (R52) behind flags so the core loop can ship first if an ADR or hardening lags. Invite-based registration (R1/R45) and System Admin bootstrap (R46) are **not** flaggable — they are prerequisites for any user to exist.
- **Migration.** Greenfield — no data migration. New Alembic migrations only.
- **Comms.** Announce v1 to the pilot workspace once the bootstrap System Admin can issue invites; publish a short getting-started note covering how to invite teammates.

## 11. Non-functional requirements & UX

**Performance / scalability / reliability.** Per §5a/§7/§8.

**Observability.** Structured JSON logs with correlation ids (no PII/content/tokens); uptime + error monitoring; latency instrumentation; alerting on error-rate and uptime-probe failure. **New:** log (without content) invite issuance, invite redemption, deactivation/reactivation events, and password-reset requests as security-relevant audit events.

**Fault tolerance / DR.** Redis loss degrades real-time/presence/rate-limit but not history. Daily backups; restore drill before GA. **New:** if the email provider is unreachable, invite/reset requests must fail loudly (clear error to the System Admin / user) rather than silently dropping — do not queue-and-forget without a retry/alerting story.

**Visual tone / reference product.** Premium, minimal, and information-dense in the working app — closer to Linear/Raycast than a marketing site — with a distinctive ambient identity on low-density auth/onboarding surfaces (soft gradient/noise atmosphere), not decorative chrome throughout. No illustration/imagery beyond avatars. **Light and dark themes are both in scope** (system-preference default, user-toggleable, persisted) — supersedes the earlier "light mode only" note now that dark mode is explicitly directed. Full palette, type/spacing scale, elevation, motion tokens, and component states are defined in [`architecture/design-tokens.md`](../../architecture/design-tokens.md) — `frontend-engineer` must treat that file as a required input alongside this PRD, not optional polish.

**UX states (responsive web; native mobile client remains a non-goal).**
- **Empty states:** no channels joined, empty channel, no DMs, empty public-channel list, no pending invites, no avatar (initials badge).
- **Loading states:** history fetch, message send (optimistic + pending), media upload (progress + cancel), invite send (pending confirmation).
- **Error states** (mapped from RFC 7807): send failure (retry), upload rejected (size/type reason), rate-limited (cooldown), session expired (re-login), account deactivated (clear message, not a generic login failure), expired/used invite or reset link (clear message + path to request a new one), offline/reconnecting banner.
- **Validation messages:** inline for registration, password change/reset, channel creation, message length, invite email format.
- **Accessibility.** Target **WCAG 2.1 AA** (keyboard nav, focus management on new/live-updated messages, ARIA live-region for incoming messages/typing/edits/deletes, contrast, alt text). *(Default — confirm with PM/UX if a different bar is required.)*
- **Timezones.** Server stores UTC; client renders local/relative time.

## 12. Handoff to Design / ADR (open decisions — NOT resolved here)

- [x] **Pagination strategy** — resolved: cursor-based (R11/R13/R39); ADR confirms cursor encoding.
- [x] **Registration model** — resolved: invite-based, System-Admin-issued, email auto-verified (R1/R45).
- [x] **Account recovery** — resolved: self-service email-based reset (R48).
- [x] **Moderation scope** — resolved: System Admin = invite + deactivate/reactivate only; message deletion stays author-only (R10, R47).
- [x] **Channel discovery/lifecycle** — resolved: browse public list (R49), leave (R50), auto-succession (R51), no archive/delete.
- [x] **Real-time edit/delete propagation** — resolved: yes, live (R52).
- [x] **Media hygiene scope** — resolved: EXIF strip now (R53), AV scan deferred (accepted risk).
- [ ] **DM data model** — reuse `channels` table (2-member private channel) vs dedicated `direct_messages` table. Prerequisite for R12/R13.
- [ ] **Deployment target** — single Docker host vs Render/Fly.io/Railway. Prerequisite for Ship phase.
- [ ] **Media storage backend** — S3-compatible bucket vs alternative (scope confirmed IN v1; backend choice open). Prerequisite for R30–R33.
- [ ] **Revocable-session mechanism** — `token_version`-per-request vs refresh-token store/denylist vs short-TTL+rotation. Prerequisite for R16/R29/R34/R35/R47.
- [ ] **Delivery correctness** — plain persist-then-publish vs transactional outbox for R40 (decide based on load-test findings).
- [ ] **Transactional email provider/integration** — SMTP relay vs a provider API (e.g. SES/Postmark/etc.); templates for invite and reset emails. Prerequisite for R45/R48 and for the workspace to be usable at all.
- [ ] **System Admin bootstrap mechanism** — env-var-seeded account vs first-run CLI/setup wizard. Prerequisite for R46.

---
🔒 **Approval gate:** human PM sign-off before Architecture begins. *(All product clarifications resolved as of this version — gate is now a formality/final read, not blocked on open questions.)*