# Database Design — chatspace v1

> Owner: `database-engineer`. Guarded by `schema-change-guard` hook. Reviewed with `architect`, `performance-engineer`.

**Status: Draft**

Scope: the complete v1 PostgreSQL physical schema and its reversible initial migration for a self-hostable, single-workspace, Slack-style team chat (FastAPI + SQLAlchemy + Alembic + asyncpg). Grounded in the functional spec §7 data dictionary + F57–F62 (media), TSD §4, the `CLAUDE.md` DOMAIN MODEL, the finalized v1 API contract, and ADR-0002 (DM = message with `recipient_id`), ADR-0003 (keyset pagination), ADR-0005 (UUIDv7 ids), ADR-0006 (revocable sessions), ADR-0007 (media object storage).

**Cross-cutting decisions applied everywhere**
- **UUIDv7 primary keys on every table** (ADR-0005), stored in Postgres' native `uuid` type. Ids are **generated application-side** (Python UUIDv7 library, e.g. `uuid6`/`uuid-utils`) — *not* by a DB default — because (a) the id must be known before persist-then-publish so it can accompany the message to the WebSocket fan-out with no extra round-trip (ADR-0004/0005), and (b) avoiding a `pg_uuidv7` server extension keeps the schema portable across managed/self-hosted Postgres. Trade-off: the app owns id generation (a library dependency vetted via `dependency-update`) rather than the DB; there is deliberately **no `DEFAULT` on `id`** (a `gen_random_uuid()` default would be UUIDv4 — random, not time-sortable — and would silently violate R39, so it is excluded). Time-ordered ids keep b-tree inserts near-append-only, protecting write latency.
- **All timestamps are `timestamptz`, stored in UTC.** `created_at` defaults to `now()` at the DB as a safety net; the app is authoritative for message `created_at` (R39).
- **No Postgres extensions required.** Case-insensitive uniqueness uses functional unique indexes on `lower(...)` rather than `citext`, maximizing self-hostability.
- **Ephemeral state is NOT in Postgres.** Presence (online/offline ref-count), typing indicators, and per-user rate-limit token buckets live in **Redis** (F49–F50, R14/R43, `CLAUDE.md` ARCHITECTURE NOTES). Only the **durable `last_seen`** survives in Postgres on `users` (R44).
- **Media bytes are NOT in Postgres.** Uploaded files live in S3-compatible object storage (ADR-0007); Postgres stores only attachment **metadata** and the opaque `storage_key`. Fetch URLs are short-lived signed URLs issued at request time (`GET /v1/media/{media_id}/url`), never persisted.
- **Secrets never stored in cleartext.** Refresh tokens, invite tokens, and password-reset tokens are stored **hashed** (`*_token_hash`); raw tokens and `hashed_password` are never returned in API responses and never logged (R1/R24).

## Data model

```dbml
// UUIDv7 PKs everywhere (app-generated). timestamptz UTC everywhere.

Table users {
  id               uuid       [pk]
  username         text       [not null, unique, note: 'immutable; unique case-insensitive']
  email            text       [not null, unique, note: 'immutable; unique case-insensitive']
  hashed_password  text       [not null, note: 'bcrypt/argon2; never returned/logged']
  first_name       text       [not null]
  last_name        text       [not null]
  avatar_url       text       [null]
  is_active        boolean    [not null, default: true]
  is_system_admin  boolean    [not null, default: false]
  last_seen        timestamptz[null, note: 'durable; written on last disconnect (R44)']
  created_at       timestamptz[not null, default: `now()`]
}

Table channels {
  id           uuid        [pk]
  name         text        [not null, note: '1-80 chars; unique case-insensitive in workspace']
  is_private   boolean     [not null]
  created_by   uuid        [not null, ref: > users.id]
  created_at   timestamptz [not null, default: `now()`]
}

Table channel_members {
  channel_id   uuid        [ref: > channels.id]
  user_id      uuid        [ref: > users.id]
  role         channel_member_role [not null, default: 'member']
  joined_at    timestamptz [not null, default: `now()`, note: 'earliest = succession heir (R51)']
  indexes { (channel_id, user_id) [pk] }
}

Table messages {
  id           uuid        [pk, note: 'UUIDv7 time-sortable']
  channel_id   uuid        [null, ref: > channels.id, note: 'set for channel msg; XOR recipient_id']
  recipient_id uuid        [null, ref: > users.id, note: 'set for DM; XOR channel_id (ADR-0002)']
  sender_id    uuid        [not null, ref: > users.id]
  content      text        [not null, note: '1..4000 chars, non-whitespace']
  created_at   timestamptz [not null, default: `now()`, note: 'authoritative order; tie-break by id']
  edited_at    timestamptz [null]
  deleted_at   timestamptz [null, note: 'soft delete; row retained, excluded from history']
}

Table attachments {
  id            uuid            [pk, note: 'UUIDv7; API media_id = this']
  message_id    uuid            [null, ref: > messages.id, note: 'null until message-create binds it (two-phase); ON DELETE CASCADE']
  uploader_id   uuid            [not null, ref: > users.id, note: 'ON DELETE RESTRICT']
  kind          attachment_kind [not null, note: 'image | file | video']
  content_type  text            [not null, note: 'MIME; allowlist app-side, SVG excluded']
  storage_key   text            [not null, note: 'opaque object-store key; NOT a URL']
  filename      text            [not null, note: 'sanitized; API filename']
  byte_size     bigint          [not null, note: 'API size; per-kind cap; > 0']
  created_at    timestamptz     [not null, default: `now()`]
}

Table invites {
  id           uuid          [pk]
  email        text          [not null, note: 'invited address; locks registration email']
  token_hash   text          [not null, unique, note: 'hash of single-use token; raw never stored']
  status       invite_status [not null, default: 'pending']
  created_by   uuid          [not null, ref: > users.id]
  expires_at   timestamptz   [not null, note: '7 days from issue']
  accepted_at  timestamptz   [null]
  created_at   timestamptz   [not null, default: `now()`]
}

Table password_reset_tokens {
  id           uuid        [pk]
  user_id      uuid        [not null, ref: > users.id]
  token_hash   text        [not null, unique, note: 'hash of single-use token']
  expires_at   timestamptz [not null, note: '1 hour from issue']
  used_at      timestamptz [null, note: 'only latest unused+unexpired is valid (F17)']
  created_at   timestamptz [not null, default: `now()`]
}

Table sessions {
  id                  uuid        [pk, note: 'session_id (sid) embedded in access JWT']
  user_id             uuid        [not null, ref: > users.id]
  refresh_token_hash  text        [not null, unique, note: 'hash of opaque refresh token']
  user_agent          text        [null, note: 'device/agent metadata']
  ip_address          inet        [null, note: 'PII; last observed client IP']
  issued_at           timestamptz [not null, default: `now()`]
  last_used_at        timestamptz [null]
  expires_at          timestamptz [not null, note: '30-day sliding']
  revoked_at          timestamptz [null, note: 'revocation source of truth (ADR-0006)']
}

// Enums
Enum channel_member_role { member admin }
Enum invite_status       { pending accepted revoked }
Enum attachment_kind     { image file video }

// Presence / typing / rate-limit  ->  Redis only, NOT in Postgres.
// Media bytes -> object storage; only metadata + storage_key live in Postgres.
```

