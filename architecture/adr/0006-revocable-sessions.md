# ADR-0006: Revocable sessions — server-side session store + Redis revocation check

> Owner: `architect` / `documentation-writer`. Indexed in `architecture/adr/README.md`.

- **Status:** Proposed
- **Date:** 2026-07-02
- **Deciders:** architect + human architecture gate
- **Tags:** security, auth, session

## Context
v1 needs **revocable sessions** (R35). Login issues a short-lived access token (15 min) plus a refresh token (30-day sliding) and establishes a **revocable session** (F10). The system must:
- **Logout** invalidates the *current* session only; other sessions unaffected (F14, R34).
- **Password change / reset** invalidates all of the user's *other* active sessions (F16, F22, R29/R48).
- **System-Admin deactivation** invalidates *all* of the target's sessions immediately and drops open WebSockets within the revalidation window (F25, R47).
- **WebSocket** authenticates before joining and is revalidated periodically so revoked/expired/deactivated tokens are dropped mid-connection (F52, R16).

The open decision (PRD §12, spec §9): `token_version`-per-request vs refresh-token store/denylist vs short-TTL+rotation only. Because per-session revocation (logout one device, keep others) is required, per-user versioning alone is insufficient, and pure short-TTL cannot meet "immediate" invalidation or per-session granularity.

The forcing question: what is the source of truth for a session, and how do we revoke access before a 15-minute access token naturally expires?

## Decision
We will maintain a **server-side session store** with a **Redis-backed revocation check**:

- **Session record (source of truth, Postgres `sessions` table):** `session_id`, `user_id`, hashed refresh token, issued/expiry, `revoked_at`, device/agent metadata (no PII beyond what is needed). One row per login = one revocable session.
- **Access token = short-lived (15 min) signed JWT** carrying `sub` (user_id), `sid` (session_id), and `iat`/`exp`. JWT signing key from env via `pydantic-settings` (never committed/logged, R2/R24).
- **Refresh token = opaque, cryptographically random**, stored **hashed** in the session row; exchanged for a new access token (F12) and slides the session expiry.
- **Revocation check:** every authenticated REST request and every periodic WebSocket revalidation checks that `sid` maps to an **active, non-revoked** session **and** that the user is `is_active`. This check is served from a **Redis cache of session state** (O(1)), with a Postgres fallback; cache entries carry a TTL ≤ the access-token TTL so the cache self-heals. Revocation writes `revoked_at` in Postgres and evicts/marks the Redis entry, so subsequent requests fail fast.
- **Revocation semantics:** logout revokes one `sid`; password change/reset revokes all sessions except the initiating one; deactivation revokes all sessions for the user. WebSocket revalidation (heartbeat-driven, F52) re-runs the same check and closes connections whose `sid` is revoked or whose user is deactivated, with a documented close code (F70).

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| A (chosen) — Session store (Postgres) + `sid` in JWT + Redis revocation cache | Per-session revocation (logout one device, revoke others) — the only option that meets F14/F16/F22; near-immediate revocation via Redis check; durable session truth survives Redis restart; supports "list/kill my sessions" later | Adds a session lookup to auth (mitigated by Redis O(1) cache); revocation correctness depends on cache eviction being reliable |
| B — `token_version` column per user (bump to invalidate) | Very simple; one integer check | Cannot revoke a *single* session while keeping others (logout would kill all devices) — fails F14/F16 "other sessions unaffected/invalidated" granularity |
| C — Short-TTL access tokens + rotation only, no server store | Fully stateless; no revocation lookup | Cannot revoke before natural expiry → deactivation/logout not "immediate" (fails F25/F14); 15-min window of continued access is unacceptable for a security lever |

## Consequences
- **Positive:** Meets every revocation requirement with per-session granularity. Redis check keeps the hot path fast while Postgres remains the durable truth (survives a Redis restart — a revoked session stays revoked). WebSocket mid-connection drop reuses the same check on the heartbeat (F52). Foundation for a future "active sessions" management UI at near-zero extra cost.
- **Negative / trade-offs:** Auth is no longer purely stateless — there is a per-request revocation check. We accept this for the security guarantee; the Redis cache keeps it cheap. If Redis is down, the check falls back to Postgres (higher latency but correct) — sessions stay enforceable, unlike delivery/presence which degrade. Revocation is near-immediate for REST (bounded by cache eviction) and bounded by the heartbeat interval for WebSockets (F52) — this residual lag is a documented risk (TSD §12).
- **Follow-ups:** `database-engineer` designs the `sessions` table and its indexes in the DB-design instance; `security-reviewer` reviews the revocation flows (logout, change/reset, deactivation) and the WS revalidation close-code scheme in the threat model; `backend-engineer` sets the heartbeat/revalidation interval and wires the Redis cache with self-healing TTL; the interval choice bounds the mid-connection revocation lag and must be recorded.

## Compliance / reversibility
Reversible but security-sensitive: changing the session model later touches every auth path and would invalidate outstanding tokens (forced re-login) — a one-time cost, not a data loss. This directly implements the R35 security requirement, so `security-reviewer` sign-off at the 🔒 gate is required. No external regulatory regime is in scope, but sessions and refresh tokens are sensitive and must never be logged (R24).
