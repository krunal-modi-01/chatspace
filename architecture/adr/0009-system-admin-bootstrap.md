# ADR-0009: System Admin bootstrap — env-seeded at startup

> Owner: `architect` / `documentation-writer`. Indexed in `architecture/adr/README.md`.

- **Status:** Proposed
- **Date:** 2026-07-02
- **Deciders:** architect + human architecture gate
- **Tags:** security, auth, bootstrap, deployment

## Context
Registration is reachable **only** via a System-Admin-issued invite (F6, R1/R45) — there is no invite-less path. Therefore the very first System Admin cannot be created by an invite; it must be **bootstrapped**. Exactly one default System Admin must be created automatically at first deployment, the step **must not be skippable**, and the workspace must never be in a zero-admin state (F8, R46). The bootstrap admin must be able to immediately issue invites and has no special channel/message powers (F9). The open decision (PRD §12, spec §9): env-var-seeded account vs a first-run CLI / setup wizard.

The forcing question: what mechanism creates the first System Admin safely, without leaving an unauthenticated setup surface or a skippable step?

## Decision
We will **seed the bootstrap System Admin from environment variables at application startup**, idempotently:

- On startup, if the `users` table has **zero users**, the app **requires** bootstrap config (`BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_USERNAME`, and a `BOOTSTRAP_ADMIN_PASSWORD`) supplied via env / `pydantic-settings`. It creates exactly **one** active `system_admin` user with the password hashed (bcrypt/argon2), email marked verified, and **flags the account to force a password change on first login**.
- The routine is **idempotent**: it runs only when user count is zero, so restarts never create duplicates and never touch an existing workspace.
- The step is **non-skippable / fail-loud**: if there are zero users and bootstrap config is missing or invalid, the app **refuses to serve** (startup fails with a clear operator error) rather than starting in a zero-admin state. This is enforced alongside the transactional-email-configured check (ADR-0010), since both are hard first-run prerequisites.
- The bootstrap password is **never logged** (R24); the operator supplies it as a secret and is prompted to rotate it on first login.

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| A (chosen) — Env-seeded at startup, idempotent, fail-loud when zero users | No unauthenticated HTTP surface; naturally non-skippable (app won't serve without it); fits PaaS env-var secret model (ADR-0008); idempotent and restart-safe; force-password-change limits the standing-secret risk | Operator must set env vars before first boot; initial password lives in env until rotated (mitigated by forced change) |
| B — First-run web setup wizard | Familiar UX; operator sets credentials in a browser | Exposes an **unauthenticated** setup endpoint until claimed — an attack/race surface (whoever hits it first becomes admin); must be carefully gated and disabled after use; more code + a security-sensitive edge |
| C — CLI / management command (operator runs a one-off) | No standing secret in env; explicit operator action | Easy to **skip** → risks a zero-admin deployment (violates F8 "not skippable"); an extra manual step the operator can forget; harder to guarantee in a PaaS deploy flow |

## Consequences
- **Positive:** The workspace can never boot into a usable-but-zero-admin state — the app either has an admin or refuses to serve. No unauthenticated setup endpoint exists. The mechanism reuses the PaaS env-var secret pattern already used for JWT/DB/Redis/SMTP, so there is nothing new to operate. Forced password rotation on first login bounds the exposure of the seeded credential.
- **Negative / trade-offs:** The initial admin password exists as an env secret until the operator logs in and rotates it; this is a bounded, documented window. The operator must know to set the bootstrap env vars — covered by the getting-started note (PRD §10 comms) and the fail-loud startup error that tells them exactly what is missing.
- **Follow-ups:** `backend-engineer` implements the idempotent startup seed + force-password-change flag + fail-loud guard; `infrastructure-engineer`/`devops-engineer` document the required bootstrap env vars in the deploy runbook; `security-reviewer` confirms the seed path never logs the password and that the force-rotation flag is enforced on first login.

## Compliance / reversibility
Reversible and low-cost to change: the seed routine is isolated startup logic. Once at least one admin exists it never runs again, so switching to a different first-admin mechanism later is inconsequential. Security-sensitive (creates a privileged account and handles an initial secret), so it is in scope for `security-reviewer` at the 🔒 gate. No external regulatory implication.
