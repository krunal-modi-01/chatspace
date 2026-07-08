# ADR-0011: Forced password-change unblock — reuse self-service reset, don't invent a scoped session

> Owner: `architect` / `documentation-writer`. Indexed in `architecture/adr/README.md`.
> Amends: [ADR-0009](0009-system-admin-bootstrap.md) (does not supersede it — ADR-0009's bootstrap decision stands; this ADR fills in a mechanism ADR-0009 left unspecified).

- **Status:** Proposed
- **Date:** 2026-07-08
- **Deciders:** architect + human architecture gate
- **Tags:** security, auth, bootstrap

## Context
ADR-0009 decided the bootstrap System Admin is created with `users.must_change_password=true` and said the account is "prompted to rotate it on first login" — but never specified the mechanism. T15 (`feat/batch-t15-t16-t17`, commit `b81b392`) implemented the only piece a security-reviewer conditional-pass required: `POST /v1/auth/login` checks the flag and rejects with `403 must-change-password` **before issuing any session**. That closed the "flag is inert" gap, but it also means the flagged account can never obtain a session — and `POST /v1/auth/password/change` (the only password-setting endpoint reachable by an authenticated user) requires exactly that. The result, discovered when actually exercising the built T30 login UI: the bootstrap admin is permanently locked out. There is no path in the shipped system for a `must_change_password` account to ever change its password.

This gap exists because "force a password change on first login" was never decomposed into a task (`docs/spec/chatspace-v1-task-breakdown.md` T15 lists login/refresh/logout/sessions only; `must_change_password` isn't mentioned) — it was patched into T15 mid-review as a compensating control, without anyone designing the unblock path.

Two already-shipped, already-reviewed pieces are relevant:
- `POST /v1/auth/password-reset` + `/password-reset/confirm` (T16): a fully public, unauthenticated, email-token-based flow that sets `user.hashed_password` without requiring a prior session.
- ADR-0010's Phase-0 constraint: transactional email is a non-skippable startup prerequisite, so if the app is serving at all, email delivery works — the reset flow is always usable.

The forcing question: what is the mechanism by which a `must_change_password`-flagged user (today, only the bootstrap admin; potentially others later) actually sets a new password and clears the flag, given login will not issue them a session?

## Decision
We will **not** introduce a new scoped/limited-session concept or a dedicated force-change endpoint. Instead:

- The `403 must-change-password` response (unchanged) is treated by the client as an instruction to use the existing **self-service password-reset flow** (T16), not as a dead end. The frontend surfaces a "Reset your password to continue" call-to-action linking to `/password-reset` when this specific problem `type` is received (no new backend contract surface).
- `POST /v1/auth/password-reset/confirm` additionally clears `must_change_password=false` on success, in the same transaction that sets the new `hashed_password` (`backend/app/api/password.py::confirm_password_reset`). Resetting the password is itself sufficient proof of rotation — no separate "confirm you rotated it" step is needed.
- `POST /v1/auth/password/change` (the authenticated in-app path) also clears `must_change_password=false` on success, for the (currently theoretical, but foreseeable — e.g. an admin later resetting another operator's flag) case where a non-flagged session somehow reaches this endpoint while the flag is set.
- No change to `POST /v1/auth/login`'s blocking behavior — it still rejects with `403` and issues no session while the flag is set. This preserves T15's security property (a standing operator-known credential can never be used to establish a session) with no new attack surface.

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| A (chosen) — Reuse T16 self-service reset; reset-confirm clears the flag | Zero new backend endpoints or contract surface (no fresh API-owner sign-off needed, unlike a new scoped-token type); reuses an already-shipped, already-security-reviewed flow end-to-end (email delivery, single-use token, non-enumeration); minimal diff (two `must_change_password = False` assignments + a frontend CTA); consistent with CLAUDE.md's "reuse over new abstraction" and 1,000-user-scale simplicity principle | Requires the admin to have working access to the bootstrap email inbox (already required — ADR-0010 makes email a hard Phase-0 dependency, so this is not a new requirement); one extra round-trip (request reset, then confirm) vs. a hypothetical single-shot change |
| B — Scoped/limited access token from login (`scope: password_change_only`), enforced in `require_auth` | Single round-trip login → change flow, no email dependency | New JWT claim + new enforcement branch in `require_auth` (touches the hottest security path in the codebase); a second undocumented contract addition on top of the still-unsigned-off `must-change-password` 403 (memory follow-up #2); more code, more attack surface, for a case (bootstrap-admin-only, today) that reset already solves |
| C — Dedicated public `POST /v1/auth/force-password-change` endpoint (email + current temp password + new password, no session) | No email round-trip | Duplicates almost all of the reset-confirm logic (policy check, hashing, session revocation) under a new route; a second public password-setting surface to secure and test; the "knows the temp password" check is weaker than a mailed single-use token (temp password may be shared/typed insecurely by an operator) |

## Consequences
- **Positive:** Closes the lockout with the smallest possible diff over already-reviewed code. No new contract surface requiring fresh API-owner/security sign-off. The flag now has a real, working exit path for the only account that can carry it today (bootstrap admin) and for any future feature that sets it on another user. Resolves memory follow-up #1 (`t15-must-enforce-must-change-password.md`) implicitly: since login never issues a session while the flag is set, `refresh_session` still has nothing to re-check — this ADR makes that invariant explicit rather than leaving it as an open question.
- **Negative / trade-offs:** The admin must complete an extra request→email→confirm round-trip instead of a single change-password call; acceptable given ADR-0010 already guarantees email works whenever the app is serving. The `403`'s `type: must-change-password` slug is now load-bearing for frontend routing logic (it must not be repurposed later without updating that redirect) — same contract-stability caveat memory follow-up #2 already flagged, not a new one introduced here.
- **Follow-ups:** `backend-engineer` implements the two `must_change_password = False` clears (task below); `frontend-engineer` adds the redirect-to-reset CTA on the `403 must-change-password` response; `documentation-writer` updates `t15-must-enforce-must-change-password.md` once shipped to mark both open follow-ups resolved; `security-reviewer` confirms clearing the flag on reset-confirm doesn't reopen the ADR-0009 threat model (it doesn't — reset already requires proving control of the registered email, a stronger bar than the original temp password).

## Compliance / reversibility
Fully reversible, low blast radius: two additional field assignments in already-reviewed transactions, plus a frontend conditional redirect. No schema change, no new migration, no new endpoint. Security-sensitive only insofar as it touches the ADR-0009 compensating control — reviewed by `security-reviewer` at the 🔒 gate before merge, per that ADR's own follow-up requirement.