Relationships: `users 1─* channels` (created_by), `users 1─* channel_members *─1 channels`, `users 1─* messages` (sender), `users 0─* messages` (recipient, DM only), `channels 1─* messages`, `messages 1─* attachments` (0 or more; attachment may be temporarily orphaned pre-bind), `users 1─* attachments` (uploader), `users 1─* invites` (created_by), `users 1─* password_reset_tokens`, `users 1─* sessions`. A DM has **no** `channels` row — conversation identity is the canonical unordered pair `(least(sender_id, recipient_id), greatest(sender_id, recipient_id))` (ADR-0002).

## Tables / collections

| Name | Purpose | Key fields | PII? | Retention |
|------|---------|-----------|------|-----------|
| users | Workspace member identity + profile + auth material | id (PK), username (uq), email (uq), hashed_password, is_active, is_system_admin | Yes — username, email, first/last name, avatar_url, last_seen. hashed_password sensitive. | Indefinite. Deactivated users retained as-is, not deleted/anonymized (R47, FS §9). |
| channels | Workspace channels (public/private) | id (PK), name (uq), is_private, created_by | No | Indefinite (no channel-delete feature in v1). |
| channel_members | Channel membership + per-channel role; drives succession | (channel_id, user_id) PK, role, joined_at | No | Lives with channel; row removed on leave/kick. |
| messages | Channel messages **and** DMs (unified); soft-deletable | id (PK, UUIDv7), channel_id XOR recipient_id, sender_id, content, created_at, deleted_at | Yes — content, and DM participant identities. | Indefinite; soft-deleted rows retained (content hidden), never hard-deleted in v1. |
| attachments | Media metadata for message images/files/videos (ADR-0007, F57–F62); bytes in object storage | id (PK), message_id (nullable FK), uploader_id, kind, storage_key, byte_size | Yes — filename (may carry PII); uploader linkage. content bytes sensitive but not in DB. | Bound rows live with their message. **Orphans** (`message_id IS NULL`) past a TTL are swept (F62); object bytes purged separately in object storage. |
| invites | Single-use registration invites | id (PK), email, token_hash (uq), status, created_by, expires_at | Yes — email. token sensitive (hashed). | Retain for admin audit (issued-by); purge/expire policy TBD (see Open questions). |
| password_reset_tokens | Single-use password-reset tokens | id (PK), user_id, token_hash (uq), expires_at, used_at | Yes — links to user. token sensitive (hashed). | Short-lived; purge rows past `expires_at` on a scheduled job. |
| sessions | Revocable session / refresh-token store (ADR-0006) | id (PK = sid), user_id, refresh_token_hash (uq), expires_at, revoked_at | Yes — user_agent, ip_address (activity). refresh token sensitive (hashed). | Purge rows where `expires_at < now()` (revoked/expired) on a scheduled job. |
| *(presence / typing / rate-limit)* | **Redis only — not modeled in Postgres** | — | Activity (ephemeral) | TTL-based in Redis; no durability. |

## Field definitions

