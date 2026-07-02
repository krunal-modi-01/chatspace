---
name: security
description: Threat modeling, secure-coding review, and vulnerability triage. Use when writing or reviewing anything that handles auth, secrets, user input, money, PII, or external requests; when doing a security review; or when a vuln-scan flags an issue. Stack-agnostic.
---

# Security Skill

## Purpose
Bring a consistent, standards-based security lens (OWASP ASVS / Top 10, CWE) to design, implementation, and review — so security is built in, not bolted on.

## When invoked
- Designing/reviewing auth, authorization, session, crypto, secrets handling.
- Any code touching untrusted input, money, or PII.
- Running a security review (`security-reviewer` agent).
- Triaging a `vuln-scan.sh` finding.

## Inputs
The diff or design under review, the data-flow (what's trusted vs untrusted), the threat model (`templates/threat-model.md`), and compliance constraints from `CLAUDE.md`.

## Outputs
- A threat model (STRIDE) for new surfaces.
- Ranked findings: CWE id · severity (CVSS-ish) · exploit scenario · remediation.
- A go / no-go for the 🔒 security gate.

## Procedure
1. **Map the surface.** Identify trust boundaries, entry points, and sensitive assets. What's attacker-controlled?
2. **STRIDE the design.** Spoofing, Tampering, Repudiation, Info-disclosure, DoS, Elevation — one pass per boundary.
3. **Review against the checklist** (`references/secure-coding-checklist.md`).
4. **Verify, don't assume.** For each suspected issue, construct a concrete exploit path. No path → mark "theoretical".
5. **Rank + remediate.** Give the cheapest correct fix. Prefer platform primitives (parameterized queries, framework auth) over hand-rolled crypto.

## Files included
- `references/secure-coding-checklist.md` — the OWASP-aligned review checklist.
- `references/prompt-injection.md` — defending agents/LLM features against untrusted content.

## Core checklist (summary — full list in references)
- **Input:** validate/parameterize everything; no string-built SQL/shell/HTML; canonicalize paths.
- **AuthN/Z:** enforce on the server for *every* request; deny by default; check object-level ownership (no IDOR).
- **Secrets:** env/secret-manager only; never in code, logs, or errors (the `secret-scan` hook enforces).
- **Crypto:** vetted libraries; TLS in transit; encrypt sensitive data at rest; no home-grown crypto.
- **Errors:** fail closed; don't leak stack traces / internals to clients.
- **Dependencies:** pin + scan (SCA); no unvetted transitive risk (`dependency-update` skill).
- **Money/PII (fintech):** idempotency keys, audit trail, least-data retention, tamper-evident logs.
- **LLM features:** treat model/tool output and fetched content as untrusted; sandbox tool use; see `references/prompt-injection.md`.

## Best practices
- Security review is **mandatory and non-skippable** for auth/money/PII changes.
- Shift left: threat-model at design time, not after code.
- Every finding needs an exploit scenario or it's noise.

## Anti-patterns
- "We'll add auth later." · Rolling your own crypto/session. · Trusting client-side validation. · Logging tokens/PII. · Disabling the security hooks to "move fast".
