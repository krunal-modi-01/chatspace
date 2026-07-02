# Code Review Checklist

Companion to the `code-review` skill. Every non-nit finding needs a concrete failure scenario.

## Severity rubric
| Severity | Meaning | Blocks merge? |
|---|---|---|
| **Critical** | Data loss, security vulnerability, corruption, crash on a realistic path | Yes |
| **Major** | Wrong behavior on a plausible input, missing error handling, significant perf regression | Yes |
| **Minor** | Narrow edge-case bug, weak/missing test, maintainability issue | Author's call |
| **Nit** | Style, naming, preference | No — optional |

## Correctness
- [ ] Edge cases: empty, null/undefined, zero, negative, max, single-element, duplicates.
- [ ] Off-by-one and boundary conditions on loops/indexes/ranges.
- [ ] Error/failure paths handled — not just the happy path; errors not swallowed.
- [ ] Concurrency: shared mutable state, races, lost updates, correct locking/idempotency.
- [ ] Resource handling: files/connections/locks released; no leaks.
- [ ] Time/locale: timezones, DST, encoding, floating-point money.
- [ ] The change actually matches the stated intent.

## Security (escalate non-trivial to the security skill)
- [ ] Untrusted input validated and bounded at the boundary.
- [ ] Injection prevented: parameterized queries, no shell/template interpolation of input.
- [ ] AuthN present; AuthZ checked on the target object (not just the route) — no IDOR.
- [ ] No secrets in code, config, or logs; PII minimized and not logged.
- [ ] Output encoded/escaped for its sink (HTML/SQL/shell/URL).

## Performance
- [ ] No N+1 queries; batched access where looping over rows.
- [ ] Collections paginated/bounded; no unbounded allocations.
- [ ] No expensive work repeated in a hot loop; algorithmic complexity fits real data size.
- [ ] No chatty synchronous calls on the hot path; timeouts on outbound calls.
- [ ] Concern raised only with a plausible cost — no micro-opt demands without evidence.

## Maintainability & reuse
- [ ] Not reinventing an existing utility/pattern — reuse over duplication.
- [ ] Names clear; complexity justified; consistent with codebase conventions.
- [ ] Tests present and testing behavior (incl. failure cases), not implementation details.
- [ ] Public API/contract changes are backward-compatible or versioned.
- [ ] Docs/comments updated where behavior or contracts changed.

## Verdict discipline
- [ ] Blocking items are only Critical/Major.
- [ ] Nits explicitly marked optional; blockers listed first.
- [ ] Each finding includes the input/sequence that triggers the failure.
- [ ] If correct, safe, and tested → approve.