### users
| Table.field | Type | Null? | Default | Constraints | Index? |
|-------------|------|-------|---------|-------------|--------|
| users.id | uuid | No | — (app UUIDv7) | PK | PK btree |
| users.username | text | No | — | UNIQUE (case-insensitive via `lower`); immutable (app-enforced, R27); CHECK length 1–32 | `uq_users_username_lower` |
| users.email | text | No | — | UNIQUE (case-insensitive via `lower`); immutable; CHECK basic format | `uq_users_email_lower` |
| users.hashed_password | text | No | — | bcrypt/argon2; never returned/logged (R1/R24) | No |
| users.first_name | text | No | — | CHECK non-empty | No |
| users.last_name | text | No | — | CHECK non-empty | No |
| users.avatar_url | text | Yes | NULL | Null → initials fallback (R28) | No |
| users.is_active | boolean | No | true | False blocks login + revokes sessions (R47) | No |
| users.is_system_admin | boolean | No | false | Workspace admin flag (see note) | No |
| users.last_seen | timestamptz | Yes | NULL | Durable; written on last disconnect (R44) | No |
| users.created_at | timestamptz | No | now() | server-set | No |

*Note:* FS §7 models workspace role as an enum `system_admin|user`; v1 has exactly two workspace roles, so a boolean `is_system_admin` (per the task/DOMAIN MODEL) is the simpler faithful encoding. Promote to an enum only if a third workspace role appears (would be an expand migration).

### channels
| Table.field | Type | Null? | Default | Constraints | Index? |
|-------------|------|-------|---------|-------------|--------|
| channels.id | uuid | No | — (app UUIDv7) | PK | PK btree |
| channels.name | text | No | — | UNIQUE (case-insensitive via `lower`); CHECK `~ '^[A-Za-z0-9 _-]{1,80}$'` (R36) | `uq_channels_name_lower` |
| channels.is_private | boolean | No | — | public → directly joinable; private → admin-gated (R5) | No |
| channels.created_by | uuid | No | — | FK → users(id) ON DELETE RESTRICT; first admin (R4) | No |
| channels.created_at | timestamptz | No | now() | server-set | No |

### channel_members
| Table.field | Type | Null? | Default | Constraints | Index? |
|-------------|------|-------|---------|-------------|--------|
| channel_members.channel_id | uuid | No | — | FK → channels(id) ON DELETE CASCADE; part of PK | PK part |
| channel_members.user_id | uuid | No | — | FK → users(id) ON DELETE RESTRICT; part of PK | PK part + `ix_channel_members_user` |
| channel_members.role | channel_member_role | No | 'member' | enum member/admin (R6) | partial in succession index |
| channel_members.joined_at | timestamptz | No | now() | earliest admin = succession heir (R51) | `ix_channel_members_admin_succession` |

Composite PRIMARY KEY `(channel_id, user_id)` = one row per membership; doubles as the O(log n) membership-check index (F34).

### messages
| Table.field | Type | Null? | Default | Constraints | Index? |
|-------------|------|-------|---------|-------------|--------|
| messages.id | uuid | No | — (app UUIDv7, time-sortable) | PK | PK btree |
| messages.channel_id | uuid | Yes | NULL | FK → channels(id) ON DELETE RESTRICT; XOR recipient_id | `ix_messages_channel_history` |
| messages.recipient_id | uuid | Yes | NULL | FK → users(id) ON DELETE RESTRICT; XOR channel_id; DM only | `ix_messages_dm_history` (functional) |
| messages.sender_id | uuid | No | — | FK → users(id) ON DELETE RESTRICT | No (see note) |
| messages.content | text | No | — | CHECK `char_length(content) <= 4000 AND btrim(content) <> ''` (R36) | No |
| messages.created_at | timestamptz | No | now() | authoritative order; tie-break by id (R39) | in history indexes |
| messages.edited_at | timestamptz | Yes | NULL | set on edit; id/order unchanged (R9) | No |
| messages.deleted_at | timestamptz | Yes | NULL | soft delete; row retained, excluded from history (R10, F44) | partial-index predicate |

*Note:* no standalone `sender_id` index — no hot query filters by sender alone; adding one would tax every insert. `content` uses `text` + CHECK (idiomatic) rather than `varchar(4000)`.

### attachments
Media metadata (ADR-0007, F57–F62). API field mapping for `backend-engineer`: API `media_id` = `attachments.id`; API `size` = `attachments.byte_size`; API `kind` = `attachments.kind`; API `filename` = `attachments.filename`. The API `media[]` array on message read/WS payloads is built by selecting `attachments WHERE message_id = :message_id`.

| Table.field | Type | Null? | Default | Constraints | Index? |
|-------------|------|-------|---------|-------------|--------|
| attachments.id | uuid | No | — (app UUIDv7) | PK; = API `media_id` | PK btree |
| attachments.message_id | uuid | Yes | NULL | FK → messages(id) ON DELETE CASCADE; **nullable** — upload precedes message-create in the two-phase flow (`POST /v1/media` then `media_ids[]` on send); orphans (still NULL) are swept (F62) | `ix_attachments_message` (partial) + `ix_attachments_orphans` (partial) |
| attachments.uploader_id | uuid | No | — | FK → users(id) ON DELETE RESTRICT; who uploaded (authz + audit, F59) | No |
| attachments.kind | attachment_kind | No | — | enum image/file/video; drives per-kind size cap | No |
| attachments.content_type | text | No | — | MIME type; allowlist enforced app-side, **SVG excluded** (R31/R32) | No |
| attachments.storage_key | text | No | — | opaque object-store key; **not a URL** (signed URLs are issued at fetch time) | No |
| attachments.filename | text | No | — | sanitized original name (R33); **PII** (may embed a name) — never logged raw (R24) | No |
| attachments.byte_size | bigint | No | — | CHECK `> 0` and per-kind cap (image ≤ 10 MB, file ≤ 50 MB, video ≤ 200 MB) | No |
| attachments.created_at | timestamptz | No | now() | server-set; drives orphan-sweep age | in `ix_attachments_orphans` |

