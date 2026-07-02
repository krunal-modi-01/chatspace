# Threat Model — <Feature / System>

> Owner: `security-reviewer` (with `architect`). Method: STRIDE. Skill: `security`.

## 1. Scope & assets
What's in scope. Sensitive assets (credentials, money, PII, tokens) and their value to an attacker.

## 2. Trust boundaries & data flow
Diagram entry points, trust boundaries, and where data crosses them. Mark attacker-controlled inputs.

```
[Untrusted client] ══boundary══> [API] ──> [Service] ──> [DB (PII)]
```

## 3. STRIDE analysis
| Threat | Category | Asset/Boundary | Likelihood | Impact | Mitigation | Status |
|--------|----------|----------------|-----------|--------|-----------|--------|
| e.g. Forged JWT | Spoofing | API auth | Med | High | Verify sig + short TTL + rotation | Planned |
| Tampered amount | Tampering | Txn endpoint | Med | High | Server-side validation + signed request | |
| Missing audit | Repudiation | Money move | Low | High | Immutable audit log | |
| PII leak in logs | Info-disclosure | Logging | Med | High | Log scrubbing + secret-scan | |
| Flood | DoS | API | Med | Med | Rate limit + autoscale | |
| IDOR | Elevation | Object access | High | High | Object-level authZ | |

## 4. Abuse cases
How a malicious actor would try to misuse the feature (fraud, replay, enumeration).

## 5. Residual risk & sign-off
Accepted risks (with owner) and the security 🔒 go/no-go decision.
