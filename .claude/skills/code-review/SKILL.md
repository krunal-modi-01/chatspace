---
name: code-review
description: Reviewing a code diff — ranking findings by severity, applying correctness/security/performance/maintainability lenses, requiring a concrete failure scenario for every issue raised, favoring reuse over duplication, and rendering a disciplined approve/request-changes verdict. Use when reviewing a PR or diff, before approving a change, or when asked whether a change is safe to merge. Used by the code-reviewer agent. Stack-agnostic.
---
# Code Review Skill

## Purpose
Review a diff so that real defects are caught before merge and the author's time is respected. Every finding is ranked by severity and backed by a concrete failure scenario — not opinion. The verdict is disciplined: block only on things that genuinely should block.

## When invoked
- The **code-reviewer** agent uses this on any PR/diff. Security-heavy diffs additionally go to `security` (security-reviewer); performance-critical ones to `performance`.
- Triggered by: "review this PR/diff", "is this safe to merge?", "look over these changes", pre-merge gate.
- Consumes the diff, its context, and the change's stated intent; produces ranked findings and a verdict.

## Inputs
- The diff and enough surrounding code to judge it (not just the changed lines).
- The intent: the PR description, linked issue/spec, and what problem it claims to solve.
- Project conventions, existing utilities/patterns, and the test suite / CI results.

## Outputs
- Findings, each with: **severity**, location, the **concrete failure scenario** (the input/sequence that breaks), and a suggested direction.
- Notes on reuse/duplication and simplification opportunities.
- A clear verdict: **approve**, **approve-with-nits**, or **request-changes**, with the blocking items called out.

## Procedure
1. **Understand intent first.** Read the description and linked issue. Review against *what the change is supposed to do* — a diff that's clean but solves the wrong problem still fails review. If intent is unclear, that's the first finding.
2. **Read beyond the diff.** Open the surrounding code, callers, and callees. Many defects live at the boundary between changed and unchanged code (a new caller violating an old invariant). Reviewing only the highlighted lines misses these.
3. **Pass the correctness lens.** For each change ask: what input or ordering breaks this? Check edge cases (empty, null, zero, max, unicode, timezone), off-by-one, error paths, concurrency (races, shared mutable state), and resource handling (leaks, unclosed handles). Verify the happy path *and* the failure path.
4. **Pass the security lens.** Untrusted input validated? Injection (SQL/command/template) parameterized? AuthN/AuthZ checked on the right object, not just the route? Secrets absent from code/logs? PII handled? Escalate anything non-trivial to `security`. (See `references/review-checklist.md`.)
5. **Pass the performance lens.** N+1 queries, unbounded loops/allocations, missing pagination, chatty network calls on the hot path, needless work in a tight loop. Flag algorithmic complexity that won't scale to real data volumes — but don't demand micro-optimizations without a measured cost.
6. **Pass the maintainability & reuse lens.** Is this reinventing something the codebase already has? Prefer reuse over duplication — point to the existing utility. Is it needlessly complex? Names clear? Is the change consistent with established patterns? Are there tests, and do they test behavior (including failure cases) rather than implementation?
7. **Require a concrete failure scenario for every non-nit finding.** Don't write "this could be a problem" — write "if `items` is empty, line 42 divides by zero and 500s". If you can't produce a scenario, it's a preference (a nit) or nothing. This is the core discipline: it keeps reviews honest and actionable, and lets the author reproduce the issue.
8. **Rank by severity.** Use a consistent scale:
   - **Critical / blocking** — data loss, security hole, corruption, crash on a realistic path.
   - **Major** — incorrect behavior on a plausible input, missing error handling, significant perf regression.
   - **Minor** — narrow-edge-case bug, weak test, maintainability issue.
   - **Nit** — style/naming/preference; explicitly optional, never blocking.
   Label each finding so the author knows what must change vs what's a suggestion.
9. **Separate must-fix from nice-to-have, and don't nitpick-bomb.** A wall of nits buries the one critical bug. Lead with the blocking items. Prefer suggesting the fix direction over just flagging.
10. **Render the verdict with discipline.** Block only on critical/major items. Don't hold a PR hostage over nits or personal style. If it's correct, safe, and tested, approve it — trust the author on the small stuff. Where CI/tests would catch it, defer to CI rather than manual nitpicking.

## Best practices
- Every finding names the input/sequence that triggers the failure — reproducible, not vague.
- Review intent, then boundaries, then the diff — not the diff in isolation.
- Rank ruthlessly; lead with blockers; mark nits as optional.
- Reuse over duplication — point to the existing helper instead of accepting a copy.
- Be specific and kind: critique the code, suggest a direction, assume competence.
- Approve when it's correct and safe; a review is not a rewrite request.

## Anti-patterns
- **Findings with no failure scenario** — "this looks risky" that the author can't act on.
- **Nitpick-bombing** — 30 style comments and zero mention of the real bug.
- **Rubber-stamp / LGTM** on a large diff without reading the boundaries.
- **Reviewing only changed lines** and missing the broken caller in unchanged code.
- **Blocking on preference** — style, naming, or "how I'd have done it".
- **Demanding micro-optimizations** with no measured cost, or ignoring a genuine N+1.
- **Rewriting the PR in comments** instead of pointing at the smallest safe fix.

## Files included
- `references/review-checklist.md` — the correctness/security/performance/maintainability checklist and severity rubric.