*Width/height omitted deliberately:* no v1 query or API field consumes image dimensions (the `media[]` payload returns only `{media_id, kind, filename, size}`, and clients size images from the fetched bytes). Adding them now would be speculative columns with no reader; they can be added later as a nullable expand migration if a layout/thumbnail feature needs them.

### invites
| Table.field | Type | Null? | Default | Constraints | Index? |
|-------------|------|-------|---------|-------------|--------|
| invites.id | uuid | No | — (app UUIDv7) | PK | PK btree |
| invites.email | text | No | — | invited address; locks registration email (R45) | `ix_invites_email_pending` (partial) |
| invites.token_hash | text | No | — | UNIQUE; hash of single-use token; raw never stored/logged (R24) | `uq_invites_token_hash` |
| invites.status | invite_status | No | 'pending' | enum pending/accepted/revoked; expired derived from `expires_at` (F7) | in partial index |
| invites.created_by | uuid | No | — | FK → users(id) ON DELETE RESTRICT; audit (R45) | No |
| invites.expires_at | timestamptz | No | — | 7 days from issue (R45) | No |
| invites.accepted_at | timestamptz | Yes | NULL | set when redeemed | No |
| invites.created_at | timestamptz | No | now() | server-set | No |

### password_reset_tokens
| Table.field | Type | Null? | Default | Constraints | Index? |
|-------------|------|-------|---------|-------------|--------|
| password_reset_tokens.id | uuid | No | — (app UUIDv7) | PK | PK btree |
| password_reset_tokens.user_id | uuid | No | — | FK → users(id) ON DELETE CASCADE | `ix_prt_user_active` (partial) |
| password_reset_tokens.token_hash | text | No | — | UNIQUE; hash of single-use token (R24) | `uq_prt_token_hash` |
| password_reset_tokens.expires_at | timestamptz | No | — | 1 hour from issue (R48) | No |
| password_reset_tokens.used_at | timestamptz | Yes | NULL | only latest unused+unexpired is valid (F17) | in partial index |
| password_reset_tokens.created_at | timestamptz | No | now() | server-set | No |

### sessions
| Table.field | Type | Null? | Default | Constraints | Index? |
|-------------|------|-------|---------|-------------|--------|
| sessions.id | uuid | No | — (app UUIDv7) | PK; = `sid` claim in access JWT (ADR-0006) | PK btree |
| sessions.user_id | uuid | No | — | FK → users(id) ON DELETE CASCADE | `ix_sessions_user_active` (partial) |
| sessions.refresh_token_hash | text | No | — | UNIQUE; hash of opaque refresh token; raw never stored/logged (R24) | `uq_sessions_refresh_hash` |
| sessions.user_agent | text | Yes | NULL | device/agent metadata | No |
| sessions.ip_address | inet | Yes | NULL | PII; last observed client IP | No |
| sessions.issued_at | timestamptz | No | now() | server-set | No |
| sessions.last_used_at | timestamptz | Yes | NULL | updated on refresh | No |
| sessions.expires_at | timestamptz | No | — | 30-day sliding; extended on refresh (F12) | No |
| sessions.revoked_at | timestamptz | Yes | NULL | revocation source of truth; logout/reset/deactivate (F14/F16/F25) | in partial index |

## Indexing strategy

