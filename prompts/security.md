# Security Prompt — v1.0.0
**Agent:** `security-reviewer` · **Skills:** `security` · **Output:** `templates/threat-model.md` + ranked findings + go/no-go
**Use when:** designing/reviewing anything touching auth, secrets, money, PII, or untrusted input; or triaging a vuln-scan hit.

**Variables:** `{{TARGET}}` `{{DATA_FLOW}}` `{{COMPLIANCE}}`

---

Perform a security review of {{TARGET}}. Data flow / trust boundaries: {{DATA_FLOW}}. Compliance regime: {{COMPLIANCE}}.

1. **Map the surface:** trust boundaries, entry points, sensitive assets, attacker-controlled inputs.
2. **STRIDE** each boundary → `templates/threat-model.md`.
3. Review against the OWASP-aligned checklist (`.claude/skills/security/references/secure-coding-checklist.md`): access control/IDOR, injection, crypto/secrets, authN, SSRF, logging, and the fintech add-ons (idempotency, audit, PII minimization) where relevant.
4. If the target includes an LLM/agent feature, apply `references/prompt-injection.md` (treat external content as untrusted; gate effects).
5. For each finding: **CWE id · severity · concrete exploit scenario · cheapest correct remediation**. No exploit path → mark *theoretical*.
6. Prefer platform primitives (parameterized queries, framework auth) over hand-rolled security.
7. Give the 🔒 **go / no-go** for the security gate; this gate is mandatory and non-skippable for auth/money/PII.

Verify, don't assume. Never approve on unexamined trust in client-side controls.
