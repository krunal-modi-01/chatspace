# ADR-0010: Transactional email — provider-agnostic SMTP abstraction, fail-loud, no queue

> Owner: `architect` / `documentation-writer`. Indexed in `architecture/adr/README.md`.

- **Status:** Proposed
- **Date:** 2026-07-02
- **Deciders:** architect + human architecture gate
- **Tags:** email, integration, security, deployment

## Context
Invites (F1, R45) and self-service password reset (F15, R48) both require outbound transactional email. Email is a **hard first-run prerequisite** — the workspace is unusable until it is configured, and delivery failures must **fail loudly** (no silent drop, no queue-and-forget without retry/alerting) per spec §9 and PRD §8. The constitution forbids a message queue at this scale, so there is no async worker tier to lean on. There is a tension with the **non-enumeration** requirement: password-reset responses must be uniform regardless of whether the email exists (F15) and auth rate limiting must not reveal identifier existence (F64). The open decision (PRD §12): SMTP relay vs a provider API (SES/Postmark/etc.).

The forcing question: how do we send email portably, fail loudly, and preserve non-enumeration — without a queue?

## Decision
We will send email through a **provider-agnostic SMTP abstraction** (async SMTP client, e.g. `aiosmtplib`) behind a thin internal `EmailService` interface, configured via env / `pydantic-settings` (`SMTP_HOST/PORT/USER/PASSWORD/FROM`, TLS). Any provider works — a self-hosted relay or a transactional provider (SES, Postmark, etc.), since all expose SMTP — keeping the self-hostable ethos and deferring the concrete provider to deploy time (alongside ADR-0008).

- **First-run prerequisite / fail-loud startup:** the app validates that email config is present at startup (with the bootstrap check, ADR-0009) and refuses to serve if unusable, so the workspace never appears healthy while unable to onboard anyone.
- **No queue — inline send with bounded retry:** invite and reset emails are sent **inline** within the request with a short bounded retry. Since there is no message queue (constitution), we do not queue-and-forget.
- **Failure surfacing, reconciled with non-enumeration:**
  - **Invite (admin action, no enumeration concern):** if send fails after retries, **fail loudly to the System Admin** with a clear error (F1 / Flow A step 1c); do not record the invite as delivered.
  - **Password reset (must not reveal existence):** always return the **uniform response** (F15). When the email exists but send fails, log an **audit + alert event server-side** (without content/token, R24) so the operator is notified, but do **not** vary the client response — preserving non-enumeration.
- **Content hygiene:** emails carry single-use, time-limited, unguessable tokens (invite 7-day, reset 1-hour); tokens are **never logged** and audit events record issuance/redemption without the token or content (R24, F69).

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| A (chosen) — Provider-agnostic SMTP abstraction, inline send + bounded retry, fail-loud | Portable across self-hosted relays and all major providers (self-host ethos); no vendor SDK lock-in; no queue needed; fail-loud + audit satisfies §9/F1/F15 | Inline send adds latency to invite/reset requests; SMTP gives coarser delivery telemetry than a provider API |
| B — Hard-code a provider API SDK (e.g. SES/Postmark client) | Richer delivery events/bounce webhooks; possibly higher deliverability | Couples the deployment to one vendor; weakens self-hostability; every operator must use that vendor; more deps to vet |
| C — Queue-and-forget (background send) | Removes send latency from the request path | Explicitly disallowed by §9 ("no queue-and-forget without retry/alerting"); no queue infra at this scale anyway; hides failures — contradicts fail-loud |

## Consequences
- **Positive:** One email seam works from any operator's SMTP to any provider; fail-loud behaviour makes misconfiguration obvious at first run rather than as a silent onboarding failure; non-enumeration is preserved for reset by keeping the client response uniform while alerting the operator out-of-band.
- **Negative / trade-offs:** Inline send couples invite/reset request latency to SMTP responsiveness (bounded by retry limits and the auth rate limits). Coarser delivery insight than a provider API — acceptable at v1; a provider with SMTP still works through the same abstraction if richer telemetry is later wanted. If email is misconfigured at runtime (not just startup), invite requests error visibly and reset requests alert the operator.
- **Follow-ups:** `backend-engineer` implements `EmailService` (async SMTP + bounded retry) and the invite/reset templates; `devops-engineer`/`infrastructure-engineer` provision SMTP creds as env secrets and document them as a first-run prerequisite; `security-reviewer` confirms tokens/content never enter logs and that the reset path preserves non-enumeration under send failure; a follow-up ADR may adopt a provider API if deliverability/telemetry needs grow.

## Compliance / reversibility
Reversible cheaply: the `EmailService` interface isolates the transport, so swapping SMTP providers or adopting a provider API later is an implementation change behind a stable seam. Email addresses are PII and tokens are sensitive — neither is logged (R24). No external regulatory regime in scope at v1.