| Index | Columns | Type | Rationale (query it serves) |
|-------|---------|------|-----------------------------|
| users_pkey | (id) | btree PK | Point lookups by user id (auth `sub`, FK targets). |
| uq_users_username_lower | (lower(username)) | unique btree (functional) | Enforce case-insensitive unique username; login by username. |
| uq_users_email_lower | (lower(email)) | unique btree (functional) | Enforce case-insensitive unique email; login + invite email lock. |
| channels_pkey | (id) | btree PK | Channel point lookups. |
| uq_channels_name_lower | (lower(name)) | unique btree (functional) | Workspace-unique channel name (R36); browse-by-name. |
| channel_members_pkey | (channel_id, user_id) | btree PK | **Membership check on every message read/write** (F34): `WHERE channel_id=? AND user_id=?` — O(log n). |
| ix_channel_members_user | (user_id) | btree | "My channels" list: `WHERE user_id=?`. |
| ix_channel_members_admin_succession | (channel_id, joined_at) `WHERE role='admin'` | partial btree | Last-admin succession (F36/R51): earliest-joined admin `WHERE channel_id=? AND role='admin' ORDER BY joined_at ASC LIMIT 1`; cheap admin-count for zero-admin terminal state (F37). |
| ix_messages_channel_history | (channel_id, created_at, id) `WHERE deleted_at IS NULL AND channel_id IS NOT NULL` | partial btree | **Channel history keyset scan** (ADR-0003): `WHERE channel_id=? AND (created_at,id) < (?,?) ORDER BY created_at DESC, id DESC LIMIT n`. Partial predicate excludes soft-deleted rows (F44); backward index scan serves DESC ordering. Also serves reconnect catch-up (F55). |
| ix_messages_dm_history | (least(sender_id,recipient_id), greatest(sender_id,recipient_id), created_at, id) `WHERE recipient_id IS NOT NULL AND deleted_at IS NULL` | partial btree (functional) | **DM history keyset scan** (ADR-0002/0003): query on canonical user-pair `WHERE least(...)=? AND greatest(...)=? AND (created_at,id) < (?,?) ORDER BY created_at DESC, id DESC`. Query MUST use the same `least/greatest` expressions to hit the index. |
| ix_attachments_message | (message_id) `WHERE message_id IS NOT NULL` | partial btree | Fetch a message's media to build the API `media[]` array: `WHERE message_id=?`. Partial predicate keeps orphaned rows out of this index, shrinking it and keeping the common lookup tight. |
| ix_attachments_orphans | (created_at) `WHERE message_id IS NULL` | partial btree | **Orphan cleanup sweep** (F62): find unbound uploads older than a TTL, `WHERE message_id IS NULL AND created_at < now() - :ttl`. Partial + `created_at`-ordered so the sweep is an efficient range scan over only the (small) orphan set. |
| uq_invites_token_hash | (token_hash) | unique btree | Redeem invite by token: `WHERE token_hash=?`; enforce single-use uniqueness. |
| ix_invites_email_pending | (email) `WHERE status='pending'` | partial btree | Prevent/resend duplicate pending invites; admin listing of open invites. |
| uq_prt_token_hash | (token_hash) | unique btree | Validate reset token: `WHERE token_hash=?`. |
| ix_prt_user_active | (user_id) `WHERE used_at IS NULL` | partial btree | Enforce "only latest valid" (F17): find/invalidate a user's outstanding unused tokens. |
| uq_sessions_refresh_hash | (refresh_token_hash) | unique btree | Refresh-token exchange: `WHERE refresh_token_hash=?` (F12). |
| ix_sessions_user_active | (user_id) `WHERE revoked_at IS NULL` | partial btree | List active sessions; **revoke-all on password change/reset/deactivation** (F16/F22/F25); Postgres fallback for the Redis revocation check (ADR-0006). |

Every non-PK index above is justified by a named query; none is speculative. Write cost is bounded: `messages` inserts touch only the two partial history indexes (a row hits exactly one — channel XOR DM); `attachments` inserts land first in `ix_attachments_orphans` (unbound) then migrate to `ix_attachments_message` on bind. UUIDv7 time-ordering keeps all these inserts near-append.

## Integrity & invariants

**Primary keys:** every table has a UUIDv7 PK; `channel_members` uses composite PK `(channel_id, user_id)` (natural, prevents duplicate membership).

**Foreign keys** (referential integrity — users are never hard-deleted in v1, so `RESTRICT` is the conservative default; `CASCADE` only where a child is meaningless without its parent):
- `channels.created_by → users(id)` ON DELETE RESTRICT
- `channel_members.channel_id → channels(id)` ON DELETE CASCADE; `channel_members.user_id → users(id)` ON DELETE RESTRICT
- `messages.channel_id → channels(id)` ON DELETE RESTRICT; `messages.recipient_id → users(id)` ON DELETE RESTRICT; `messages.sender_id → users(id)` ON DELETE RESTRICT
- `attachments.message_id → messages(id)` ON DELETE CASCADE (an attachment is meaningless without its message; cascade cleans metadata rows — object-store bytes are purged by a separate reaper); `attachments.uploader_id → users(id)` ON DELETE RESTRICT
- `invites.created_by → users(id)` ON DELETE RESTRICT
- `password_reset_tokens.user_id → users(id)` ON DELETE CASCADE
- `sessions.user_id → users(id)` ON DELETE CASCADE

**Unique constraints:** `lower(username)`, `lower(email)`, `lower(channels.name)`, `invites.token_hash`, `password_reset_tokens.token_hash`, `sessions.refresh_token_hash`.

**CHECK constraints / in-DB invariants:**
- **Message XOR + no self-DM** (ADR-0002, F47): `CHECK ( (channel_id IS NOT NULL AND recipient_id IS NULL) OR (channel_id IS NULL AND recipient_id IS NOT NULL AND recipient_id <> sender_id) )`.
- **Message content** (R36): `CHECK (char_length(content) <= 4000 AND btrim(content) <> '')`.
- **Channel name** (R36): `CHECK (name ~ '^[A-Za-z0-9 _-]{1,80}$')`.
- **Attachment size** (F57–F58): `CHECK (byte_size > 0)` plus a per-kind cap expressed cleanly as `CHECK (byte_size <= CASE kind WHEN 'image' THEN 10485760 WHEN 'file' THEN 52428800 WHEN 'video' THEN 209715200 END)`. This is defense-in-depth; the upload service still enforces the cap (and streaming/size-limit) **before** persisting, since a row is only written after a successful, sniffed upload (R30/R42). The `content_type` allowlist and SVG exclusion are enforced app-side (not cheaply expressible as a stable in-DB list) and reviewed by `security-reviewer` (R31/R32).
- **Non-empty names:** `CHECK (btrim(first_name) <> '' AND btrim(last_name) <> '')`; `CHECK (char_length(username) BETWEEN 1 AND 32)`.

