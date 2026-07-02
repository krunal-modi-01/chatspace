# Secure Coding Checklist (OWASP ASVS / Top-10 aligned)

Use during implementation and review. Map each finding to a CWE id.

## A01 Broken Access Control
- [ ] AuthZ enforced server-side on every endpoint (deny by default).
- [ ] Object-level ownership checked (no IDOR — can user A read user B's record by changing an id?).
- [ ] No client-trusted role/permission flags.
- [ ] Directory traversal prevented (canonicalize + allowlist paths).

## A02 Cryptographic Failures
- [ ] TLS enforced in transit; HSTS on web.
- [ ] Sensitive data encrypted at rest; keys in a KMS, rotated.
- [ ] Vetted algorithms only (AES-GCM, Argon2/bcrypt/scrypt for passwords). No MD5/SHA1 for security.
- [ ] No secrets in code/logs/URLs.

## A03 Injection
- [ ] SQL: parameterized queries / ORM bindings only. Never string concatenation.
- [ ] OS command: avoid shelling out; if unavoidable, no shell, arg arrays, allowlist.
- [ ] Output encoding for the sink (HTML/attr/JS/URL) to stop XSS.
- [ ] LDAP/NoSQL/template injection considered.

## A04 Insecure Design
- [ ] Threat model exists for new surfaces (STRIDE).
- [ ] Abuse cases + rate limits defined.
- [ ] Secure defaults; fail closed.

## A05 Security Misconfiguration
- [ ] No default creds; unused features/ports off.
- [ ] Security headers (CSP, X-Content-Type-Options, etc.).
- [ ] Verbose errors disabled in prod.

## A06 Vulnerable & Outdated Components
- [ ] SCA clean (no HIGH/CRITICAL); dependencies pinned.
- [ ] Supply-chain: lockfile committed, provenance checked.

## A07 Identification & Authentication Failures
- [ ] Strong password storage; MFA where warranted.
- [ ] Session tokens rotated on privilege change; secure/HttpOnly/SameSite cookies.
- [ ] Brute-force / credential-stuffing protection (rate limit, lockout).

## A08 Software & Data Integrity Failures
- [ ] Signed artifacts / verified updates.
- [ ] Deserialization of untrusted data avoided or guarded.
- [ ] CI/CD pipeline integrity (protected branches, signed commits optional).

## A09 Logging & Monitoring Failures
- [ ] Security events logged (authn, authz failures, high-value actions) — without secrets/PII.
- [ ] Tamper-evident audit trail for money/PII actions.
- [ ] Alerts wired for anomalies.

## A10 Server-Side Request Forgery (SSRF)
- [ ] Outbound requests to user-supplied URLs are allowlisted; no access to metadata endpoints/internal ranges.

## Fintech / regulated add-ons
- [ ] Idempotency keys on money-moving endpoints (no double-spend on retry).
- [ ] Double-entry / balance invariants enforced transactionally.
- [ ] PII minimized + retention-bounded; right-to-erasure supported.
- [ ] Audit log immutable and reconciled.
