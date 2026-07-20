# Functional Specification — chatspace v1

> Owner: `business-analyst` agent. Input: PRD. Output consumed by: `architect`, `qa-engineer`.
> Status: Draft · Traces to PRD: `docs/prd/chatspace-v1-prd.md`

## 1. Overview

This specification defines the behavior of **chatspace v1**, a single-workspace, self-hostable team-chat product. It makes explicit the core communication loop: a System Admin invites a user by email; the invitee registers into a verified account; users authenticate with a short-lived access token plus a refresh token, manage their own profile and password, and recover access via self-service reset. Any active user creates public or private channels (becoming that channel's admin), browses and joins public channels, leaves channels (with automatic last-admin succession), and exchanges text-and-media messages in channels and 1:1 DMs. Messages are persisted with a globally-unique, time-sortable id, then broadcast in real time — new messages, edits, and soft-deletes — over authenticated WebSocket connections that fan out across app instances, with at-least-once delivery deduplicated client-side and reconnect catch-up via history. Presence (online/offline plus durable last-seen) and typing indicators keep the conversation live, while token-bucket rate limits and non-enumerating uniform responses provide the baseline abuse and privacy defenses. This spec is behavior-level and stack-agnostic; it does not resolve the open ADR decisions carried in §9.

## 2. Actors & roles

| Actor | Definition | Capabilities in v1 |
|-------|------------|--------------------|
| **Unauth** | A client with no valid session. | May only reach public auth entry points (login, password-reset request, invite-redemption via a valid token). Cannot reach any protected resource. |
| **Invited (pre-registration)** | The holder of a valid, unused, unexpired invite token tied to a specific email. Not yet a user. | May open the registration form (email locked to the invited address) and complete registration exactly once. |
| **Auth user (non-member)** | A registered, active, authenticated user who is not a member of a given channel. | Login/logout/reset; view/edit own profile; change password; create channels; browse and join public channels; send/read DMs with any active user. Cannot read or post in channels they do not belong to. |
| **Channel Member** | An authenticated user in a channel's membership list with role `member`. | Read and post in that channel; attach media; leave that channel. Inherits all Auth-user capabilities. |
| **Channel Admin** | A channel member with role `admin` for that channel (per-channel, not global). | All Channel-Member capabilities plus add/remove members and assign member/admin roles **within that channel**. Leaving as sole admin triggers succession (R51). |
| **Message Author** | The user who created a given message. | Edit and soft-delete **their own** message only — no override by any admin in v1. |
| **System Admin** | A workspace-level role, separate from Channel Admin. At least one always exists. | Issue/revoke/resend invites; deactivate/reactivate user accounts. **No** special channel or message access; cannot read private channels they are not a member of, nor delete other users' messages. |
| **Workspace Operator** | The human who runs the deployment infrastructure. | Interacts through operational/security guarantees (uptime, no sensitive data in logs, rate limiting, email configured as a first-run prerequisite). Not a product role in the app itself; the bootstrap System Admin is typically created by the operator. |

### 2.1 Permission matrix (authoritative — restated from PRD §5c)

| Action | Unauth | Invited (pre-reg) | Auth user (non-member) | Channel Member | Channel Admin | Message Author | System Admin |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| Register (via valid invite only) | ❌ | ✅ | — | — | — | — | — |
| Issue / revoke / resend an invite | ❌ | ❌ | ❌ | ❌ | ❌ | — | ✅ |
| Login / logout / password reset | — | — | ✅ | ✅ | ✅ | ✅ | ✅ |
| View/edit own profile, change password | — | — | ✅ | ✅ | ✅ | ✅ | ✅ |
| Deactivate / reactivate a user | ❌ | ❌ | ❌ | ❌ | ❌ | — | ✅ |
| Create a channel | — | — | ✅ | ✅ | ✅ | — | ✅ |
| Browse / join a public channel | — | — | ✅ | ✅ | ✅ | — | ✅ |
| List own channels ("My channels") | ❌ | — | ✅ | ✅ | ✅ | — | ✅ |
| Leave a channel | — | — | — | ✅ | ✅¹ | — | — |
| Read/post in a channel | ❌ | — | ❌ | ✅ | ✅ | — | — |
| Add/remove members, set roles (own channel) | — | — | ❌ | ❌ | ✅ | — | — |
| Edit a message | — | — | ❌ | ❌ | ❌ | ✅ (own) | ❌ |
| Soft-delete a message | — | — | ❌ | ❌ | ❌ | ✅ (own only) | ❌ |
| Send/read DM with a user | — | — | ✅² | ✅² | ✅² | — | ✅² |

¹ Leaving as the sole admin triggers auto-succession (R51) before membership is removed.
² Any two distinct active users; no DM blocking in v1.

## 3. Functional requirements (detailed)

| ID | Traces to (PRD Rn) | Behavior | Preconditions | Postconditions |
|----|--------------------|----------|---------------|----------------|
| F1 | R45 | System Admin issues an invite for a specific email; a single-use, 7-day token is generated and an invite email is sent to that address. | Caller is an active System Admin; email delivery configured; email not already a registered user. | An `Invite` row exists (status `pending`, expiry set, `issued_by` recorded); email dispatched or the action fails loudly. |
| F2 | R45 | System Admin revokes an unused invite. | Caller is an active System Admin; target invite is `pending`. | Invite status → `revoked`; its token can no longer redeem (subsequent open → `410`). |
| F3 | R45 | System Admin resends an invite, issuing a new token and invalidating the prior one. | Caller is an active System Admin; a prior invite for that email exists and is unused. | New `pending` token issued and emailed; the previous token is invalidated (→ `410` if opened). |
| F4 | R1, R45 | Invitee opens a valid, unused, unexpired invite link; the registration form loads with email pre-filled and locked to the invited address. | Invite token is `pending` and unexpired. | Registration form served bound to the invited email; token remains `pending` until redemption. |
| F5 | R1 | Invitee registers with first name, last name, username, password (policy-compliant), optional avatar; password is hashed; email auto-verified. | Valid invite (F4); username and email unique; password meets R37. | New active `User` created (email verified, no separate verification step); invite token → `used`; password stored hashed and never returned/logged. |
| F6 | R1, R45 | A registration request without a valid invite token (direct API call) is rejected — no invite-less path exists. | Request lacks a valid `pending` invite token. | Request rejected; no user created. |
| F7 | R45 | An expired, already-used, or revoked invite token is rejected on redemption. | Token exists but is not `pending`/unexpired. | `410 Gone`; no user created; token state unchanged. |
| F8 | R46 | On first deployment with no users, exactly one default System Admin account is created automatically (bootstrap), without any prior invite. | Fresh deployment, zero users; bootstrap mechanism executed (mechanism is an ADR). | One active System Admin exists and can immediately issue invites; bootstrap step is not skippable (no zero-admin deployment). |
| F9 | R46 | System Admin role grants only invite (R45) and deactivate/reactivate (R47) powers — no special channel/message access. | Caller holds System Admin role. | System Admin actions on channels/messages are governed by the same membership/authorship rules as any user. |
| F10 | R2 | An active user logs in with valid credentials and receives a short-lived access token plus a refresh token. | Credentials valid; account active. | Access token (15 min TTL) and refresh token (30-day sliding TTL) issued; a revocable session is established. |
| F11 | R2, R47 | Login is rejected for invalid credentials (without revealing which field) or for a deactivated account. | Credentials invalid, or account `is_active = false`. | No tokens issued; response does not disclose field-level error or account existence. |
| F12 | R2, R35 | A valid refresh token is exchanged for a new access token; an invalidated refresh token fails. | Refresh token presented. | Valid → new access token issued (session preserved); invalidated/expired → `401`. |
| F13 | R3 | Protected REST endpoints reject requests with a missing, invalid, or expired access token. | Request targets a non-auth REST route. | Valid token → request proceeds; otherwise `401` and no protected data returned. |
| F14 | R34, R35 | User logs out; the current session's access + refresh tokens can no longer authenticate any request. | Authenticated session. | Current session invalidated server-side; other sessions unaffected. |
| F15 | R48 | User requests a password reset for their registered email; a single-use, 1-hour reset link is emailed. Response is uniform regardless of whether the email exists. | Email delivery configured. | If the email exists, a `PasswordResetToken` is created and emailed; response identical whether or not it exists (no enumeration). |
| F16 | R48, R35 | User submits a new, policy-compliant password via a valid, unused, unexpired reset link; password is set and all of the user's other active sessions are invalidated. | Reset token valid, unused, unexpired; new password meets R37. | Password re-hashed and stored; token → `used`; all of the user's other sessions invalidated. |
| F17 | R48 | Concurrent reset requests: only the most recently issued token is valid; earlier tokens are invalidated. Expired/used tokens → `410`. | ≥1 reset token issued. | Latest token valid; all earlier tokens invalidated; stale/used submissions → `410`. |
| F18 | R26 | User views own profile: first name, last name, username, email, avatar. | Authenticated. | Profile returned; password never included. |
| F19 | R27 | User edits own first name, last name, and/or avatar; changes persist and propagate to where the user is rendered. | Authenticated; new values valid. | Updated fields persisted; rendered identity updates. |
| F20 | R27 | Email and username are immutable after registration; edit attempts are unavailable/rejected. | Authenticated. | Email/username unchanged. |
| F21 | R28 | When a user has no avatar set, an initials badge (first + last initial) is shown everywhere the user is rendered. | User has no `avatar_url`. | Initials badge derived from first/last name displayed as visual identity. |
| F22 | R29, R35, R37 | User changes password by confirming the current password and supplying a policy-compliant new one; all of the user's other active sessions are invalidated. | Authenticated; current password correct; new password meets R37. | New password hashed/stored; other sessions invalidated; incorrect current password → rejected, password unchanged. |
| F23 | R37 | Password policy (minimum length + basic strength) is enforced on registration, password change, and password reset. | Any password-setting operation. | Non-compliant password rejected with validation error; nothing persisted. |
| F24 | R26, R28 | Other users' names and avatars (or initials badge) are shown next to their messages. | Viewing messages authored by others. | Author identity rendered with each message. |
| F25 | R47, R35, R16 | System Admin deactivates an active user: login blocked, all of that user's active sessions invalidated immediately, and open WebSocket connections dropped within the R16 revalidation window. | Caller is active System Admin; target is active; target is not the last active System Admin (see F27). | Target `is_active = false`; sessions invalidated; WebSockets closed at next validation/heartbeat. |
| F26 | R47 | System Admin reactivates a deactivated user; login is restored with a fresh session (prior sessions not restored). | Caller is active System Admin; target `is_active = false`. | Target `is_active = true`; can log in anew; old sessions remain invalid. |
| F27 | R47 | Deactivating the last remaining active System Admin is rejected. | Target is the only active System Admin. | Action rejected with a clear error; workspace retains ≥1 active System Admin. |
| F28 | R47 | A deactivated user's prior messages and channel memberships are retained as-is (not deleted, not anonymized). | User deactivated. | Historical messages and memberships remain visible/intact. |
| F29 | R4 | Any active authenticated user creates a channel (public or private) and is recorded as its admin. | Authenticated, active; channel name valid and unique within workspace. | `Channel` stored with creator, visibility, `created_at`; a `ChannelMember` row for the creator with role `admin`. |
| F30 | R49 | An active user retrieves a paginated list of public channels they are not yet a member of and can join directly from it. | Authenticated, active. | Paginated public-channel list (name; optional member count) excluding channels the requester already belongs to. |
| F31 | R5 | A user joins a public channel directly. | Authenticated, active; channel is public; requester not already a member. | `ChannelMember` row created with role `member`. |
| F32 | R5, R6 | Joining/adding to a private channel is admin-gated; non-admins cannot add themselves or others. Members are selected via the workspace user-directory search (F76), not by entering a raw user id. | Target channel is private. | Only a Channel Admin of that channel may add members; non-admin attempt → `403`. Add resolves the target from a directory-search selection (F76). |
| F33 | R6 | A Channel Admin manages that channel's membership and roles (add/remove members, assign member/admin). | Caller is admin of that channel; channel has ≥1 admin. | Membership/role changes applied; changes to a zero-admin channel are blocked until it regains an admin. |
| F34 | R7 | The server validates channel membership on every message read/write and every media fetch; a client-supplied channel_id alone is never trusted. | Any channel read/write/media-fetch request. | Non-members rejected on server-side membership check even with a valid channel_id. |
| F35 | R50 | Any member (including an admin) leaves a channel they belong to. | Caller is a member. | Membership removed; if caller was sole admin, F36 runs first. |
| F36 | R51 | When a channel's only admin leaves (F35) or is deactivated (F25), the longest-standing remaining member (earliest `joined_at`) is automatically promoted to admin before the departing membership change completes. | Departing/deactivated user is the channel's only admin; ≥1 other member remains. | Earliest-`joined_at` remaining member's role → `admin`; then the original membership change proceeds. |
| F37 | R51 | If no other members remain when the sole admin departs, the channel persists with zero admins (not archived, not deleted); membership/roles cannot change until it regains an admin. | Sole admin departs; no other members. | Channel persists with zero admins as a valid terminal state; membership/role mutations blocked. |
| F38 | R8, R36 | A channel member sends a valid text message (optionally with media). | Caller is a member; body non-null/non-whitespace/≤ max length. | Message persisted (F45), assigned a sortable id (F41), delivered live (F51). |
| F39 | R36 | Message input validation: body non-null, non-whitespace, ≤ 4,000 chars; edit only while not deleted; edit never changes id/ordering. | Any message create/edit. | Invalid → `422`, nothing persisted/changed. |
| F40 | R38 | Send idempotency: a repeated `Idempotency-Key` on message-create returns the original message with no duplicate row. | Client supplies `Idempotency-Key`. | First call creates the row; repeat returns the same message; exactly one row exists. |
| F41 | R39 | Each message is assigned a server-generated, globally-unique, time-sortable id; server `created_at` is authoritative; ties broken by id. | Message created. | Message carries a sortable id used for ordering and pagination cursors. |
| F42 | R9, R52 | The author edits their own message; `edited_at` is set, id/order unchanged, and a live update event is broadcast to all clients connected to that channel/DM. | Caller is the author; message not deleted. | Content updated, `edited_at` set; edit event broadcast; non-author attempt → `403`. |
| F43 | R10, R52 | The author soft-deletes their own message; `deleted_at` set, content hidden, row retained, and a live delete event is broadcast. | Caller is the author; message not already deleted. | `deleted_at` set; content hidden but row retained; delete event broadcast; no admin override. |
| F44 | R11 | A channel member retrieves channel history in chronological order with cursor-based pagination, excluding soft-deleted content. | Caller is a member. | `{ items, next_cursor }` returned; soft-deleted content excluded. |
| F45 | R40 | Messages are persisted before being published to real-time subscribers (persist-then-publish). | Any message create/edit/delete. | The durable record is committed before the real-time event is emitted. |
| F46 | R12 | A user sends a 1:1 DM to another distinct active user. | Both users distinct and active. | DM message persisted and delivered live to the recipient. |
| F47 | R12 | A user attempting to DM themselves is rejected. | Sender and recipient are the same user. | `422`; nothing persisted. |
| F48 | R13 | A user retrieves 1:1 DM history with another user, chronological, cursor-paginated. | Participant in the DM conversation. | `{ items, next_cursor }` returned. |
| F49 | R14, R43 | Presence: a user is `online` while ≥1 live WebSocket exists, ref-counted across tabs/instances; heartbeat + TTL expires stale connections. | User has ≥1 tracked live connection. | Presence reflects `online`/`offline`; stale connections expire via heartbeat/TTL. |
| F50 | R44 | On the user's last connection closing/timing out, presence → `offline` and `last_seen` is written durably so it survives a Redis restart. | Last live connection ends. | `last_seen` persisted durably; user shown `offline`. |
| F51 | R15, R52 | New messages, edits, and deletes appear in real time over WebSocket without a refresh. | Client has an open, authenticated WebSocket to the channel/DM. | Live message/edit/delete events rendered without refresh. |
| F52 | R16 | A WebSocket authenticates via the access token before joining any channel and is revalidated periodically; revoked/expired/deactivated-user tokens are dropped mid-connection. | Connection attempt with token. | Missing/invalid token → rejected before join; token later invalidated → connection closed at next validation/heartbeat with a documented close code. |
| F53 | R17 | Real-time broadcast (including edit/delete events) works across more than one app instance via pub/sub fan-out. | ≥1 app instance; an event occurs on any instance. | Members connected to any instance receive the event. |
| F54 | R18 | Delivery is at-least-once; clients deduplicate by message id. | Real-time delivery in progress. | Duplicate deliveries are collapsed client-side by message id. |
| F55 | R40, R18 | A client reconnecting after a gap catches up on missed messages via history using the last received message id and dedups. | Client reconnects after disconnect. | Missed messages fetched via history from the last id; duplicates deduped. |
| F56 | R19 | Typing indicators for channels and DMs are shown live and auto-expire 5 s after the last keystroke. | Open WebSocket; peer typing. | Indicator shown to other participants; auto-clears per §5a. |
| F57 | R30 | A user attaches media (image, file, or video) to a channel or DM message. | Caller may post to the target channel/DM; media within limits/allowlist (F58). | Media associated with the message and accessible to authorized recipients. |
| F58 | R31 | Media validation: enforce per-type max size and content-type allowlist; sniffed content must match the declared type; `image/svg+xml` is excluded from the image allowlist. | Media upload attempt. | Oversize → `413`; disallowed type or sniff mismatch → `415`; SVG rejected; nothing stored on rejection. |
| F59 | R32 | Stored media is served from a separate origin/bucket via short-TTL (5 min) signed URLs, authorized against **current** channel/DM membership; access is revoked within the URL TTL after membership ends. | Authorized requester at fetch time. | Signed URL issued only to a current member; a removed member loses access within the TTL. |
| F60 | R33 | Browser-decodable images/video render inline/playable; all other files (and undecodable media) appear as downloadable attachments with filename and size; no server-side transcoding. | Media attached to a rendered message. | Inline render or download affordance shown per decodability; no transcoding performed. |
| F61 | R53, R42 | EXIF metadata (including GPS) is stripped from uploaded images before storage; visible content is otherwise unchanged. Applies to the image allowlist only, not video/files. | Image upload passing F58. | Image stored with EXIF stripped; if stripping fails on a malformed image, the upload is rejected rather than stored unstripped. |
| F62 | R42 | Media hygiene: filenames are sanitized (no path traversal, no active-content extensions served inline); a per-user upload rate limit (20/min) applies; orphaned media (parent message-create never completed) is cleaned up. | Any upload. | Sanitized filename stored; over-limit uploads throttled; orphaned uploads removed by the cleanup job. |
| F63 | R20 | Per-user token-bucket rate limiting on message send (10 msg / 10 s, burst 20). | User sending messages. | Over-limit sends → `429` + `Retry-After` until refill. |
| F64 | R20 | Per-IP + per-attempted-identifier rate limiting on auth endpoints (login, register-via-invite, password-reset request, refresh): 5 attempts / 5 min; must not enable enumeration. | Auth-endpoint traffic. | Over-limit → `429` regardless of whether the identifier exists. |
| F65 | R21 | The system sustains ~1,000 concurrent users with real-time delivery within the §7 latency target. | ~1,000 concurrent users. | Delivery latency stays within the p95 < 500 ms target under load. |
| F66 | R22 | CORS is restricted to known frontend origin(s); no wildcard in production. | Production configuration. | Unlisted-origin requests are CORS-blocked. |
| F67 | R23 | All production traffic is served over TLS. | Production. | Traffic encrypted end to end (terminated at the platform/load balancer). |
| F68 | R24 | Logs never contain raw message content, JWTs, invite tokens, reset tokens, secrets, or PII. | Any log output. | Log lines carry a correlation/request id but no sensitive data. |
| F69 | R25 | Structured JSON logging plus uptime/error monitoring and latency instrumentation for the §7 delivery metric; security-relevant audit events (invite issuance/redemption, deactivation/reactivation, reset requests) are logged without content. | Runtime. | Observability signals emitted; audit events recorded without sensitive payloads. |
| F70 | R41 | REST errors use RFC 7807 `application/problem+json` with standard statuses; WebSocket uses a documented close-code/reason scheme. | Any error response. | Errors returned in the standard shape with the correct status/close code. |
| F71 | R54 | A System Admin can retrieve a paginated list of invites (email, status, expiry, issued_at), filterable by status (`pending`/`accepted`/`revoked`/`expired`); backs the Invite Management screen (PRD §11). | System Admin requesting the invite list. | List returned paginated with per-invite status; a non-admin caller → `403`; the raw invite token is never included (F68/R24). |
| F72 | R55 | A System Admin can retrieve a paginated, searchable list of users (id, first/last name, username, email, role, `is_active`, `last_seen`); search matches name/username/email; includes active and deactivated users; backs the User Management screen (PRD §11). | System Admin requesting/searching the user list. | Matching users returned paginated; a non-admin caller → `403`; no password hash or other secret material in the response (§8). |
| F73 | R56 | An active user retrieves a cursor-paginated list of every channel they are a member of — public **and** private — with name, visibility, member count, and their own role; backs the primary logged-in navigation surface (PRD §11). | Authenticated, active. | `{ items, next_cursor }` over the caller's own memberships only; channels the caller does not belong to never appear; empty membership → empty, non-error page. |
| F74 | R57 | When a user is added to a channel (self-join or channel-admin add) and the membership is committed, each of that user's open authenticated WebSocket connections receives a `channel.member_added` event carrying the channel summary, via that user's per-user topic. | Membership creation committed; target user has ≥1 open authenticated connection. | Event delivered to the affected user's connections only (no other user receives it); clients insert the channel idempotently by id. Events are at-least-once with **no replay** — a disconnected client recovers via a channel-list refetch on reconnect. |
| F75 | R57 | When a user is removed from a channel (self-leave or channel-admin remove) and the change is committed, each of that user's open connections receives a `channel.member_removed` event; clients drop the channel from the list and exit any open view of it gracefully. | Membership removal committed; target user has ≥1 open authenticated connection. | Event delivered to the affected user's connections only. Deactivation-triggered removal emits no event (connections are dropped, F25/F52); role-only changes emit no event (role display self-heals on the next list fetch). |
| F76 | R59 | An authenticated, active user searches the workspace user directory (matching `username`/`first_name`/`last_name`, case-insensitive) and receives minimal public identity per match; the read backs the channel member-picker (F32/F33) and the DM "new message" picker (F46). | Authenticated, active. | Cursor-paginated `{ items, next_cursor }` of `{ id, username, first_name, last_name, avatar_url }`; **never** returns `email`/`is_active`/`last_seen`/`role` (distinct from the admin list F72); deactivated users excluded from results by default; rate-limited as a general authenticated read. |

## 4. User flows

### Flow A — Invite issuance → email → registration (F1–F7, R1/R45)
```
1. System Admin submits an invite for email E.
   1a. Caller is not an active System Admin → 403.
   1b. E is already a registered user → 409.
   1c. Email delivery is not configured/unreachable → fail loudly to the admin (no silent drop).
2. System creates a pending, single-use invite token (7-day expiry) tied to E and emails the link.
3. Invitee opens the invite link.
   3a. Token expired / used / revoked → 410, no form.
4. Registration form loads with email locked to E; invitee enters first/last name, username, password (+ optional avatar).
   4a. Username or email not unique → 409.
   4b. Password fails policy (R37) → 422.
5. System creates the active, email-verified user, hashes the password, marks the invite token used, and issues no separate verification step.
   (Alt) Admin revokes an unused invite before step 3 → later open → 410.
   (Alt) Admin resends → new token issued, old token invalidated (→ 410 if opened).
   (Alt) Direct API registration with no valid token → rejected (no invite-less path).
```

### Flow B — Login / refresh / logout (F10–F14, R2/R34/R35)
```
1. User submits credentials.
   1a. Account deactivated → rejected (clear "deactivated" message, not generic).
   1b. Invalid credentials → rejected without revealing which field.
   1c. Over per-IP+identifier rate limit → 429 + Retry-After.
2. System issues a short-lived access token + a refresh token (a revocable session).
3. Client calls protected endpoints with Bearer access token.
   3a. Missing/invalid/expired access token → 401.
4. On access-token expiry, client exchanges the refresh token for a new access token.
   4a. Refresh token invalidated/expired → 401 (must re-login).
5. User logs out → current session's access + refresh tokens can no longer authenticate; other sessions unaffected.
```

### Flow C — Password reset (F15–F17, R48/R35)
```
1. User requests a reset for email E.
2. System returns a uniform response regardless of whether E exists (no enumeration).
   2a. If E exists → a single-use, 1-hour reset token is emailed; any earlier reset token for E is invalidated.
   2b. Over auth rate limit → 429.
3. User opens the reset link and submits a new password.
   3a. Token expired / already used → 410.
   3b. New password fails policy → 422.
   3c. A superseded (earlier) token is submitted → invalid (only the latest is valid).
4. System sets the new password (hashed) and invalidates all of the user's other active sessions.
```

### Flow D — Deactivate / reactivate (F25–F28, R47)
```
1. System Admin requests deactivation of user U.
   1a. U is the last remaining active System Admin → rejected with a clear error.
2. System sets U.is_active = false, invalidates all of U's sessions immediately, and drops U's open WebSockets within the R16 revalidation window.
   2a. If U was the sole admin of any channel → last-admin succession (Flow F, R51) runs for each such channel.
3. U's prior messages and channel memberships remain intact (not deleted/anonymized).
4. (Reactivate) System Admin reactivates U → U.is_active = true; U can log in with a fresh session; prior sessions are not restored.
```

### Flow E — Create / browse / join / leave channel (F29–F37, F73, R4/R5/R6/R49/R50/R51/R56)
```
1. Active user creates a channel (public or private) with a valid, workspace-unique name.
   1a. Name invalid/duplicate → 422 / 409.
2. System stores the channel and records the creator as its admin.
3. User retrieves their own channel list ("My channels": every public + private membership, cursor-paginated) (F73).
4. User browses the paginated public-channel list (channels they are not yet a member of).
5. User joins a public channel directly → becomes a member.
   5a. Private channel: only a Channel Admin may add members; non-admin self/other add → 403.
6. Channel Admin adds/removes members and assigns member/admin roles within the channel.
   6a. Channel currently has zero admins → membership/role changes blocked until an admin returns.
   6b. Membership add/remove is propagated live to the affected user's channel list (Flow L).
7. Member (incl. admin) leaves a channel.
   7a. Leaver is the sole admin and other members remain → promote earliest-joined_at member to admin, THEN remove leaver's membership (Flow F).
   7b. Leaver is the sole admin and no other members remain → membership removed; channel persists with zero admins (terminal state).
```

### Flow F — Last-admin succession (F36–F37, R51)
```
1. A channel's only admin departs (leaves per Flow E, or is deactivated per Flow D).
2. System evaluates remaining members.
   2a. ≥1 remaining member → promote the member with the earliest joined_at to admin, then complete the departure.
   2b. 0 remaining members → complete the departure; channel persists with zero admins; membership/roles frozen until an admin is regained.
```

### Flow G — Send / edit / delete message with live broadcast (F38–F45, F51, R8/R9/R10/R36/R38/R39/R40/R52)
```
1. Channel member composes a message and sends it with an Idempotency-Key.
   1a. Body empty/whitespace/over max length → 422, nothing persisted.
   1b. Not a member of the channel → 403 (server-side membership check).
   1c. Over per-user send rate limit → 429 + Retry-After.
   1d. Repeated Idempotency-Key → original message returned, no duplicate row.
2. System persists the message with a server-assigned sortable id and authoritative created_at (persist-then-publish).
3. System publishes a new-message event; connected clients render it live and dedup by id.
4. (Edit) Author edits their message → content updated, edited_at set, id/order unchanged; edit event broadcast live.
   4a. Non-author attempts edit → 403.
   4b. Message already soft-deleted → edit rejected.
5. (Delete) Author soft-deletes → deleted_at set, content hidden, row retained; delete event broadcast live.
   5a. Non-author attempts delete → 403.
```

### Flow H — Media upload → validate → sniff → EXIF-strip → store → signed-URL fetch (F57–F62, R30/R31/R32/R33/R42/R53)
```
1. User attaches media to a channel/DM message they may post to.
2. System validates declared content-type against the per-type allowlist and size against the per-type cap.
   2a. Oversize → 413.
   2b. Disallowed type (incl. image/svg+xml) → 415.
3. System sniffs actual content; sniffed type must match the declared type.
   3a. Sniff mismatch → 415, nothing stored.
4. For images: strip EXIF metadata (incl. GPS) before storage; visible content otherwise unchanged.
   4a. EXIF strip fails on a malformed image → reject the upload (do not store unstripped).
5. System sanitizes the filename and stores media on a separate origin/bucket; associates it with the message.
6. On fetch, system checks the requester's CURRENT channel/DM membership and issues a short-TTL (5 min) signed URL.
   6a. Requester is not a current member → denied.
   6b. Member removed after issuance → loses access within the signed-URL TTL.
7. Client renders inline/playable if browser-decodable, else as a downloadable attachment with filename/size (no transcoding).
   (Background) Orphaned uploads whose parent message-create never completed are removed by the cleanup job.
```

### Flow I — DM send / history (F46–F48, R12/R13)
```
1. User sends a DM to another distinct active user.
   1a. Recipient is self → 422.
   1b. Over per-user send rate limit → 429.
2. System persists the DM and delivers it live to the recipient.
3. Either participant retrieves DM history, chronological, cursor-paginated.
```

### Flow J — WebSocket connect → auth → join → heartbeat → revalidate → drop (F49–F53, R14/R16/R17/R43)
```
1. Client opens a WebSocket presenting the access token.
   1a. Missing/invalid/expired token → rejected before joining any channel (documented close code).
2. System authenticates the token, then allows the client to join channels/DMs it is authorized for.
3. Presence ref-count increments; user shown online while ≥1 connection exists (ref-counted across tabs/instances).
4. Client sends periodic heartbeats; the server periodically revalidates the token.
   4a. Token expired/revoked or user deactivated → connection closed at next validation/heartbeat.
   4b. Heartbeat stops (ungraceful disconnect) → connection expires via TTL.
5. Events (new/edit/delete/typing) fan out across instances via pub/sub to all authorized connected clients.
6. On the user's last connection closing/timing out → presence → offline, last_seen persisted durably.
```

### Flow K — Reconnect catch-up (F54–F55, R18/R40)
```
1. Client detects a dropped connection and shows a reconnecting banner.
2. Client re-authenticates and reopens the WebSocket (Flow J).
3. Client requests history since the last received message id for each active channel/DM.
4. System returns missed messages (chronological, soft-deleted excluded).
5. Client merges and dedups by message id so duplicates from at-least-once delivery are collapsed.
```

### Flow L — Membership change → live channel-list update (F74–F75, R57)
```
1. A membership change for user U commits (self join/leave, or channel-admin add/remove).
2. System publishes a membership event to U's per-user topic AFTER the commit (persist-then-publish).
   - channel.member_added carries the channel summary; channel.member_removed carries the channel id.
3. Each app instance relays the event to U's locally connected clients only — no other user's connection receives it.
4. U's clients update the channel list idempotently by channel id (insert on added, remove on removed).
   4a. U is currently viewing the removed channel → the open view is exited gracefully with a clear "you were removed from this channel" message.
5. Membership events are at-least-once with NO replay: after a disconnect, U's client refetches the channel list on reconnect (F73) instead of expecting missed events.
   (Excluded) Deactivation-triggered removal emits no membership event — the target's connections are dropped (Flow D, F52).
   (Excluded) Role-only changes emit no event; the displayed role self-heals on the next list fetch.
```

## 5. Business rules

**Configurable limits & policy defaults (PRD §5a — defaults, tunable during design; not open product questions):**
- **Password policy:** minimum 6 chars + basic strength rule; enforced on registration, password change, and password reset (R37).
- **Message body:** non-null, non-whitespace, ≤ 4,000 chars (R36).
- **Channel name:** 1–80 chars; letters, digits, spaces, `-`, `_`; unique within the workspace (R36).
- **Message edit window:** unlimited (author only, until deleted); an edit never changes a message's id or ordering (R9/R36).
- **Access-token TTL:** 15 min. **Refresh-token TTL:** 30 days (sliding) (R35).
- **Invite token TTL:** 7 days, single-use (R45). **Password-reset token TTL:** 1 hour, single-use (R48).
- **Message send rate limit:** 10 msg / 10 s / user (burst 20) (R20). **Auth endpoint rate limit:** 5 attempts / 5 min per IP + attempted identifier (R20). **Per-user upload rate limit:** 20 uploads / min (R42).
- **Media size caps:** image 10 MB, file 50 MB, video 200 MB (R31).
- **Image content-type allowlist:** `image/png`, `image/jpeg`, `image/gif`, `image/webp` — `image/svg+xml` excluded (R31). **Video allowlist:** `video/mp4`, `video/webm` (R31/R33).
- **Signed media URL TTL:** 5 min — defines the media revocation-lag bound (R32).
- **Typing-indicator auto-expire:** 5 s after last keystroke (R19).
- **Public-channel list page size:** 50, paginated (R49).
- **My-channels list page size:** 50, cursor-paginated (R56).

**Identity & uniqueness:**
- Email and username are unique across the workspace (DB constraint) and immutable after registration; only display name (first/last) and avatar are editable (R1/R27).
- Registration is reachable **only** via a valid, unused, unexpired invite; there is no invite-less registration path; the invited email is auto-verified (R1/R45).
- At least one active System Admin must always exist; the bootstrap admin is created automatically at first deployment and this step is not skippable (R46).

**Messaging & delivery:**
- **Message identity:** server-assigned, globally-unique, time-sortable id; server `created_at` is authoritative; ties broken by id (R39).
- **Send idempotency:** a repeated `Idempotency-Key` returns the original message with no duplicate row (R38).
- **Persist-then-publish:** the durable record is committed before the real-time event is emitted (R40).
- **At-least-once + client dedup:** delivery may repeat; clients deduplicate by message id; reconnecting clients catch up via history from the last received id (R18/R40).
- **Message deletion is author-only** (soft delete); no Channel Admin or System Admin override in v1. Editing is author-only and only while the message is not deleted (R9/R10).

**Channels & succession:**
- Any active user can create a channel and becomes its admin; there is no System-Admin gate on channel creation (R4).
- Public channels are joinable directly; private-channel membership is admin-gated (R5).
- **Last-admin succession:** when a channel's only admin leaves or is deactivated, the longest-standing remaining member (earliest `joined_at`) is auto-promoted to admin **before** the departure completes (R51).
- **Zero-admin channel is a valid terminal state:** if no members remain, the channel persists with zero admins (never archived/deleted); its membership/roles cannot change until it regains an admin (R51).
- **Membership events** (`channel.member_added` / `channel.member_removed`) are published only after the membership change is committed (persist-then-publish) and are delivered only to the affected user's own connections; they carry no replay — a reconnecting client refetches its channel list (R57).

**Authorization & privacy:**
- The server validates channel/DM membership on every message read/write and every media fetch; a client-supplied channel_id is never trusted alone (R7).
- Media is served from a separate origin via short-TTL signed URLs authorized against **current** membership; access ends within the URL TTL after membership ends (R32).
- **Uniform, non-enumerating responses:** private channels, non-visible resources, password-reset requests, and invite-registration attempts return uniform responses regardless of whether the target exists; auth-endpoint rate limiting must not reveal identifier existence (R20/§7).

**Sessions:**
- Sessions are revocable: logout, password change, password reset, and System-Admin deactivation all invalidate the affected tokens; password change/reset invalidate all of the user's *other* sessions (R29/R34/R35/R47/R48).

**Media hygiene (R31/R42/R53):**
- Enforce allowlist + size cap; sniffed content must match the declared type; SVG is excluded from images.
- **EXIF-strip-or-reject:** images have EXIF (incl. GPS) stripped before storage; if stripping fails on a malformed image, reject the upload rather than store it unstripped. Applies to images only, not video/files.
- Filenames are sanitized (no path traversal / active-content extensions served inline); orphaned uploads are cleaned up; AV/malware scanning is explicitly deferred (accepted risk).

**Presence:**
- A user is `online` while ≥1 live WebSocket exists, ref-counted across tabs/instances; heartbeat + TTL expires stale connections; `last_seen` is written durably on the last disconnect so it survives a Redis restart (R14/R43/R44).

**Logging & errors:**
- No raw message content, JWTs, invite tokens, reset tokens, secrets, or PII in logs; every response/log line carries a non-PII correlation id (R24).
- REST errors use RFC 7807 `application/problem+json`; WebSocket uses a documented close-code scheme (R41).

## 6. Edge cases & error handling

| Case | Expected behavior |
|------|-------------------|
| Empty/invalid input (message body null/whitespace) | `422`, nothing persisted (F39). |
| Message body over 4,000 chars | `422`, nothing persisted (F39). |
| Invite token expired | `410 Gone`; no registration (F7). |
| Invite token already used | `410`; single-use enforced (F7). |
| Invite token revoked by admin | `410` on later open (F2/F7). |
| Invite resent | Old token invalidated → `410`; only the new token redeems (F3). |
| Direct API registration with no/invalid invite | Rejected — no invite-less path (F6). |
| Duplicate email/username at registration | `409` conflict (F5). |
| Reset token expired or already used | `410` (F17). |
| Concurrent password-reset requests | Only the most recently issued token is valid; earlier tokens invalidated (F17). |
| Reset request for a non-existent email | Uniform response identical to the existing-email case; no enumeration (F15). |
| Self-DM (recipient == sender) | `422`, nothing persisted (F47). |
| Login on a deactivated account | Rejected with a clear "account deactivated" message (not a generic login failure) (F11). |
| Invalid login credentials | Rejected without revealing which field was wrong (F11). |
| Oversize media upload | `413`, nothing stored (F58). |
| Disallowed media content-type | `415`, nothing stored (F58). |
| `image/svg+xml` upload | Rejected (`415`) — excluded from image allowlist (F58). |
| Sniffed content-type mismatches declared type | `415`, nothing stored (F58). |
| EXIF-strip failure on a malformed image | Upload rejected — never stored unstripped (F61). |
| Media fetched after membership ends | Access revoked within the 5-min signed-URL TTL (F59). |
| Media fetch by a non-member with a valid-looking URL | Denied via current-membership check (F34/F59). |
| Mid-connection token expiry | WebSocket closed at next validation/heartbeat with a documented close code (F52). |
| Mid-connection token revocation (logout/password change) | Same as above — dropped at next revalidation (F52). |
| Mid-connection user deactivation | Sessions invalidated; open WebSockets dropped within the R16 revalidation window (F25/F52). |
| Redis (real-time/presence/rate-limit backend) unavailable | Real-time delivery, presence, and rate limiting degrade; REST/history remain available from durable storage; no user falsely shows online (accepted SPOF). |
| Multi-tab presence: one tab closes while others remain | User stays `online` while ≥1 connection remains (ref-count) (F49). |
| Ungraceful disconnect (no close frame) | Connection expires via heartbeat TTL; presence → offline; last_seen persisted (F49/F50). |
| Deactivating the last active System Admin | Rejected with a clear error; ≥1 active System Admin always retained (F27). |
| Leaving a channel as its sole admin (other members exist) | Earliest-joined_at member promoted to admin first, then membership removed (F36). |
| Leaving a channel as its sole admin (no other members) | Membership removed; channel persists with zero admins (terminal state) (F37). |
| Mutation attempted on a zero-admin channel | Blocked until the channel regains an admin (F33/F37). |
| User added to a channel while offline/disconnected | Channel appears on the next channel-list fetch / reconnect refetch — membership events have no replay (F73/F74). |
| User removed from a channel they are currently viewing | Channel removed from the list live; the open view is exited gracefully with a clear message (F75). |
| Redis unavailable when a membership change commits | Membership event lost (fail-open); the membership itself is durable and the list is corrected on the next fetch/reconnect refetch — same recovery class as message catch-up (F55/F74/F75). |
| Over per-user message send rate limit | `429` + `Retry-After` until token-bucket refill (F63). |
| Over per-IP+identifier auth rate limit | `429` regardless of whether the identifier exists (no enumeration) (F64). |
| Over per-user upload rate limit | `429` (F62). |
| Duplicate real-time delivery of the same message | Client dedups by message id (F54). |
| Retried send with the same Idempotency-Key | Original message returned; exactly one row exists (F40). |
| Reconnect after a gap | Missed messages fetched via history from last received id; deduped (F55). |
| Non-member reads/posts with a valid channel_id | Rejected on server-side membership check (F34). |
| Non-author edits/deletes a message | `403`; no admin override in v1 (F42/F43). |
| Edit attempt on an already-soft-deleted message | Rejected (F39). |
| Cross-origin request from an unlisted origin (production) | CORS-blocked; no wildcard (F66). |
| Email provider unreachable at invite/reset time | Fail loudly (clear error to the admin/user); no silent drop or queue-and-forget without retry/alerting (F1/F15). |

## 7. Data dictionary

> All timestamps are ISO-8601 UTC; clients render local/relative time. Tokens and password hashes are **never returned in API responses and never logged**.

### User
| Field | Type | Constraints | PII? | Notes |
|-------|------|-------------|------|-------|
| id | opaque id | PK; server-assigned | No | Stable user identifier. |
| username | string | unique; immutable after registration | Yes (identifier) | Not editable in v1 (R27). |
| email | string | unique; immutable; auto-verified via invite | Yes | Verified at registration; never freely entered (R1). |
| hashed_password | string | bcrypt/argon2 | Sensitive | Never returned/logged (R1/R24). |
| first_name | string | required | Yes | Editable (R1/R27). |
| last_name | string | required | Yes | Editable; drives initials badge (R28). |
| avatar_url | string \| null | optional | Yes (image) | Null → initials badge fallback (R28). |
| role | enum | `system_admin` \| `user` | No | Workspace-level; distinct from Channel Admin (R46). |
| is_active | boolean | default true | No | False blocks login and invalidates sessions (R47). |
| last_seen | timestamp \| null | durable | Yes (activity) | Written on last disconnect; survives Redis restart (R44). |
| created_at | timestamp | server-set | No | |

### Channel
| Field | Type | Constraints | PII? | Notes |
|-------|------|-------------|------|-------|
| id | opaque id | PK | No | |
| name | string | 1–80 chars; letters/digits/spaces/`-`/`_`; unique in workspace | No | R36. |
| is_private | boolean | — | No | Public → directly joinable; private → admin-gated (R5). |
| created_by | user id | FK → User | No | Recorded creator; becomes first admin (R4). |
| created_at | timestamp | server-set | No | |

### ChannelMember
| Field | Type | Constraints | PII? | Notes |
|-------|------|-------------|------|-------|
| channel_id | channel id | FK; composite key with user_id | No | |
| user_id | user id | FK | No | |
| role | enum | `member` \| `admin` | No | Per-channel role (R6). |
| joined_at | timestamp | server-set | No | Drives succession (earliest = successor) (R51). |

### Message
| Field | Type | Constraints | PII? | Notes |
|-------|------|-------------|------|-------|
| id | opaque id | PK; server-assigned; globally unique; time-sortable | No | ULID/UUIDv7-class; used for ordering + pagination cursor (R39). |
| channel_id | channel id \| null | nullable when it is a DM | No | Exactly one of channel_id / recipient_id set. |
| sender_id | user id | FK → User | No | The Message Author. |
| recipient_id | user id \| null | nullable when it is a channel message | No | Set for DMs only. |
| content | text | non-null/non-whitespace; ≤ 4,000 chars | Yes | Message body; never logged raw (R24/R36). |
| created_at | timestamp | server-set; authoritative for ordering | No | Ties broken by id (R39). |
| edited_at | timestamp \| null | set on edit; never changes id/order | No | Author-only edit (R9). |
| deleted_at | timestamp \| null | soft delete | No | Content hidden but row retained; author-only (R10). |

### DM model (open ADR — described generically)
| Field | Type | Constraints | PII? | Notes |
|-------|------|-------------|------|-------|
| (conversation identity) | — | 1:1 between two distinct active users; self-DM rejected | Yes (participants) | **Data model is an open ADR (§9):** reuse channels as a 2-member private channel vs a dedicated direct_messages structure. Behaviorally, a DM message is a Message with `recipient_id` set and `channel_id` null; history is chronological and cursor-paginated (R12/R13). |

### Invite
| Field | Type | Constraints | PII? | Notes |
|-------|------|-------------|------|-------|
| id | opaque id | PK | No | |
| email | string | the invited address; email locked to this on registration | Yes | R45. |
| token | string | cryptographically random; single-use; 7-day TTL | Sensitive | Never returned in listings or logged (R24). |
| status | enum | `pending` \| `used` \| `revoked` \| (expired by TTL) | No | Drives `410` on non-`pending` redemption (F7). |
| expiry | timestamp | 7 days from issue | No | R45/§5a. |
| issued_by | user id | FK → System Admin | No | Audit: who invited (R45). |

### PasswordResetToken
| Field | Type | Constraints | PII? | Notes |
|-------|------|-------------|------|-------|
| id | opaque id | PK | No | |
| user_id | user id | FK → User | No | |
| token | string | cryptographically random; single-use; 1-hour TTL | Sensitive | Never returned/logged (R24). |
| expiry | timestamp | 1 hour from issue | No | R48/§5a. |
| used | boolean | default false | No | Only the latest issued token is valid; earlier ones invalidated (F17). |

### Presence (ephemeral — not durable)
| Field | Type | Constraints | PII? | Notes |
|-------|------|-------------|------|-------|
| user_id | user id | — | No | |
| state | enum | `online` \| `offline` | Yes (activity) | Ephemeral, ref-counted across tabs/instances; heartbeat + TTL (R14/R43). Durable `last_seen` lives on User (R44). |

## 8. Acceptance criteria (Given/When/Then)

**F1–F7 · Invites & registration (R1/R45)**
- Given an active System Admin, When they issue an invite for `alice@co.com`, Then a single-use token with a 7-day expiry tied to that email is created (status `pending`) and an email is sent.
- Given email delivery is unreachable, When an invite is issued, Then the action fails loudly to the admin (no silent success).
- Given a valid, unused, unexpired invite link, When opened, Then the registration form pre-fills and locks the email to the invited address.
- Given an expired, used, or revoked invite, When redemption is attempted, Then `410 Gone` and no user is created.
- Given a valid invite and a policy-compliant password with a unique username, When registration is submitted, Then an active, email-verified user is created, the password is hashed (never returned), and the invite token is marked `used`.
- Given a duplicate username or email, When registration is submitted, Then `409` and no user created.
- Given a System Admin revokes an unused invite, When the original link is opened later, Then `410`; Given they resend, Then a new token is issued and the old one is invalidated.
- Given no/invalid invite token, When a registration request hits the API directly, Then it is rejected — no invite-less path exists.

**F8–F9 · System Admin bootstrap & scope (R46)**
- Given a fresh deployment with zero users, When the app starts for the first time, Then exactly one default System Admin is created automatically without any prior invite, and the step is not skippable.
- Given the bootstrap System Admin, Then they can immediately issue invites; and they have no special access to private channels or other users' messages.

**F10–F14 · Login / refresh / logout (R2/R3/R34/R35)**
- Given valid credentials for an active account, When a user logs in, Then a short-lived access token and a refresh token are returned.
- Given valid credentials for a deactivated account, When login is attempted, Then it is rejected with a clear deactivated message.
- Given invalid credentials, Then the request is rejected without revealing which field was wrong.
- Given a protected endpoint with a missing/invalid/expired token, Then `401` and no protected data.
- Given a valid refresh token, When exchanged, Then a new access token is issued; an invalidated refresh token → `401`.
- Given a logged-in user, When they log out, Then that session's access + refresh tokens can no longer authenticate; other sessions are unaffected.

**F15–F17 · Password reset (R48/R35)**
- Given a reset request for an email that exists, Then a single-use, 1-hour reset link is emailed; Given an email that does not exist, Then the same generic response is returned (no enumeration).
- Given a valid, unused, unexpired reset link and a policy-compliant new password, When submitted, Then the password is set and all of the user's other active sessions are invalidated.
- Given an expired or already-used reset link, Then `410`.
- Given multiple reset requests in quick succession, Then only the most recently issued token is valid; earlier ones are invalidated.

**F18–F24 · Profile & password (R26/R27/R28/R29/R37)**
- Given an authenticated user, When they view their profile, Then first/last name, username, email, and avatar are shown; the password is never included.
- Given a name/avatar update, Then the changes persist and propagate; email/username changes are unavailable.
- Given a user with no avatar, Then an initials badge (first + last initial) is shown wherever the user is rendered, including next to messages by others.
- Given a correct current password and a policy-compliant new password, When a password change is submitted, Then it is hashed/stored and all other sessions are invalidated; Given an incorrect current password, Then it is rejected and the password is unchanged.
- Given a non-compliant password on registration/change/reset, Then it is rejected with a validation error and nothing is persisted.

**F25–F28 · Deactivation / reactivation (R47)**
- Given a System Admin deactivates an active user, Then that user's sessions are invalidated immediately, open WebSockets are dropped within the R16 revalidation window, and subsequent logins are rejected.
- Given a System Admin attempts to deactivate the last remaining active System Admin, Then the action is rejected with a clear error.
- Given a System Admin reactivates a deactivated user, Then the user can log in with a fresh session; prior sessions are not restored.
- Given a deactivated user's prior messages and channel memberships, Then they remain intact (not deleted/anonymized).

**F29–F37 · Channels & membership (R4/R5/R6/R7/R49/R50/R51)**
- Given any active authenticated user, When they create a channel, Then it is stored with creator, visibility, and created_at, and the creator is recorded as admin.
- Given the public-channel list, When requested, Then it returns public channels the requester is not yet a member of, paginated.
- Given a public channel, When a user requests to join, Then they become a member; Given a private channel, When a non-admin adds themselves/others, Then `403`; When a channel admin adds/removes/changes roles, Then applied.
- Given a non-member with a valid channel_id, When they attempt to read/post, Then rejected on server-side membership.
- Given a member leaves as the sole admin with other members present, Then the earliest-joined_at member is promoted to admin before their membership is removed; Given no other members remain, Then the channel persists with zero admins.
- Given a deactivated user who was a channel's sole admin, Then the same succession rule applies; Given a zero-admin channel, When any membership/role change is attempted, Then it is blocked until an admin is regained.

**F38–F45, F51 · Messaging & live broadcast (R8/R9/R10/R11/R36/R38/R39/R40/R52)**
- Given a channel member sends a valid message, Then it is persisted, assigned a sortable id, and delivered in real time.
- Given an empty/whitespace/over-length body, Then `422` and nothing persisted.
- Given a retried send with the same Idempotency-Key, Then exactly one message row exists and the original is returned.
- Given a message the user authored, When edited, Then content updates, edited_at is set, id/order unchanged, and connected clients receive a live update event; a non-author edit → `403`; an edit on a deleted message → rejected.
- Given a message the user authored, When soft-deleted, Then deleted_at is set, content hidden, row retained, and a live delete event is broadcast; a non-author delete → `403`.
- Given history requested with limit/cursor, Then chronological order, soft-deleted excluded, next_cursor returned.

**F46–F48 · DMs (R12/R13)**
- Given two distinct active users, When one sends a DM, Then it is persisted and delivered live.
- Given a user DMs themselves, Then `422`.
- Given DM history requested, Then chronological, cursor-paginated.

**F49–F50 · Presence (R14/R43/R44)**
- Given a user with ≥1 live WebSocket, Then `online`; Given their last connection closes/times out, Then `offline` and last_seen updated durably.
- Given multiple open tabs, When one closes, Then still `online` while any connection remains.
- Given a Redis restart, Then no user falsely shows `online` and last_seen is still available.

**F51–F55 · Real-time delivery (R15/R16/R17/R18/R40/R52)**
- Given an open WebSocket, When a new message/edit/delete occurs in that channel/DM, Then it appears live without refresh.
- Given a missing/invalid token at connect, Then rejected before joining; Given a token that expires/is revoked (incl. via deactivation) mid-connection, Then the connection is closed at the next validation/heartbeat.
- Given two app instances, When an event occurs on instance A, Then a member on instance B receives it via pub/sub fan-out.
- Given duplicate delivery, Then the client dedups by message id.
- Given a client reconnecting after a gap, Then it fetches missed messages via history from the last received id and dedups.

**F56 · Typing indicators (R19)**
- Given a member typing, Then others see an indicator that auto-clears 5 s after the last keystroke.

**F57–F62 · Media (R30/R31/R32/R33/R42/R53)**
- Given media within limits/allowlist, Then it is stored and accessible to authorized recipients.
- Given oversize upload, Then `413`; Given disallowed type or sniff mismatch, Then `415`; Given `image/svg+xml`, Then rejected — nothing stored in each case.
- Given an image upload, When stored, Then EXIF (incl. GPS) is stripped before persistence and visible content is otherwise unchanged; Given EXIF stripping fails on a malformed image, Then the upload is rejected rather than stored unstripped.
- Given stored media fetched, Then served from a separate origin via a short-TTL signed URL authorized against current membership; a removed member loses access within the TTL.
- Given media rendering, Then browser-decodable images/video are inline/playable, else downloadable with filename/size; no transcoding.
- Given an orphaned upload (parent message-create never completed), Then it is removed by the cleanup job; Given a user over the upload rate limit, Then `429`.

**F63–F64 · Rate limiting (R20)**
- Given a user over the per-user send limit, Then `429` + `Retry-After` until refill.
- Given repeated failed auth/reset/invite-registration attempts over the per-IP+identifier limit, Then `429`, regardless of whether the identifier exists.

**F65–F70 · NFR & platform (R21/R22/R23/R24/R25/R41)**
- Given ~1,000 concurrent users, Then real-time delivery stays within the p95 < 500 ms target.
- Given production config, Then unlisted-origin requests are CORS-blocked (no wildcard) and all traffic is TLS.
- Given any log output, Then it contains no raw message content, JWTs, invite/reset tokens, secrets, or PII, and carries a correlation id.
- Given security-relevant events (invite issuance/redemption, deactivation/reactivation, reset requests), Then they are logged as audit events without sensitive payloads.
- Given any error, Then REST responses use RFC 7807 `application/problem+json` with the correct status and WebSocket closes use the documented close-code scheme.

**F71–F72 · Admin list/search (R54/R55)**
- Given a System Admin requests the invite list, Then invites are returned paginated with email, status, expiry, and issued_at, filterable by status, and no raw token is included.
- Given a System Admin searches users by name/username/email, Then matching users (active and deactivated) are returned paginated with id, name, username, email, role, `is_active`, and `last_seen`, and no password material.
- Given a non-System-Admin requests the invite list or the user list, Then the request is rejected with `403`.
- Given the invite or user list is empty, Then an empty, non-error result is returned.

**F73–F75 · My channels & live membership (R56/R57)**
- Given an authenticated, active user, When they request their channel list, Then every channel they belong to — public **and** private — is returned cursor-paginated with name, visibility, member count, and their own role; channels they do not belong to never appear.
- Given a user with no memberships, When they request their channel list, Then an empty, non-error page is returned.
- Given user U with an open WebSocket connection, When U is added to a channel (self join or admin add) and the change commits, Then all of U's connected clients receive `channel.member_added` with the channel summary and show the channel without a refresh.
- Given user U with an open WebSocket connection, When U is removed from a channel (self leave or admin remove), Then all of U's connected clients receive `channel.member_removed`, drop the channel from the list, and exit any open view of it gracefully.
- Given a membership change affecting U, Then no other user's connection receives the event (per-user delivery only).
- Given membership events were missed while U was disconnected, When U's client reconnects, Then it refetches the channel list and reflects the correct memberships (no event replay is provided).

**F76 · Workspace user directory (R59)**
- Given an authenticated, active user searches the directory by name or username, Then matching users are returned cursor-paginated with **public identity only** (`id`, `username`, `first_name`, `last_name`, `avatar_url`) and **no** `email`, `is_active`, `last_seen`, or `role` (distinct from the admin list, F72).
- Given a channel admin adds a member, Then the target is chosen from a directory-search selection (F76), never by entering a raw user id; the add itself remains admin-gated (F32/F33).
- Given a user starts a DM, Then the recipient is chosen from a directory-search selection (F76), then F46 applies (self-DM rejected).
- Given the directory search matches no one, Then an empty, non-error result is returned; deactivated users are excluded from picker results by default.

## 9. Assumptions & dependencies

**Assumptions carried forward from the PRD:**
- **Deactivated-user data is retained as-is** — a deactivated user's prior messages and channel memberships are not deleted or anonymized (R47). *Flag: confirm with PM if a different retention/anonymization policy is later required.*
- **Accessibility target is WCAG 2.2 AA** (adopted 2026-07-20; keyboard nav, focus management on live-updated messages, ARIA live regions for incoming messages/typing/edits/deletes, contrast, alt text, ≥24×24px target size, focus-not-obscured). Standard and checklist: `docs/design/ACCESSIBILITY_GUIDELINES.md`.
- **Single workspace per deployment** — all entities are workspace-global; no `workspace_id`, no multi-tenancy in v1.
- **Scale target is ~1,000 concurrent users** on a single deployment — not hyperscale; delivery latency target p95 < 500 ms.
- Server stores UTC; clients render local/relative time.

**Hard dependencies:**
- **Transactional email is a hard first-run prerequisite** — invites (R45) and password resets (R48) cannot be delivered without configured outbound email; the workspace is unusable until it is configured, and delivery failures must fail loudly (no silent drop / queue-and-forget without retry & alerting).
- **System Admin bootstrap** — a default System Admin must be created at first deployment; the workspace must never be in a zero-admin state.

**Accepted risks (v1):**
- **Single-Redis SPOF** — one Redis carries pub/sub fan-out, live presence, and rate limiting; its failure degrades real-time delivery, presence, and throttling simultaneously (history/REST survive from durable storage). No Redis failover in v1.
- **Backup RPO up to 24 h** — daily backups; a restore drill must be performed before GA.
- **No AV/malware scanning of uploads** — deferred; content-type allowlist + sniffing + EXIF strip + SVG exclusion + filename sanitization are the v1 mitigations.

**Open ADR decisions (NOT resolved in this spec — PRD §12).** Where a behavior below cannot be fully specified without the decision, this spec describes it generically and flags it:

> **Reconciliation (2026-07-20):** all of the items below are now **resolved** by ADRs — DM data model ([ADR-0002](../../architecture/adr/0002-dm-data-model.md)), delivery correctness ([ADR-0004](../../architecture/adr/0004-realtime-delivery-fanout.md)), revocable sessions ([ADR-0006](../../architecture/adr/0006-revocable-sessions.md)), media backend ([ADR-0007](../../architecture/adr/0007-media-object-storage.md)), deployment target ([ADR-0008](../../architecture/adr/0008-deployment-target.md)), System Admin bootstrap ([ADR-0009](../../architecture/adr/0009-system-admin-bootstrap.md)), transactional email ([ADR-0010](../../architecture/adr/0010-transactional-email.md)); see PRD §12 and the [ADR index](../../architecture/adr/README.md). The generic descriptions below are retained for traceability; the physical details now live in those ADRs and the technical spec.
- **DM data model** — reuse channels (2-member private channel) vs a dedicated direct-messages structure. *Flag: DM entity in §7 is described behaviorally only; the physical model, and whether DM authorization reuses channel-membership checks, cannot be pinned until this is decided (affects F46–F48, F34, F59).*
- **Deployment target** — single Docker host vs Render/Fly.io/Railway. Affects TLS termination (F67) and email/media integration surface.
- **Media storage backend** — S3-compatible bucket vs alternative. *Flag: the separate-origin signed-URL mechanism (F59) and orphan cleanup (F62) are specified behaviorally; concrete URL-signing and lifecycle semantics depend on the backend.*
- **Revocable-session mechanism** — token-version-per-request vs refresh-token store/denylist vs short-TTL + rotation. *Flag: the exact timing and guarantees of "immediate" session invalidation (F14, F16, F22, F25) and the mid-connection drop window (F52) depend on this choice.*
- **Delivery correctness** — plain persist-then-publish vs transactional outbox for R40. *Flag: F45/F55 specify persist-then-publish + reconnect catch-up; the stronger dual-write guarantee is an ADR based on load-test findings.*
- **Transactional email provider/integration** — SMTP relay vs a provider API; invite and reset email templates. Prerequisite for F1/F15.
- **System Admin bootstrap mechanism** — env-var-seeded account vs first-run CLI/setup wizard. *Flag: F8 requires a non-skippable bootstrap; the mechanism is an architect decision.*

**Contradictions / gaps flagged for product/architect:**
- No product-level contradictions were found between PRD §5, §5a, §5c, and §6 — the permission matrix, limits, and acceptance criteria are internally consistent.
- **Zero-admin channel recovery gap:** R51 permits a channel to reach a permanent zero-admin terminal state with no recovery path in v1 (accepted per PRD §9). Flagged so the architect/product are aware that such channels are frozen until a future moderation feature exists.
- **Media revocation lag is bounded but non-zero:** F59 guarantees access loss only within the 5-min signed-URL TTL, not instantaneously — acceptable per §5a but noted as a privacy boundary.
- **Mid-connection revocation lag:** WebSocket drop on token revocation/deactivation occurs at the next revalidation/heartbeat, not instantaneously (F52); the exact bound depends on the heartbeat interval and the revocable-session ADR.