**Invariants enforced in application logic (not expressible cheaply in-DB), flagged for `backend-engineer`/`security-reviewer`:**
- Username/email **immutability** after registration (R27).
- "Only the **latest** reset token is valid" (F17) — service invalidates prior tokens on issue; `ix_prt_user_active` makes the sweep cheap.
- **Channel membership / DM participant / attachment authorization** on every read/write and media fetch (F34/F59) — server-side, never trusting a client-supplied id. On message-create, the server verifies each supplied `media_id` was uploaded by the sender and is still unbound before binding it.
- **Media allowlist + content sniff + EXIF strip** before persist (F57–F62, R30–R33) — pipeline concern, not a DB constraint.
- **Last-admin succession** and **zero-admin terminal state** (F36/F37) — transactional service logic backed by `ix_channel_members_admin_succession`.

## Migration plan (expand → migrate → contract)

This is a **greenfield initial migration**: it creates the entire schema from empty. There is no existing data, so steps 2–4 are trivially empty for this migration; they define how **all future** changes are made.

1. **Expand** — The initial migration is pure expand: create enum types, then tables in FK-dependency order (`users` → `channels` → `channel_members` → `messages` → `attachments` → `invites` → `password_reset_tokens` → `sessions`), then indexes. Purely additive against an empty database; nothing dropped or narrowed.
2. **Backfill** — None (empty DB). *Future pattern:* new columns land nullable/defaulted, data backfilled in **resumable batches** (`WHERE id > :cursor ... LIMIT :batch`) to avoid long-held locks; large backfills run out-of-band, never inside the DDL transaction.
3. **Switch** — None (no prior shape). *Future pattern:* deploy app code that reads/writes the new shape while the old shape still exists (dual-write / read-new-fallback-old) so a rollback needs only a code revert.
4. **Contract** — None. *Future pattern:* after a bake period, a **separate later** migration drops the retired object. Destructive contracts are 🔒-gated (footer). Shipped migrations are **never edited** — only new ones added (`CLAUDE.md` boundaries).

**Annotated initial-schema DDL (concrete UP):**

