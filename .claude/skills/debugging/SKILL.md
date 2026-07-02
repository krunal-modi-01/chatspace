---
name: debugging
description: Systematic debugging — reproduce, isolate, hypothesize, and root-cause a defect from logs, traces, and code. Use when a test is failing, a bug is reported, behavior is wrong, or an incident needs diagnosis. Emphasizes finding the true cause, not patching the symptom. Used by the bug-investigator agent. Stack-agnostic.
---

# Debugging Skill

## Purpose
Turn "it's broken" into a precise, proven root cause and a regression-guarded fix — via method, not guessing.

## When invoked
A failing test, a reported defect, wrong output, a production incident, or an unexplained regression. Primary skill of `bug-investigator`.

## Inputs
Symptom description, reproduction steps, environment, logs/traces (`monitoring` MCP), and the change history (`git` MCP — blame/bisect).

## Outputs
A deterministic reproduction, a **failing test** capturing the bug, the identified root cause, and a minimal fix specification handed to the owning build agent.

## Procedure
1. **Reproduce deterministically.** No fix begins before you can trigger the bug on demand. If it's flaky, stabilize the repro first (control time/concurrency/data).
2. **Capture it as a failing test** (red). This proves the bug exists and guards against regression.
3. **Localize.** Binary-search the space: `git bisect` across commits, or bisect the code path (disable halves, add probes). Read the logs/traces along the failing path.
4. **Hypothesize → test one variable at a time.** Change one thing, observe, revert if it wasn't it. Keep a short log of what you ruled out.
5. **Find the root cause (5 whys).** Distinguish the *trigger* from the *underlying cause*. "Null pointer" is a symptom; "we never validated the upstream response" is a cause.
6. **Fix minimally at the root**, turn the test green, run the full suite for regressions.
7. **Record** the cause + a prevention idea (a gate/test that would have caught it) for the postmortem and `knowledge/decisions.md`.

## Best practices
- Change one variable at a time; keep a ruled-out list.
- Trust evidence (logs/traces/repro) over intuition; reproduce before theorizing.
- Prefer `git bisect` for "it worked last week" regressions.
- Keep the reproducing test permanently.

## Anti-patterns
- Fixing the symptom (swallowing the exception) instead of the cause. · "Shotgun debugging" (changing many things at once). · Debugging on prod without a repro. · Deleting/loosening the test to make it pass.