```sql
-- === UP: chatspace v1 initial schema =====================================
-- No extensions required. UUIDv7 PKs are supplied by the application layer.
-- All timestamps are timestamptz (UTC).

-- Enum types -------------------------------------------------------------
CREATE TYPE channel_member_role AS ENUM ('member', 'admin');
CREATE TYPE invite_status       AS ENUM ('pending', 'accepted', 'revoked');
CREATE TYPE attachment_kind     AS ENUM ('image', 'file', 'video');

-- users ------------------------------------------------------------------
CREATE TABLE users (
    id               uuid        PRIMARY KEY,                         -- app UUIDv7
    username         text        NOT NULL,
    email            text        NOT NULL,
    hashed_password  text        NOT NULL,                            -- bcrypt/argon2; never returned/logged
    first_name       text        NOT NULL,
    last_name        text        NOT NULL,
    avatar_url       text,
    is_active        boolean     NOT NULL DEFAULT true,
    is_system_admin  boolean     NOT NULL DEFAULT false,
    last_seen        timestamptz,                                     -- durable (R44)
    created_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_users_username_len  CHECK (char_length(username) BETWEEN 1 AND 32),
    CONSTRAINT ck_users_names_present CHECK (btrim(first_name) <> '' AND btrim(last_name) <> '')
);
CREATE UNIQUE INDEX uq_users_username_lower ON users (lower(username));
CREATE UNIQUE INDEX uq_users_email_lower    ON users (lower(email));

-- channels ---------------------------------------------------------------
CREATE TABLE channels (
    id          uuid        PRIMARY KEY,                              -- app UUIDv7
    name        text        NOT NULL,
    is_private  boolean     NOT NULL,
    created_by  uuid        NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_channels_name CHECK (name ~ '^[A-Za-z0-9 _-]{1,80}$')
);
CREATE UNIQUE INDEX uq_channels_name_lower ON channels (lower(name));

-- channel_members --------------------------------------------------------
CREATE TABLE channel_members (
    channel_id  uuid                NOT NULL REFERENCES channels (id) ON DELETE CASCADE,
    user_id     uuid                NOT NULL REFERENCES users (id)    ON DELETE RESTRICT,
    role        channel_member_role NOT NULL DEFAULT 'member',
    joined_at   timestamptz         NOT NULL DEFAULT now(),
    PRIMARY KEY (channel_id, user_id)
);
CREATE INDEX ix_channel_members_user ON channel_members (user_id);
CREATE INDEX ix_channel_members_admin_succession
    ON channel_members (channel_id, joined_at) WHERE role = 'admin';

-- messages (channel messages AND DMs) ------------------------------------
CREATE TABLE messages (
    id            uuid        PRIMARY KEY,                            -- app UUIDv7 (time-sortable)
    channel_id    uuid        REFERENCES channels (id) ON DELETE RESTRICT,
    recipient_id  uuid        REFERENCES users (id)    ON DELETE RESTRICT,
    sender_id     uuid        NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    content       text        NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),                -- authoritative order
    edited_at     timestamptz,
    deleted_at    timestamptz,                                       -- soft delete
    -- Exactly one of channel_id / recipient_id set; DM never to self (ADR-0002, F47)
    CONSTRAINT ck_messages_target_xor CHECK (
        (channel_id IS NOT NULL AND recipient_id IS NULL)
        OR (channel_id IS NULL AND recipient_id IS NOT NULL AND recipient_id <> sender_id)
    ),
    CONSTRAINT ck_messages_content CHECK (char_length(content) <= 4000 AND btrim(content) <> '')
);
-- Channel history keyset scan, soft-deleted excluded (ADR-0003, F44)
CREATE INDEX ix_messages_channel_history
    ON messages (channel_id, created_at, id)
    WHERE deleted_at IS NULL AND channel_id IS NOT NULL;
-- DM history keyset scan on canonical user-pair (ADR-0002/0003)
CREATE INDEX ix_messages_dm_history
    ON messages (least(sender_id, recipient_id), greatest(sender_id, recipient_id), created_at, id)
    WHERE recipient_id IS NOT NULL AND deleted_at IS NULL;

-- attachments (media metadata; bytes in object storage, ADR-0007) --------
CREATE TABLE attachments (
    id            uuid            PRIMARY KEY,                        -- app UUIDv7; API media_id
    message_id    uuid            REFERENCES messages (id) ON DELETE CASCADE,  -- NULL until bound (two-phase)
    uploader_id   uuid            NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    kind          attachment_kind NOT NULL,
    content_type  text            NOT NULL,                           -- MIME; allowlist app-side, SVG excluded
    storage_key   text            NOT NULL,                           -- opaque object-store key; NOT a URL
    filename      text            NOT NULL,                           -- sanitized; PII; never logged raw
    byte_size     bigint          NOT NULL,                           -- API size
    created_at    timestamptz     NOT NULL DEFAULT now(),
    CONSTRAINT ck_attachments_size_positive CHECK (byte_size > 0),
    CONSTRAINT ck_attachments_size_cap CHECK (
        byte_size <= CASE kind
            WHEN 'image' THEN 10485760      -- 10 MB
            WHEN 'file'  THEN 52428800      -- 50 MB
            WHEN 'video' THEN 209715200     -- 200 MB
        END
    )
);
-- Fetch a message's media for the API media[] array
CREATE INDEX ix_attachments_message ON attachments (message_id) WHERE message_id IS NOT NULL;
-- Orphan cleanup sweep for unbound uploads (F62)
CREATE INDEX ix_attachments_orphans ON attachments (created_at) WHERE message_id IS NULL;

-- invites ----------------------------------------------------------------
CREATE TABLE invites (
    id          uuid          PRIMARY KEY,                           -- app UUIDv7
    email       text          NOT NULL,
    token_hash  text          NOT NULL,                              -- hash of single-use token
    status      invite_status NOT NULL DEFAULT 'pending',
    created_by  uuid          NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    expires_at  timestamptz   NOT NULL,                              -- 7 days
    accepted_at timestamptz,
    created_at  timestamptz   NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_invites_token_hash ON invites (token_hash);
CREATE INDEX ix_invites_email_pending ON invites (email) WHERE status = 'pending';

-- password_reset_tokens --------------------------------------------------
CREATE TABLE password_reset_tokens (
    id          uuid        PRIMARY KEY,                             -- app UUIDv7
    user_id     uuid        NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_hash  text        NOT NULL,                                -- hash of single-use token
    expires_at  timestamptz NOT NULL,                                -- 1 hour
    used_at     timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_prt_token_hash ON password_reset_tokens (token_hash);
CREATE INDEX ix_prt_user_active ON password_reset_tokens (user_id) WHERE used_at IS NULL;

-- sessions (revocable session / refresh-token store, ADR-0006) -----------
CREATE TABLE sessions (
    id                  uuid        PRIMARY KEY,                     -- session_id (sid in JWT)
    user_id             uuid        NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    refresh_token_hash  text        NOT NULL,                        -- hash of opaque refresh token
    user_agent          text,
    ip_address          inet,                                        -- PII
    issued_at           timestamptz NOT NULL DEFAULT now(),
    last_used_at        timestamptz,
    expires_at          timestamptz NOT NULL,                        -- 30-day sliding
    revoked_at          timestamptz
);
CREATE UNIQUE INDEX uq_sessions_refresh_hash ON sessions (refresh_token_hash);
CREATE INDEX ix_sessions_user_active ON sessions (user_id) WHERE revoked_at IS NULL;
-- === end UP ==============================================================
```

**Reverse (concrete DOWN):**

```sql
-- === DOWN: drop everything in reverse dependency order ===================
-- attachments references messages -> drop attachments BEFORE messages.
DROP TABLE IF EXISTS sessions;
DROP TABLE IF EXISTS password_reset_tokens;
DROP TABLE IF EXISTS invites;
DROP TABLE IF EXISTS attachments;
DROP TABLE IF EXISTS messages;
DROP TABLE IF EXISTS channel_members;
DROP TABLE IF EXISTS channels;
DROP TABLE IF EXISTS users;
DROP TYPE  IF EXISTS attachment_kind;
DROP TYPE  IF EXISTS invite_status;
DROP TYPE  IF EXISTS channel_member_role;
-- === end DOWN ============================================================
```

- **Reversibility:** the down-migration is provided above and is a clean, total reversal — the schema returns to empty. It is safe to test on a scratch database (create → drop → re-create) in CI before the runnable Alembic version is authored by `backend-engineer`. Indexes/constraints are owned by their tables, so `DROP TABLE` removes them implicitly; `attachments` is dropped **before** `messages` (it FKs to it), and enum `DROP TYPE`s come last. *(Note: dropping `attachments` removes only metadata rows — the corresponding object-store bytes must be reaped by the media service; a schema down-migration cannot touch object storage.)*
- **Locking/downtime:** none of consequence. All `CREATE`s target empty/new objects and take only brief catalog locks; no existing traffic or data to block, so this runs online with effectively zero downtime. *(Future note: on a populated hot table, index builds must use `CREATE INDEX CONCURRENTLY` outside a transaction, and column adds must be nullable/defaulted to avoid a rewrite; not applicable to this greenfield create.)*
- **Rollback:** because the DB starts empty, rollback is the DOWN script (drops all objects) with no data loss possible. For any *future* migration, rollback = revert app code first (expand/switch guarantees the old shape still works), then run the paired downgrade; genuinely irreversible steps (destructive contracts) are called out and 🔒-gated rather than auto-run.

## Performance considerations

**Scale target:** ~1,000 concurrent users on a single Postgres + single Redis + 1–2 FastAPI instances (`CLAUDE.md` principle #7). No sharding, no partitioning, no read replicas in v1.

**Row-count / growth estimates:**
- `users` — ~1,000 rows; negligible.
- `channels` — hundreds; negligible.
- `channel_members` — ~1,000 users × ~20 channels ≈ 20k rows; trivial, fully cacheable.
- `messages` — the primary growth table. At ~1,000 users sending tens of messages/day → ~10–50k rows/day → single-digit-to-~18M rows/year. A single Postgres b-tree handles this comfortably; UUIDv7 time-ordering keeps inserts near-append (low write amplification, good right-hand-page cache locality).
- `attachments` — grows as a **fraction** of `messages` (only messages that carry media, and media messages are a minority in team chat), so well below the message rate — on the order of thousands-to-low-tens-of-thousands of rows/year. Rows are small (metadata only; bytes are in object storage). Orphan rows (`message_id IS NULL`) are short-lived and swept, so `ix_attachments_orphans` stays tiny.
- `sessions`, `invites`, `password_reset_tokens` — thousands of live rows at most; expired/revoked rows swept by scheduled purge, keeping active partial indexes small.

**Hot queries and the indexes that serve them:**
- **Channel history (hottest read):** keyset scan served by `ix_messages_channel_history` (partial, soft-deleted excluded) — O(log n + page), independent of scroll depth, meeting the p95 < 300 ms read budget (ADR-0003). Backward scan yields DESC order without a sort.
- **DM history:** same keyset shape on the canonical user-pair, served by `ix_messages_dm_history`; queries must use identical `least/greatest(sender_id, recipient_id)` expressions to match.
- **Message media hydration:** building each rendered message's `media[]` array is `SELECT ... FROM attachments WHERE message_id = ?` via `ix_attachments_message`. For a history page of N messages, this is either N tiny index probes or a single `WHERE message_id = ANY(:ids)` batch fetch (recommended for `backend-engineer` to avoid N+1) — both index-served and cheap since media rows per message are few.
- **Orphan cleanup (F62):** the reaper runs `WHERE message_id IS NULL AND created_at < now() - :ttl` via `ix_attachments_orphans` — an efficient range scan over only the small orphan set; it never touches the bound-attachment index.
- **Membership check on every message read/write (F34):** single index probe on the `channel_members` PK; table fits in memory → effectively free.
- **Session revocation check (per request, ADR-0006):** served from **Redis** (O(1)); Postgres `sessions` is the durable fallback via `uq_sessions_refresh_hash` and `ix_sessions_user_active`. Not on the per-request critical path when Redis is healthy.
- **Presence / typing / rate-limit:** entirely in **Redis** — absent from Postgres, removing the highest-churn writes from the durable store.

**Partitioning / caching:** not needed at this scale. If `messages` growth materially exceeds these estimates (hot index falling out of cache), the future move is **monthly range partitioning of `messages` on `created_at`** (and, if it ever grows, `attachments` alongside) — recorded as an ADR when real usage warrants it (constitution #7), not pre-emptively. Connection pooling via the `asyncpg` pool per instance; PgBouncer only if connection counts warrant it (not expected at 1,000 users).

## Open questions

1. **Invite/reset retention & purge cadence.** Retention above proposes scheduled purge of expired `sessions` and `password_reset_tokens`, orphan-sweep of unbound `attachments`, and audit-retention of `invites`. The exact intervals — orphan-attachment TTL, and whether accepted/revoked invites are retained indefinitely for audit vs. purged after N days — are policy decisions for PM to confirm (interacts with the R47 "retain deactivated-user data as-is" stance). The orphan-attachment TTL must also be coordinated with the object-store lifecycle policy so metadata and bytes are reaped consistently.
2. **Workspace-role encoding.** FS §7 models workspace role as an enum; this design uses `is_system_admin boolean` per the DOMAIN MODEL/task. Flagged only so a future third workspace role is handled as a deliberate expand migration rather than a surprise.

---
🔒 Migrations against shared/prod environments require human approval.
